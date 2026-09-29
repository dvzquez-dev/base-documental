#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Banco de `cli.py`. Sin red, sin credenciales, sin reloj.

⛔ Lo primero que se comprueba es lo único que no puede fallar nunca: **sin `--aplicar` no se
escribe**. Todo lo demás es comodidad; eso es lo que protege una hoja que no tiene deshacer.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding="utf-8")
    except Exception:
        pass

import cierre as C
import cli as CLI

fallos = []
hechas = [0]


def ok(cond, que):
    hechas[0] += 1
    if not cond:
        fallos.append(que)


T, F = "TRUE", "FALSE"
AHORA = "2026-09-29T04:00:00Z"
CAB = ["request_id"] + list(C.BANDERAS) + ["updated_at", "last_error", "retry_count"]
POR_CERRAR = [T, T, T, T, T, T, F, F, T, T, T, T, T, T, T, T, T, T, F]


def fila(rid="R-1"):
    return [rid] + list(POR_CERRAR) + ["", "", ""]


class Doble(object):
    def __init__(self, valores=None, libro=None, revienta=None):
        self.valores = valores if valores is not None else [CAB, fila()]
        self.libro = libro or []
        self.revienta = revienta
        self.llamadas = []
        self.escritas = None

    def leer(self):
        self.llamadas.append("leer")
        if self.revienta == "leer":
            raise RuntimeError(u"la hoja contestó 503")
        return self.valores

    def leer_libro(self):
        self.llamadas.append("leer_libro")
        return self.libro

    def cerrar(self, f):
        self.llamadas.append("cerrar")

    def escribir(self, celdas):
        self.llamadas.append("escribir")
        self.escritas = list(celdas)


# ── 1. Lo que no puede fallar: seco por defecto ────────────────────────────────────────────
d = Doble()
txt, cod = CLI.correr([], d, ahora=AHORA)
ok("escribir" not in d.llamadas, u"¡una pasada SIN --aplicar escribió! %r" % (d.llamadas,))
ok("cerrar" not in d.llamadas, u"¡una pasada SIN --aplicar ejecutó! %r" % (d.llamadas,))
ok("SECO" in txt, u"el informe no dice que fue en seco: %r" % txt[:70])
ok(cod == 0, u"una pasada seca limpia debería salir en 0, sale %d" % cod)
# ⚠️ Y en seco SÍ se ve qué se escribiría: si no, el modo seco no sirve de nada.
ok("HAR" in txt, u"la pasada seca no dice qué haría")

d = Doble()
txt, cod = CLI.correr(["--aplicar"], d, ahora=AHORA)
ok("cerrar" in d.llamadas and "escribir" in d.llamadas,
   u"con --aplicar no ejecuta ni escribe: %r" % (d.llamadas,))
ok("APLICADA" in txt, u"el informe no dice que se aplicó")

# ── 2. Los argumentos ──────────────────────────────────────────────────────────────────────
op, m = CLI.parsear([])
ok(op == {"aplicar": False, "limite": None, "revisar": False, "ingerir": False}, u"los valores por defecto: %r" % (op,))
ok(m == [], u"sin argumentos no debería haber motivos")
ok(CLI.parsear(["--aplicar"])[0]["aplicar"] is True, u"no reconoce --aplicar")
ok(CLI.parsear(["--limite", "3"])[0]["limite"] == 3, u"no reconoce --limite")
ok(CLI.parsear(["--revisar"])[0]["revisar"] is True, u"no reconoce --revisar")
ok(CLI.parsear(["--aplicar", "--limite", "5"])[0] == {"aplicar": True, "limite": 5,
                                                      "revisar": False, "ingerir": False},
   u"no combina --aplicar con --limite")
ok(CLI.parsear(["--ingerir"])[0]["ingerir"] is True, u"no reconoce --ingerir")
ok(CLI.parsear([])[0]["ingerir"] is False, u"ingerir no puede ser el camino por defecto")

