#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""De la hoja a registros y de vuelta a celdas. Sin tocar la hoja.

Qué resuelve
------------
El ejecutor necesita leer `SOLICITUDES` y escribir banderas. Entre la hoja y el código hay dos
traducciones que parecen triviales y no lo son:

1. **Cabecera → índice.** ⛔ `SOLICITUDES` tiene **78 columnas y `unit_label` sale DOS veces**
   (la 11 y la 78), medido el 29/09/2026. Cualquier mapa construido recorriendo la fila 1 se queda
   con **una de las dos** según gane la primera o la última, y las dos pueden divergir — la fila 2
   ya tiene la 78 **vacía** y la 11 llena.

2. **Número de columna → letra de A1.** Es base-26 **biyectiva**, no base-26 normal: no hay
   cifra cero, así que la 26 es `Z` y la 27 es `AA`. Hacerlo con el módulo de toda la vida da
   `A@` o `@A` y escribe en la celda equivocada, que aquí significa **pisar la columna de al
   lado** en la hoja de un pipeline en marcha.

La asimetría que importa
------------------------
Con un nombre duplicado, **leer** devuelve el primero y avisa; **escribir** se niega. Escribir en
una de dos columnas homónimas deja las dos inconsistentes, que es exactamente como llegaron a
estarlo. Leer de más no rompe nada; escribir a ciegas sí.

