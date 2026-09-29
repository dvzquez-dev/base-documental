#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Paso 6 del pipeline documental: la fila del Libro de Datos, y un revisor del libro entero.

Qué es el Libro de Datos
------------------------
Una hoja de tres columnas — `Título del Archivo`, `Ubicación del Archivo`, `Palabras Clave` — que
es el índice buscable de todo lo que el equipo ha archivado. Se mantiene a mano desde antes de
que existiera el pipeline.

Por qué esto no es sólo «escribir una fila»
-------------------------------------------
⛔ **Se midieron 45 filas reales el 29/09/2026 y salieron seis defectos distintos**, todos
silenciosos — la hoja no da ningún error, simplemente el documento no aparece cuando alguien lo
busca:

- `Informe_I-1008_25` → ubicación `Informe_l-1005_25.pdf`: **ele minúscula por I mayúscula** *y*
  otro número. Dos errores en una celda.
- `Informe_I-2002_25` → ubicación `Informe_I-3002_25.pdf`, que es **el fichero de otra fila**.
- `Informe_l-1003_25`: ele minúscula en **las dos** columnas, así que ni siquiera desentona.
- `Informe_i-3004_25`: minúscula en A, mayúscula en B.
- `Informe_I-3005_25`: **sin palabras clave**, y la ubicación es «Mixers», que no es un fichero.
- Claves con espacios de sobra y comas colgando (`"…Codigo FPS, "`).

Un índice con la referencia mal escrita es peor que no tenerlo: el documento existe, está
archivado, y **no se encuentra**. Por eso aquí va el revisor además del generador.

⚠️ **La letra no siempre es `S`.** En el libro conviven `S-` (lo actual), `A-` y `I-` (heredados
de antes, todos de la temporada `_25`). Un revisor que exigiera `S-` marcaría en rojo 30 filas
buenas, así que las acepta y las señala aparte como heredadas.