# ⛔ Un argumento que no se entiende PARA la pasada. Ignorarlo es como un `--aplciar` mal escrito
#    acaba en una pasada seca que alguien da por aplicada.
for malo, trozo in ((["--aplciar"], "no entiendo"),
                    (["--limite"], "sin número"),
                    (["--limite", "x"], "no es un número"),
                    (["--limite", "0"], "no toca ningún expediente"),
                    (["--limite", "-2"], "no toca ningún expediente"),
                    (["algo"], "no entiendo")):
    op, m = CLI.parsear(malo)
    ok(op is None, u"%r debería parar la pasada" % (malo,))
    ok(m and trozo in m[0], u"el motivo de %r no lo explica: %r" % (malo, m))

op, m = CLI.parsear(["--revisar", "--aplicar"])
ok(op is None and m and "Elige uno" in m[0],
   u"--revisar con --aplicar debería pararse: %r" % (m,))
op, m = CLI.parsear(["--ayuda"])
ok(op is None and m and "uso:" in m[0], u"la ayuda no sale: %r" % (m,))

txt, cod = CLI.correr(["--aplciar"], Doble())
ok(cod == 2, u"un argumento malo debería salir en 2, sale %d" % cod)
ok("no entiendo" in txt, u"no explica el argumento malo")

# ── 3. El tope ─────────────────────────────────────────────────────────────────────────────
d = Doble(valores=[CAB] + [fila("R-%d" % i) for i in range(1, 6)])
txt, _c = CLI.correr(["--aplicar", "--limite", "2"], d, ahora=AHORA)
ok(d.llamadas.count("cerrar") == 2,
   u"el tope no limita: cierra %d de 5" % d.llamadas.count("cerrar"))
# ⚠️ El tope se aplica a las filas, no a la hoja: cortar la hoja se llevaría la CABECERA.
ok(d.escritas, u"con tope debería escribirse algo: %r" % (d.escritas,))
ok(all(c[0][0].isalpha() for c in d.escritas),
   u"las celdas no tienen letra de columna: se ha perdido la cabecera: %r" % (d.escritas,))

d = Doble(valores=[CAB] + [fila("R-%d" % i) for i in range(1, 6)])
CLI.correr(["--aplicar"], d, ahora=AHORA)
ok(d.llamadas.count("cerrar") == 5, u"sin tope deberían tocarse las 5")

# ── 4. El repaso ───────────────────────────────────────────────────────────────────────────
# 📏 La fila real con closed=TRUE y todo lo demás en FALSE, y una fila real del Libro.
CERRADA_VACIA = ["R-real-2"] + [T] + [F] * 17 + [T] + ["", "", ""]
LIBRO_MALO = [["Informe_I-1008_25", "Informe_l-1005_25.pdf", "Informe, I+D"]]
d = Doble(valores=[CAB, CERRADA_VACIA], libro=LIBRO_MALO)
txt, cod = CLI.correr(["--revisar"], d, ahora=AHORA)
ok("cerrar" not in d.llamadas, u"¡el repaso ejecutó el pipeline! %r" % (d.llamadas,))
ok("escribir" not in d.llamadas, u"¡el repaso escribió!")
ok("CIERRE" in txt, u"el repaso no ve el cierre injustificado: %r" % txt)
ok("LIBRO" in txt, u"el repaso no ve el defecto del Libro: %r" % txt)
ok(cod == 1, u"un repaso con cosas que no cuadran debería salir en 1, sale %d" % cod)
ok("R-real-2" in txt, u"el repaso no identifica la fila por su request_id")

# ⚠️ La fila «limpia» tiene que estar además CERRADA: `fila()` está publicada y sin cerrar, y
#    el revisor tiene razón en señalarla — lo cual es justo lo que este banco quiere que haga.
CERRADA_OK = ["R-ok"] + POR_CERRAR[:-1] + [T] + ["", "", ""]
d = Doble(valores=[CAB, CERRADA_OK], libro=[])
txt, cod = CLI.correr(["--revisar"], d, ahora=AHORA)
ok("todo cuadra" in txt, u"un repaso limpio no lo dice: %r" % txt)
ok(cod == 0, u"un repaso limpio debería salir en 0, sale %d" % cod)
# ⛔ Y el de al lado: una publicada SIN cerrar SÍ sale, que es media razón de ser del repaso.
d = Doble(valores=[CAB, fila()], libro=[])
txt, _c = CLI.correr(["--revisar"], d, ahora=AHORA)
ok("listo para cerrar" in txt,
   u"el repaso no ve un expediente terminado que nadie cerró: %r" % txt)