Cómo se prueba
--------------
`python scripts/test_hoja.py` — sin red ni credenciales.
"""
import json
import sys

for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding="utf-8")
    except Exception:  # pragma: no cover
        pass


def letra_columna(n):
    """La letra de A1 para la columna `n`, contando desde 1. `None` si `n` no vale.

    ⛔ Base-26 **biyectiva**: 26 → `Z`, 27 → `AA`, 52 → `AZ`, 53 → `BA`, 78 → `BZ`. El `- 1` antes
    del `divmod` es lo que hace que no exista una cifra cero; sin él, la 26 sale `A@`.
    """
    try:
        n = int(n)
    except (TypeError, ValueError):
        return None
    if n < 1:
        return None
    fuera = ""
    while n > 0:
        n, resto = divmod(n - 1, 26)
        fuera = chr(ord("A") + resto) + fuera
    return fuera


def indices(cabecera):
    """`(mapa, duplicadas)` desde la fila de cabecera. Las columnas cuentan desde 1.

    `mapa` lleva **la primera** aparición de cada nombre; `duplicadas` es
    `{nombre: [columnas]}` para las que salen más de una vez. Quien escriba tiene que mirar
    `duplicadas` antes — por eso se devuelve, en vez de apañarlo por dentro.
    """
    mapa = {}
    todas = {}
    for i, celda in enumerate(cabecera or []):
        nombre = str(celda if celda is not None else "").strip()
        if not nombre:
            continue
        todas.setdefault(nombre, []).append(i + 1)
        if nombre not in mapa:
            mapa[nombre] = i + 1
    duplicadas = dict((k, v) for k, v in todas.items() if len(v) > 1)
    return mapa, duplicadas


def a_registro(cabecera, fila):
    """Un `dict` desde una fila de datos. Las celdas que faltan quedan como cadena vacía.

    ⚠️ Rellenar con `""` y no con `None` es a propósito: la hoja **devuelve `""`** cuando la celda
    está vacía y **acorta la fila** cuando las últimas están vacías, así que las dos cosas
    significan lo mismo desde la hoja. Que el registro las distinga sería inventarse una
    diferencia que en el origen no existe.
    """
    mapa, _dup = indices(cabecera)
    fila = fila or []
    fuera = {}
    for nombre, col in mapa.items():
        i = col - 1
        v = fila[i] if i < len(fila) else ""
        fuera[nombre] = "" if v is None else v
    return fuera


def a_registros(valores):
    """`(registros, duplicadas)` desde la hoja entera, cabecera incluida.

    Una hoja vacía o con sólo cabecera devuelve `[]`, no revienta: es el estado normal de una hoja
    recién creada y tratarlo como error haría fallar la primera pasada de cada temporada.
    """
    valores = valores or []
    if not valores:
        return [], {}
    cabecera = valores[0]
    _mapa, duplicadas = indices(cabecera)
    return [a_registro(cabecera, f) for f in valores[1:]], duplicadas


def lista_de_celda(valor, nombre=u"la celda"):
    """`(elementos, motivos)` de una celda que trae una lista — **en JSON o separada por comas**.

    ⛔⛔ Una puerta única porque el problema tiene la misma FORMA en dos columnas distintas, y
    curarlo en una sola dejaría la otra rota. Medido en `SOLICITUDES` el 29/09/2026:
    `tags_json` trae lista JSON en 14 filas y **separada por comas en una**; y
    `annex_drive_file_ids_json` trae `[]` en unas filas y **`id, id, id`** en la que tiene anexos.
    Las dos columnas se llaman `_json` y **las dos mienten**.

    ⚠️ Un JSON **roto** sigue siendo un error, no una lista por comas: leerlo «como se pueda»
    convertiría `["a", "b"` en dos elementos llamados `["a"` y `"b"`.
    """
    if isinstance(valor, bytes):
        valor = valor.decode("utf-8", "replace")
    if not isinstance(valor, str):
        if valor is None:
            return [], []
        if isinstance(valor, list):
            return list(valor), []
        return [], [u"%s no es una lista, es %s" % (nombre, type(valor).__name__)]

    txt = valor.strip()
    if not txt:
        return [], []
    try:
        datos = json.loads(txt)
    except Exception:
        if txt[:1] in ("[", "{"):
            return [], [u"%s empieza como JSON y no lo es: %r" % (nombre, valor)]
        trozos = txt.split(",")
        return trozos, [u"%s no venía en JSON sino separada por comas; se han leído %d "
                        u"elementos" % (nombre, len([x for x in trozos if x.strip()]))]
    if datos is None:
        return [], []
    if not isinstance(datos, list):
        return [], [u"%s no es una lista, es %s" % (nombre, type(datos).__name__)]
    return datos, []


# ⛔⛔ Las columnas que **son números enteros**. No es una corazonada: es lo que permite cazar una
#    fila DESPLAZADA. Medido en `SOLICITUDES` el 29/09/2026 — **4 de 17 filas**, las cuatro
#    ingeridas el 09/07, llevan su cola **dos columnas a la izquierda**, así que el tipo MIME cae
#    en `annex_copied_count` (un contador) y el texto libre de `context` cae en `range_end`.
#    ⚠️ Hoy no revienta nada **porque nadie lee esas columnas todavía**. El día que se
#    implementen los anexos, `annex_copied_count` valdrá una cadena de 71 caracteres y se
#    copiarán **cero anexos sin un solo error**. Por eso se caza por el tipo y no por el síntoma.
#    ⛔ Aquí NO van las banderas (`closed`, `approved`…): valen `TRUE`/`FALSE`, y meterlas
#       pondría roja media hoja por hacer lo correcto.
COLUMNAS_ENTERAS = ("form_row", "reserved_id", "range_start", "range_end",
                    "annex_copied_count", "source_size_bytes", "base_database_row",
                    "retry_count", "reminder_count", "partial_alert_count")


def desplazadas(registros):
    """Celdas numéricas que no llevan un número. Lista de `(fila_1based, request_id, col, valor)`.

    ⚠️ Una celda **vacía no es síntoma**: 13 de las 17 filas reales tienen estas columnas en
    blanco, y cantar por eso enseña a ignorar el aviso — que es lo que de verdad lo mata.
    """
    avisos = []
    for i, r in enumerate(registros or []):
        if not isinstance(r, dict):
            continue
        rid = str(r.get("request_id") or "").strip() or u"(sin request_id)"
        for col in COLUMNAS_ENTERAS:
            # ⚠️ Sin `if col not in r`: `r.get(col)` ya devuelve `None` para la que no está, y
            #    `None` sale por el vacío de dos líneas más abajo. La guarda **no se podía
            #    observar** — su mutación salió ciega—, y una guarda que no cambia nada sólo
            #    enseña a confiar en guardas que no hacen nada.
            crudo = r.get(col)
            txt = u"" if crudo is None else str(crudo).strip()
            if not txt:
                continue
            try:
                int(txt)
            except (TypeError, ValueError):
                avisos.append((i + 2, rid, col, txt[:60]))
    return avisos


def celdas_de_cambios(cabecera, n_fila, cambios):
    """`(celdas, motivos)` para escribir. `celdas` es `[(A1, valor)]`.

    Con motivos, `celdas` viene **vacía**: no se escribe la mitad de un cambio. Una escritura a
    medias deja la fila en un estado que no corresponde a nada, y es peor que no escribir.
    """
    motivos = []
    mapa, duplicadas = indices(cabecera)

    try:
        n_fila = int(n_fila)
    except (TypeError, ValueError):
        n_fila = 0
    if n_fila < 2:
        motivos.append(u"la fila %r no es una fila de datos: la 1 es la cabecera" % (n_fila,))

    celdas = []
    for nombre in sorted(cambios or {}):
        if nombre in duplicadas:
            # ⛔ Aquí está el fondo del asunto: escribir en una de dos columnas homónimas deja las
            #    dos inconsistentes, y así es como llegaron a estarlo. No se elige por nosotros.
            motivos.append(u"la columna %r sale %d veces (%s): hay que decidir cuál se queda "
                           u"antes de escribir en ella"
                           % (nombre, len(duplicadas[nombre]),
                              u", ".join(letra_columna(c) for c in duplicadas[nombre])))
            continue
        if nombre not in mapa:
            motivos.append(u"la columna %r no existe en la cabecera" % nombre)
            continue
        celdas.append((u"%s%d" % (letra_columna(mapa[nombre]), n_fila), cambios[nombre]))

    if motivos:
        return [], motivos
    return celdas, []


if __name__ == "__main__":  # pragma: no cover
    print("Traducción hoja↔registros. Para probarla: python scripts/test_hoja.py")