Cómo se prueba
--------------
`python scripts/test_libro_datos.py` — sin red ni credenciales.
"""
import re
import sys
import unicodedata

for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding="utf-8")
    except Exception:  # pragma: no cover
        pass


COLUMNAS = ("Título del Archivo", "Ubicación del Archivo", "Palabras Clave")

# Las letras que de verdad aparecen en el libro. `S` es la actual; `A` e `I` son heredadas.
# 📏 Los prefijos de tipo que de verdad aparecen en el libro, contados sobre los 196
#    títulos leídos el 29/09/2026. Son MÁS que los `Tipo Aerotech` de Notion: el libro es
#    más viejo que la base y arrastra `Excel` y `Codigo`, que allí no existen.
#    ⚠️ Sirve para cazar el tipo MAL ESCRITO (`Infrorme_S-6011_25` está en el libro real):
#    un prefijo con una errata ordena lejos de sus hermanos y el documento se pierde.
TIPOS_LIBRO = ("Acta", "Carpeta", "Codigo", "Excel", "Informe", "Manual", "Memoria",
               "Pieza", "Simulacion", "Simulación", "Tabla")

LETRAS = "SAI"
LETRA_ACTUAL = "S"

# ⛔ El `I` y el `l` se dibujan casi igual en la mayoría de tipografías, y ahí es donde se cuela
#    el fallo que nadie ve al releer. Se detecta comparando en minúsculas, no a ojo.
# ⛔ La clase de letras incluye `l` y `1` A PROPÓSITO, aunque no sean letras válidas: si no,
#    `Informe_l-1003_25` **no parsea**, el revisor no dice nada y el defecto que esto existe para
#    cazar sale mudo. Se aceptan para poder **denunciarlas**, no para darlas por buenas.
HOMOGLIFOS = "l1"
_REF = re.compile(u"^([A-Za-zÁÉÍÓÚÑáéíóúñ]+)_([%s%s%s])-([0-9]{3,5})_([0-9]{2})$"
                  % (LETRAS, LETRAS.lower(), HOMOGLIFOS))


def parte_referencia(texto):
    """`(tipo, letra, numero, temporada)` de una referencia, o `None` si no lo es.

    Devuelve la letra y el tipo **tal cual venían**, sin corregir mayúsculas: quien decida si
    `informe_i-3004_25` está mal necesita ver que venía en minúscula, y una función que
    normaliza calladamente se lleva por delante justo la prueba del defecto.
    """
    m = _REF.match(str(texto or "").strip())
    if not m:
        return None
    return (m.group(1), m.group(2), m.group(3), m.group(4))


def es_canonica(texto):
    """¿Es una referencia bien escrita, con la letra en mayúscula?"""
    p = parte_referencia(texto)
    return bool(p) and p[1] in LETRAS


def es_heredada(texto):
    """¿Es una referencia buena pero de las viejas (`A-` / `I-`), no del pipeline de hoy?"""
    p = parte_referencia(texto)
    return bool(p) and p[1] in LETRAS and p[1] != LETRA_ACTUAL


def _confundible(s):
    """La forma de una referencia con los homóglifos aplastados, para comparar.

    `I` (i mayúscula), `l` (ele minúscula) y `1` se dibujan casi igual. Aplastarlos a la misma
    letra es lo que permite decir «estas dos referencias se leen igual y no son la misma».
    """
    s = unicodedata.normalize("NFKD", str(s or ""))
    s = u"".join(c for c in s if not unicodedata.combining(c))
    return s.lower().replace(u"l", u"i").replace(u"1", u"i")


def claves(texto):
    """Las palabras clave de una celda, limpias: sin vacíos, sin espacios de sobra, sin repetir.

    ⚠️ Conserva el orden y **conserva las mayúsculas del primer ejemplar**: `Informe` e `informe`
    son la misma clave para buscar, pero cambiarle a alguien cómo escribió la suya es meterse
    donde no toca. Se quita la repetida, no se reescribe la que queda.
    """
    vistas = set()
    fuera = []
    for trozo in str(texto or "").split(u","):
        t = trozo.strip()
        if not t:
            continue
        k = _confundible(t)
        if k in vistas:
            continue
        vistas.add(k)
        fuera.append(t)
    return fuera


# ── El chip de la carpeta ──────────────────────────────────────────────────────────────────
# ⛔ Lo pidió Daniel así: *«lo que tienes que enlazar es el chip de la carpeta no el link ni
#    hostias… y dentro de la carpeta está el procesamiento con IA y está el archivo original y
#    está, si hay un Word, el PDF»*. La celda de ubicación llevaba el NOMBRE DEL FICHERO en texto
#    plano, que no lleva a ninguna parte.
# ⚠️ **Nadie ha probado nunca que la API de Sheets deje ESCRIBIR chips** — Cowork los pone a mano
#    en el navegador. Por eso `chip_puesto` existe: se relee la celda y se confirma. Sin eso, el
#    pipeline dejaría texto plano haciéndose pasar por chip, y el Libro es justo donde se busca.
URL_CARPETA = "https://drive.google.com/drive/folders/%s"

# La columna donde va: «Ubicación del Archivo», la segunda de `COLUMNAS` (índice 1, 0-based).
COL_UBICACION = 1


def url_carpeta(folder_id):
    """La URL de una CARPETA de Drive, o `None`.

    ⛔ No es `/file/d/<id>/view`: ésa es la de un fichero, y con un id de carpeta abriría un
    error. Son dos formas parecidas que llevan a sitios distintos.
    """
    fid = str(folder_id or "").strip()
    if not fid:
        return None
    return URL_CARPETA % fid


def peticion_chip(hoja_id, fila_1based, folder_id, texto=None):
    """La petición de `batchUpdate` que pone el chip en la celda de ubicación. `None` si falta algo.

    ⛔⛔ **`fila_1based` es 1-based y el índice del rango es 0-based.** Equivocarse aquí **no da
    ningún error**: escribe el chip en la fila de al lado, o sea en el expediente de otra persona.
    Y la fila 0 no existe en 1-based: aceptarla escribiría en la **cabecera**.
    ⛔ **`fields` manda.** Sin él, `updateCells` borra el resto de la celda; y el texto va debajo
    del chip a propósito: si el chip no se renderiza, la ubicación **no queda en blanco**.
    """
    fid = str(folder_id or "").strip()
    uri = url_carpeta(fid)
    if not uri or hoja_id is None or not isinstance(fila_1based, int) or fila_1based < 1:
        return None
    etiqueta = str(texto or "").strip() or fid
    return {
        "updateCells": {
            "range": {
                "sheetId": hoja_id,
                "startRowIndex": fila_1based - 1,
                "endRowIndex": fila_1based,
                "startColumnIndex": COL_UBICACION,
                "endColumnIndex": COL_UBICACION + 1,
            },
            "rows": [{"values": [{
                "userEnteredValue": {"stringValue": etiqueta},
                "chipRuns": [{"startIndex": 0,
                              "chip": {"richLinkProperties": {"uri": uri}}}],
            }]}],
            "fields": "userEnteredValue,chipRuns",
        }
    }


def chip_puesto(celda, folder_id):
    """¿La celda releída lleva de verdad el chip de ESA carpeta? `True`/`False`, nunca lanza.

    ⛔⛔ Compara la URL, no solo que haya un chip: uno que apunta a **otra** carpeta es peor que
    ninguno, porque manda al revisor al expediente equivocado con toda la confianza.
    ⚠️ Y un texto que **contiene** la URL no cuenta: eso es el enlace pelado, que es exactamente
    lo que se pidió no hacer.
    """
    uri = url_carpeta(folder_id)
    if not uri or not isinstance(celda, dict):
        return False
    for run in (celda.get("chipRuns") or []):
        if not isinstance(run, dict):
            continue
        props = ((run.get("chip") or {}).get("richLinkProperties") or {})
        if str(props.get("uri") or "").strip() == uri:
            return True
    return False


def fila(expediente):
    """La fila de tres celdas para el Libro, o `(None, motivos)`.

    La ubicación sale del nombre real en Drive cuando lo hay, y si no de la referencia: es lo que
    hace el libro a mano, y cambiarlo ahora dejaría las filas nuevas distintas de las 1.000 viejas.
    """
    motivos = []
    ref = str(expediente.get("reference") or "").strip()
    if not es_canonica(ref):
        motivos.append(u"la referencia %r no es canónica: la fila no se podría encontrar" % ref)

    ubicacion = str(expediente.get("drive_filename") or "").strip() or ref
    if not ubicacion:
        motivos.append(u"sin ubicación: el índice apuntaría a ninguna parte")

    ks = claves(expediente.get("keywords"))
    if not ks:
        motivos.append(u"sin palabras clave: la fila existe pero no la encuentra ninguna búsqueda")

    if motivos:
        return None, motivos
    return [ref, ubicacion, u", ".join(ks)], []


def revisar(filas):
    """Los defectos de un libro ya escrito. Lista de `(fila_1based, referencia, qué)`.

    `filas` son las filas de datos **sin la cabecera**, cada una una lista de celdas. La fila que
    se reporta cuenta desde 1 e incluye la cabecera, que es como las numera la hoja: quien lea
    esto va a ir a buscarla ahí.
    """
    avisos = []
    por_forma = {}
    ubicaciones = {}

    for i, f in enumerate(filas):
        n = i + 2  # +1 por contar desde 1, +1 por la cabecera
        titulo = (f[0] if len(f) > 0 else u"").strip()
        ubic = (f[1] if len(f) > 1 else u"").strip()
        claves_txt = (f[2] if len(f) > 2 else u"").strip()

        if not titulo:
            avisos.append((n, titulo, u"sin título: la fila no indexa nada"))
            continue

        p = parte_referencia(titulo)
        if not p:
            avisos.append((n, titulo, u"el título no es una referencia con forma "
                                      u"<Tipo>_<Letra>-<NNNN>_<YY>"))
        if p and p[0] not in TIPOS_LIBRO:
            avisos.append((n, titulo, u"el tipo %r no es uno de los del libro: si es una errata, "
                                      u"la fila ordena lejos de sus hermanas" % p[0]))

        if p and p[1] in HOMOGLIFOS:
            avisos.append((n, titulo, u"la letra %r no es una I: se lee igual y ordena distinto, "
                                      u"así que la fila se busca donde no está" % p[1]))
        elif p and p[1] not in LETRAS:
            avisos.append((n, titulo, u"la letra %r va en minúscula: se lee igual que la buena "
                                      u"y ordena distinto" % p[1]))

        # (`len(f) < 3` sobraba: el índice de arriba ya deja `claves_txt` vacío en ese
        #  caso, y una condición que no puede cambiar el resultado sale ciega al mutarla.)
        if not claves_txt:
            avisos.append((n, titulo, u"sin palabras clave: no la encuentra ninguna búsqueda"))

        if not ubic:
            avisos.append((n, titulo, u"sin ubicación"))
        else:
            # ⛔ El defecto más caro y el más difícil de ver: la ubicación apunta a OTRA
            #    referencia. La fila parece perfecta y el enlace lleva al documento de otro.
            pu = parte_referencia(re.sub(r"\.[A-Za-z0-9]{1,5}$", u"", ubic))
            if p and pu and _confundible(u"%s-%s_%s" % (pu[1], pu[2], pu[3])) != \
                    _confundible(u"%s-%s_%s" % (p[1], p[2], p[3])):
                avisos.append((n, titulo, u"la ubicación %r es la de otra referencia" % ubic))
            elif p and pu and (pu[1] != p[1] or pu[2] != p[2]):
                avisos.append((n, titulo, u"la ubicación %r se lee igual pero no se escribe "
                                          u"igual (homóglifo)" % ubic))
            ubicaciones.setdefault(_confundible(ubic), []).append((n, titulo))

        forma = _confundible(titulo)
        por_forma.setdefault(forma, []).append((n, titulo))

    for forma, cuales in sorted(por_forma.items()):
        if len(cuales) > 1:
            donde = u", ".join(u"fila %d (%s)" % (n, t) for n, t in cuales)
            avisos.append((cuales[0][0], cuales[0][1],
                           u"esta referencia se lee igual que otra: %s" % donde))

    for forma, cuales in sorted(ubicaciones.items()):
        if len(cuales) > 1:
            donde = u", ".join(u"fila %d (%s)" % (n, t) for n, t in cuales)
            avisos.append((cuales[0][0], cuales[0][1],
                           u"dos filas apuntan al mismo archivo: %s" % donde))

    avisos.sort(key=lambda a: (a[0], a[2]))
    return avisos


if __name__ == "__main__":  # pragma: no cover
    print("Lógica pura del Paso 6. Para probarla: python scripts/test_libro_datos.py")