# La cabecera duplicada sale en el repaso.
d = Doble(valores=[CAB + ["closed"], fila() + [""]])
txt, _c = CLI.correr(["--revisar"], d)
ok("CABECERA" in txt and "closed" in txt, u"el repaso no ve la columna duplicada: %r" % txt)

# Sin `leer_libro` el repaso sigue funcionando: no todo el mundo tiene acceso al Libro.
class SoloHoja(object):
    def leer(self):
        return [CAB, CERRADA_VACIA]

txt, cod = CLI.correr(["--revisar"], SoloHoja())
ok("CIERRE" in txt, u"sin acceso al Libro el repaso debería mirar igual la hoja: %r" % txt)

# ── 5. Los códigos de salida ───────────────────────────────────────────────────────────────
# ⚠️ Es lo único que mira una tarea programada: una pasada con errores en 0 se ve VERDE para
#    siempre en el historial.
class SinLeer(object):
    pass

txt, cod = CLI.correr([], SinLeer())
ok(cod == 2, u"sin `leer` debería salir en 2, sale %d" % cod)
# ⛔ Se ata al mensaje CONCRETO, no a que aparezca la palabra «leer»: el error genérico
#    «al leer la hoja: TypeError…» también la lleva, así que las dos ramas satisfacían la
#    comprobación y la guarda salía CIEGA al mutarla.
ok("no existe" in txt, u"no dice que `servicios.leer` NO EXISTE: %r" % txt)
ok("TypeError" not in txt,
   u"llega a llamar a `None()` en vez de decirlo antes: %r" % txt)

d = Doble(revienta="leer")
txt, cod = CLI.correr([], d)
ok(cod == 2, u"si falla la lectura debería salir en 2, sale %d" % cod)
ok("503" in txt, u"el error de lectura no conserva lo que dijo el mundo: %r" % txt)

# Una pasada que no puede anotar lo hecho NO sale en 0.
d = Doble(valores=[CAB + ["closed"], fila() + [""]])
txt, cod = CLI.correr(["--aplicar"], d, ahora=AHORA)
ok(cod == 1, u"con avisos debería salir en 1, sale %d" % cod)

# ── El repaso canta las filas DESPLAZADAS ────────────────────────
# ⚠️ Escribir el detector y no llamarlo desde el repaso lo deja siendo una función que nadie
#    ejecuta: la avería de «escrita entera, muerta en el cable de en medio».
_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_CAB2 = ["request_id", "range_end", "annex_copied_count", "closed"]
_lineas, _n = CLI.revisar_datos([_CAB2, ["SOL-9", "Es un informe bimensual", _MIME, "FALSE"]], [])
ok(any(l.startswith("COLUMNA") for l in _lineas),
   u"⛔ el repaso no canta una fila desplazada: %r" % (_lineas,))
ok(any("annex_copied_count" in l for l in _lineas),
   u"el aviso no dice en qué columna: %r" % (_lineas,))
ok(any("SOL-9" in l for l in _lineas), u"el aviso no dice de qué expediente es")
ok(_n == len(_lineas), u"el recuento y las líneas no cuadran")
_lineas, _ = CLI.revisar_datos([_CAB2, ["SOL-8", "6499", "7", "FALSE"]], [])
ok(not [l for l in _lineas if l.startswith("COLUMNA")],
   u"canta sobre una fila sana: %r" % (_lineas,))

# ── El repaso canta lo que no cuadra en los ANEXOS ───────────────
_CAB3 = ["request_id", "annex_drive_file_ids_json", "annex_final_file_ids_json",
         "annex_copied_count", "closed"]
_l, _ = CLI.revisar_datos(
    [_CAB3, ["SOL-7", "a, b", '["x","y"]', "1", "FALSE"]], [])
ok(any(l.startswith("ANEXOS") for l in _l), u"⛔ el repaso no mira los anexos: %r" % (_l,))
ok(any("miente" in l for l in _l), u"no dice qué no cuadra: %r" % (_l,))
ok(any("SOL-7" in l for l in _l), u"no dice de qué expediente es")
# ⚠️ Y la fila real, que trae los ids por comas y está en regla, **no canta**: un aviso que
#    sale sobre trabajo bien hecho enseña a ignorarlo.
_l, _ = CLI.revisar_datos(
    [_CAB3, ["SOL-6", "a, b", '["x", "y"]', "2", "FALSE"]], [])
ok(not [l for l in _l if l.startswith("ANEXOS")],
   u"⛔ canta sobre unos anexos en regla que venían por comas: %r" % (_l,))

# ── Un expediente publicado SIN PDF se ve ─────────────────────
# ⛔ Casi todos los expedientes llegan en DOCX y **el PDF no lo genera nadie todavía**. Sin
#    aviso, un expediente se publica con el DOCX colgado — que Notion no previsualiza— y queda
#    igual de «completo» que uno con su PDF. Es lo mismo que enseñó `SIN_IMPLEMENTAR`: lo que
#    no se hace se **dice**, no se disimula.
_CAB5 = ["request_id", "notion_page_created", "drive_docx_file_id", "drive_primary_file_id"]
_l, _ = CLI.revisar_datos(
    [_CAB5, ["SOL-D", "TRUE", "1Qgoq3pIdGa29hYzgybJs8Cw0l95-_oCQ", ""]], [])
ok(any(l.startswith("PDF ") for l in _l), u"⛔ no avisa de un expediente sin PDF: %r" % (_l,))
ok(any("SOL-D" in l for l in _l), u"no dice de qué expediente es: %r" % (_l,))
# ⚠️ Con su PDF, callado. Y sin página creada tampoco canta: aún no toca.
_l, _ = CLI.revisar_datos(
    [_CAB5, ["SOL-E", "TRUE", "1Qgoq3pIdGa29hYzgybJs8Cw0l95-_oCQ",
             "13A2NAKagBGH4LXQI6rGasDhr3SFo2LNX"]], [])
ok(not [l for l in _l if l.startswith("PDF ")], u"canta con el PDF puesto: %r" % (_l,))
_l, _ = CLI.revisar_datos(
    [_CAB5, ["SOL-F", "FALSE", "1Qgoq3pIdGa29hYzgybJs8Cw0l95-_oCQ", ""]], [])
ok(not [l for l in _l if l.startswith("PDF ")],
   u"⚠️ canta sobre un expediente que aún no se ha publicado: %r" % (_l,))

# ── El repaso canta un id de Drive con basura dentro ──────────────
_l, _ = CLI.revisar_datos(
    [["request_id", "drive_folder_id", "closed"],
     ["SOL-9", "'1x9r1xo4X4wcCtNy1Crd7zc8bJm-6UC6X", "FALSE"]], [])
ok(any(l.startswith("ID  ") for l in _l), u"⛔ el repaso no mira los ids: %r" % (_l,))
ok(any("drive_folder_id" in l for l in _l), u"no dice qué columna: %r" % (_l,))
ok(any("SOL-9" in l for l in _l), u"no dice de qué expediente es")
_l, _ = CLI.revisar_datos(
    [["request_id", "drive_folder_id", "closed"],
     ["SOL-8", "1x9r1xo4X4wcCtNy1Crd7zc8bJm-6UC6X", "FALSE"]], [])
ok(not [l for l in _l if l.startswith("ID  ")], u"canta sobre un id bueno: %r" % (_l,))

# ── El repaso mira también las CADENAS de reentrega ───────────────
# ⚠️ `sustitucion.revisar` se escribió entero y **nadie lo llamaba**: la misma forma que ya
#    dejó muertas `analisis.etiquetas` y media `notion_api`. Un revisor que no corre no revisa.
_CAB4 = ["request_id", "reference", "replaces_document", "replacement_reference",
         "replacement_reason", "closed"]
_l, _ = CLI.revisar_datos(
    [_CAB4, ["SOL-5", "Ref_5", "SOL-QUE-NO-ESTA", "Ref_5", "un motivo", "FALSE"]], [])
ok(any(l.startswith("CADENA") for l in _l), u"⛔ el repaso no mira las cadenas: %r" % (_l,))
ok(any("no está en la hoja" in l for l in _l), u"no dice qué falla: %r" % (_l,))
ok(any("SOL-5" in l for l in _l), u"no dice de qué expediente es")
# ⚠️ Y una cadena en regla no canta.
_l, _ = CLI.revisar_datos(
    [_CAB4, ["SOL-A", "Ref_A", "No", "", "", "FALSE"],
     ["SOL-B", "Ref_A", "SOL-A", "Ref_A", "errata", "FALSE"]], [])
ok(not [l for l in _l if l.startswith("CADENA")],
   u"⛔ canta sobre una cadena en regla: %r" % (_l,))

# ── EL WORKFLOW TIENE QUE PASAR TODO LO QUE EL CÓDIGO LEE ──────────
# ⛔⛔ Medido el 29/09: el código que corre la pasada lee **cuatro** variables de entorno y el
#    workflow declaraba **tres**. La que faltaba era `DOMINIO_EQUIPO`, o sea que la primera
#    publicación de verdad se habría parado en seco — con todos los secretos puestos y sin que
#    nada en el repo lo dijera. Las dos mitades del contrato viven en ficheros distintos y en
#    lenguajes distintos, que es justo donde nadie mira.
# ⚠️ Se descubren **los módulos que el propio `cli.py` alcanza**, con `ast`: escribir la lista
#    a mano es escribir la tercera copia del contrato.
import ast as _ast
import io as _io
import re

_AQUI = os.path.dirname(os.path.abspath(__file__))


def _lee_entorno(mod, vistos):
    """Las variables de entorno que lee `mod` y todo lo que importa, transitivamente."""
    if mod in vistos:
        return set()
    vistos.add(mod)
    ruta = os.path.join(_AQUI, mod + ".py")
    if not os.path.exists(ruta):
        return set()
    arbol = _ast.parse(_io.open(ruta, encoding="utf-8").read())
    fuera = set()
    for nodo in _ast.walk(arbol):
        if isinstance(nodo, _ast.Import):
            for a_ in nodo.names:
                fuera |= _lee_entorno(a_.name, vistos)
        elif isinstance(nodo, _ast.ImportFrom) and nodo.module:
            fuera |= _lee_entorno(nodo.module, vistos)
        elif isinstance(nodo, _ast.Call):
            f = nodo.func
            if (isinstance(f, _ast.Attribute) and f.attr == "get"
                    and isinstance(f.value, _ast.Attribute) and f.value.attr == "environ"
                    and nodo.args and isinstance(nodo.args[0], _ast.Constant)):
                fuera.add(nodo.args[0].value)
        elif (isinstance(nodo, _ast.Subscript) and isinstance(nodo.value, _ast.Attribute)
              and nodo.value.attr == "environ" and isinstance(nodo.slice, _ast.Constant)):
            fuera.add(nodo.slice.value)
    return fuera


_PEDIDAS = set(v for v in _lee_entorno("cli", set()) if isinstance(v, str) and v.isupper())
_YML = os.path.join(os.path.dirname(_AQUI), ".github", "workflows", "pipeline.yml")
_TXT = _io.open(_YML, encoding="utf-8").read() if os.path.exists(_YML) else ""

# ⛔⛔ Se leen las DECLARACIONES, no el texto del fichero. Con un `in _TXT` la comprobación
#    salió **CIEGA**: el comentario que yo mismo escribí al añadir `DOMINIO_EQUIPO` nombra la
#    variable, así que borrar la línea que la pasa **no cambiaba nada**. Es la trampa de «el
#    comando que re-mide cuenta la prosa del arreglo», y aquí la escribí yo.
_DECLARADAS = set(re.findall(r"(?m)^\s*([A-Z][A-Z0-9_]+):\s*\$\{\{", _TXT))

ok(_TXT, u"no se encuentra `.github/workflows/pipeline.yml`: el contrato no se puede mirar")
ok("DOMINIO_EQUIPO" in _PEDIDAS,
   u"⚠️ el descubridor no ve `DOMINIO_EQUIPO`: mide mal y diría que todo cuadra")
ok(len(_PEDIDAS) >= 4, u"el descubridor ve muy poco (%d): %r" % (len(_PEDIDAS), sorted(_PEDIDAS)))
ok(len(_DECLARADAS) >= 4,
   u"⚠️ el lector del workflow ve %d declaraciones: si viera 0, todo saldría «falta» y el "
   u"caso sería inútil al revés" % len(_DECLARADAS))
_faltan = sorted(v for v in _PEDIDAS if v not in _DECLARADAS)
ok(_faltan == [],
   u"⛔ el workflow no pasa %r: la pasada se pararía con los secretos puestos y sin que nada "
   u"en el repo lo dijera" % (_faltan,))

# ── LA INGESTA, DE PUNTA A PUNTA ───────────────────────────
_CABR = [u"Marca temporal", u"Dirección de correo electrónico", u"Nombre y apellidos",
         u"Título breve y descriptivo", u"Tipo de documento", u"Subsistema o unidad",
         u"Elige la subcarpeta de la UCT en la que deseas incluir el archivo:",
         u"Adjunta aquí el documento", u"¿Sustituye o revisa otro documento?",
         u"Indica la referencia del archivo que deseas sustituir",
         u"Motivo de la sustitución o revisión"]
_RUTAS_IN = [{"unit_key": "uct", "subfolder_key": "actas", "range_start": "6301",
              "range_end": "6499", "drive_folder_id": "F-actas", "active": "TRUE"}]
_SOLIS = [["request_id", "form_row", "reference", "reserved_id"]]

def _fila(n, tit, sus="No", ref=""):
    return [u"2/10/2026 10:00:00", u"a@b.c", u"Quien", tit, u"Acta",
            u"Unidad de Coordinación Técnica (6)", u"Actas - (3/4)",
            u"https://drive.google.com/open?id=1AAA", sus, ref, u""]

_f, _av = CLI.ingerir([_CABR, _fila(2, u"Acta de octubre")], _SOLIS, _RUTAS_IN, [])
ok(len(_f) == 1 and _av == [], u"no ingiere una respuesta buena: %r / %r" % (_f, _av))
ok(_f and _f[0]["reference"] == u"Acta_S-6301_27",
   u"⛔ la referencia no es la que toca — 2/10/2026 es temporada 26/27, sufijo 27: %r"
   % (_f[0].get("reference") if _f else None,))
ok(_f and _f[0]["form_row"] == "2", u"no ata la solicitud a su fila de respuestas")
ok(_f and _f[0]["unit_key"] == "uct" and _f[0]["subfolder_key"] == "actas",
   u"no resuelve la ruta por los números de las etiquetas: %r" % (_f[0],))

# ⚠️ Lo ya ingerido NO se repite: es lo que impide duplicar un expediente cada pasada.
_ya = [["request_id", "form_row", "reference", "reserved_id"], ["SOL-X", "2", "Acta_S-6301_27", "6301"]]
ok(CLI.ingerir([_CABR, _fila(2, u"Acta de octubre")], _ya, _RUTAS_IN, [])[0] == [],
   u"⛔ re-ingiere una respuesta que ya está en SOLICITUDES")

# ⛔ Dos respuestas seguidas de la MISMA ruta no pueden llevarse el mismo número.
_f2, _ = CLI.ingerir([_CABR, _fila(2, u"Acta A"), _fila(3, u"Acta B")], _SOLIS, _RUTAS_IN, [])
ok(len(_f2) == 2, u"no ingiere las dos: %r" % (_f2,))
ok(_f2 and _f2[0]["reserved_id"] != _f2[1]["reserved_id"],
   u"⛔ dos respuestas de la misma ruta se llevan EL MISMO número: %r"
   % ([x.get("reserved_id") for x in _f2],))

# ✅ Una SUSTITUCIÓN reusa el número del original y no reserva otro.
_conviejo = [["request_id", "form_row", "reference", "reserved_id"],
             ["SOL-VIEJA", "9", "Acta_S-6301_27", "6301"]]
_f3, _av3 = CLI.ingerir([_CABR, _fila(2, u"Acta corregida", u"Sí", u"Acta_S-6301_27")],
                        _conviejo, _RUTAS_IN, [])
ok(len(_f3) == 1 and _f3[0]["reserved_id"] == "6301",
   u"⛔ una reentrega se lleva un número nuevo en vez de reusar el del original: %r" % (_f3,))
ok(_f3 and _f3[0]["replaces_document"] == "SOL-VIEJA", u"no anota a quién sustituye")

# ⛔ Y lo que no se puede ingerir sale en avisos SIN parar a los demás.
_f4, _av4 = CLI.ingerir(
    [_CABR, _fila(2, u"Mala", u"Sí", u"Acta_S-9999_27"), _fila(3, u"Buena")],
    _SOLIS, _RUTAS_IN, [])
ok(len(_f4) == 1 and len(_av4) == 1,
   u"⛔ una respuesta rota deja sin entrar a las de detrás: %r / %r" % (_f4, _av4))
ok(_av4 and "fila 2" in _av4[0], u"el aviso no dice qué fila: %r" % (_av4,))

# ⛔ SIN RUTA no se ingiere: archivaría donde no es y sin dar error. (La mutación que quita
#    esta guarda salía ciega: con ruta `None`, `siguiente_id` también devuelve None y la fila
#    caía por el otro camino, así que había que exigir QUÉ aviso da.)
_f5, _av5 = CLI.ingerir([_CABR, _fila(2, u"Sin ruta")], _SOLIS, [], [])
ok(_f5 == [] and len(_av5) == 1, u"sin ruta no debería entrar: %r" % (_f5,))
ok("no hay una sola ruta activa" in _av5[0],
   u"⛔ el aviso confunde «sin ruta» con «rango agotado»: mandan a arreglar cosas distintas. "
   u"Dice: %r" % (_av5,))

# ⛔ Y una sustitución que no se puede atar NO entra, y su aviso lo dice por su nombre.
_f6, _av6 = CLI.ingerir(
    [_CABR, _fila(2, u"Reentrega huérfana", u"Sí", u"Acta_S-9999_27")], _SOLIS, _RUTAS_IN, [])
ok(_f6 == [], u"⛔ una reentrega que apunta a un original inexistente se ingiere igual")
ok(_av6 and "no hay ningún expediente con esa referencia" in _av6[0],
   u"el aviso no dice que el original no existe: %r" % (_av6,))

ok(CLI.ingerir([], _SOLIS, _RUTAS_IN, []) == ([], []), u"sin respuestas no hay nada que ingerir")
ok(CLI.ingerir([_CABR], _SOLIS, _RUTAS_IN, []) == ([], []), u"solo cabecera tampoco")

# ── `--ingerir` corre de verdad, y es SECO salvo --aplicar ───────────
class _SrvIn(object):
    def __init__(self):
        self.anadidas = None

    def leer(self):
        return [["request_id", "form_row", "reference", "reserved_id"]]

    def leer_respuestas(self):
        return [_CABR, _fila(2, u"Acta de octubre")]

    def leer_rutas(self):
        return _RUTAS_IN

    def leer_reservas(self):
        return []

    def anadir_solicitudes(self, filas):
        self.anadidas = filas
        return len(filas)


_s = _SrvIn()
_txt, _cod = CLI.correr(["--ingerir"], _s)
ok("INGESTA" in _txt and "Acta_S-6301_27" in _txt,
   u"la ingesta seca no enseña lo que añadiría: %r" % (_txt,))
ok(_s.anadidas is None, u"⛔ la ingesta SECA ha escrito en SOLICITUDES")
ok("seco" in _txt, u"no dice que fue en seco: %r" % (_txt,))

_s2 = _SrvIn()
_txt2, _cod2 = CLI.correr(["--ingerir", "--aplicar"], _s2)
ok(_s2.anadidas and len(_s2.anadidas) == 1,
   u"⛔ con --aplicar no añade nada: %r" % (_s2.anadidas,))
ok("1 fila" in _txt2, u"no dice cuántas añadió: %r" % (_txt2,))

# ⚠️ Y si el adaptador no sabe leer respuestas, se dice — no se hace como que no había nada.
class _Pelado(object):
    def leer(self):
        return [["request_id"]]


_t3, _c3 = CLI.correr(["--ingerir"], _Pelado())
ok(_c3 == 2 and "leer_respuestas" in _t3, u"un adaptador sin ingesta debería decirlo: %r" % (_t3,))

print("%d comprobaciones" % hechas[0])
if fallos:
    print("\n%d ROJO(S):" % len(fallos))
    for f_ in fallos:
        print("  - %s" % f_)
    sys.exit(1)
print("verde")
