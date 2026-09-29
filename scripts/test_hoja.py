#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Banco de `hoja.py`. Sin red, sin credenciales, sin reloj.

⛔ La cabecera de los casos es la **real** de `SOLICITUDES` en lo que importa: `unit_label` en la
columna 11 y otra vez en la 78, medido el 29/09/2026.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding="utf-8")
    except Exception:
        pass

import hoja as H

fallos = []
hechas = [0]


def ok(cond, que):
    hechas[0] += 1
    if not cond:
        fallos.append(que)


# ── 1. La letra de columna: base-26 BIYECTIVA ──────────────────────────────────────────────
# ⛔ Los bordes son donde falla: 26/27 y 52/53. Con el módulo de toda la vida, la 26 sale "A@".
for n, esperada in ((1, "A"), (2, "B"), (25, "Y"), (26, "Z"), (27, "AA"), (28, "AB"),
                    (51, "AY"), (52, "AZ"), (53, "BA"), (54, "BB"), (78, "BZ"),
                    (79, "CA"), (702, "ZZ"), (703, "AAA")):
    ok(H.letra_columna(n) == esperada,
       "la columna %d debería ser %s y da %r" % (n, esperada, H.letra_columna(n)))

# Las columnas medidas de verdad en SOLICITUDES.
ok(H.letra_columna(11) == "K", "unit_label (11) debería ser K")
ok(H.letra_columna(31) == "AE", "received (31) debería ser AE")
ok(H.letra_columna(49) == "AW", "closed (49) debería ser AW")

# ⚠️ No hay columna 0 ni negativa: devolver "" o "A" ahí escribiría en la celda equivocada.
ok(H.letra_columna(0) is None, "la columna 0 no existe")
ok(H.letra_columna(-3) is None, "una columna negativa no existe")
ok(H.letra_columna(None) is None, "None no es una columna")
ok(H.letra_columna("chusta") is None, "un texto no es una columna")
ok(H.letra_columna("11") == "K", "una columna en texto debería valer")
ok(H.letra_columna(1.0) == "A", "un entero en coma flotante debería valer")

# ── 2. La cabecera real, con la columna duplicada ──────────────────────────────────────────
# 📏 La forma medida: unit_label en la 11 y en la 78, author_name_raw en la 5 y author_name en la 77.
CAB = (["request_id", "form_row", "received_at", "form_email", "author_name_raw",
        "author_notion_user_id", "author_email", "title_short", "document_type", "unit_key",
        "unit_label"] + ["c%d" % i for i in range(12, 77)] + ["author_name", "unit_label"])
ok(len(CAB) == 78, "la cabecera de prueba no tiene 78 columnas: %d" % len(CAB))

mapa, dup = H.indices(CAB)
ok(mapa["request_id"] == 1, "request_id no es la columna 1")
ok(mapa["unit_key"] == 10, "unit_key no es la columna 10")
# ⛔ Se queda con la PRIMERA, y lo dice.
ok(mapa["unit_label"] == 11, "el mapa no se queda con la primera unit_label: %r" % mapa.get("unit_label"))
ok("unit_label" in dup, "no detecta que unit_label está duplicada")
ok(dup["unit_label"] == [11, 78], "no dice las DOS columnas de unit_label: %r" % dup.get("unit_label"))
ok(len(dup) == 1, "detecta duplicadas de más: %r" % sorted(dup))
ok("author_name" not in dup, "author_name y author_name_raw no son la misma columna")

# Sin duplicadas, el diccionario de duplicadas viene vacío (no None).
m2, d2 = H.indices(["a", "b", "c"])
ok(d2 == {}, "sin duplicadas debería venir un dict vacío: %r" % (d2,))
ok(m2 == {"a": 1, "b": 2, "c": 3}, "el mapa simple no cuadra: %r" % (m2,))

# Celdas vacías o con espacios en la cabecera no crean columnas fantasma.
m3, _ = H.indices(["a", "", "  ", None, "b"])
ok(m3 == {"a": 1, "b": 5}, "las celdas vacías de la cabecera crean columnas: %r" % (m3,))
ok(H.indices([])[0] == {}, "una cabecera vacía debería dar un mapa vacío")
ok(H.indices(None)[0] == {}, "una cabecera None no debería reventar")
# El nombre se recorta, como lo recorta todo lo demás.
ok(H.indices(["  request_id  "])[0] == {"request_id": 1}, "no recorta el nombre de la columna")

# ── 3. De fila a registro ──────────────────────────────────────────────────────────────────
r = H.a_registro(["a", "b", "c"], ["1", "2", "3"])
ok(r == {"a": "1", "b": "2", "c": "3"}, "el registro simple no cuadra: %r" % (r,))

# ⛔ La hoja ACORTA la fila cuando las últimas celdas están vacías. Es el caso real: la fila de
#    `Informe_I-3005_25` del Libro venía con dos celdas de tres.
r = H.a_registro(["a", "b", "c"], ["1"])
ok(r == {"a": "1", "b": "", "c": ""},
   "una fila corta no se rellena con vacíos: %r" % (r,))
ok(r["c"] == "", "la celda que falta debería ser cadena vacía, no None")
ok(H.a_registro(["a", "b"], []) == {"a": "", "b": ""}, "una fila vacía debería dar todo vacío")
ok(H.a_registro(["a"], None) == {"a": ""}, "una fila None no debería reventar")
ok(H.a_registro(["a"], ["1", "2", "3"]) == {"a": "1"}, "sobra columna y se cuela en el registro")
ok(H.a_registro(["a", "b"], ["1", None]) == {"a": "1", "b": ""},
   "un None de la hoja debería quedar como cadena vacía")
# Con la cabecera duplicada, el registro lleva el valor de la PRIMERA.
r = H.a_registro(["unit_label", "x", "unit_label"], ["primera", "y", "segunda"])
ok(r["unit_label"] == "primera", "el registro no toma la primera columna homónima: %r" % r)

# ── 4. La hoja entera ──────────────────────────────────────────────────────────────────────
regs, dup2 = H.a_registros([["a", "b"], ["1", "2"], ["3"]])
ok(len(regs) == 2, "debería dar 2 registros: %d" % len(regs))
ok(regs[1] == {"a": "3", "b": ""}, "el segundo registro no cuadra: %r" % (regs[1],))
ok(dup2 == {}, "no debería detectar duplicadas aquí")
# ⚠️ Sólo cabecera, o nada: es el estado normal de una hoja recién creada, no un error.
ok(H.a_registros([["a", "b"]]) == ([], {}), "sólo cabecera debería dar cero registros")
ok(H.a_registros([]) == ([], {}), "una hoja vacía debería dar cero registros")
ok(H.a_registros(None) == ([], {}), "una hoja None no debería reventar")
_regs, dup3 = H.a_registros([CAB, ["x"] * 78])
ok("unit_label" in dup3, "a_registros no propaga la columna duplicada")

# ── 5. Los cambios, a celdas ───────────────────────────────────────────────────────────────
celdas, motivos = H.celdas_de_cambios(["a", "b", "c"], 5, {"b": "TRUE"})
ok(motivos == [], "un cambio normal no debería dar motivos: %r" % (motivos,))
ok(celdas == [("B5", "TRUE")], "la celda no es la esperada: %r" % (celdas,))

celdas, _ = H.celdas_de_cambios(CAB, 7, {"request_id": "R-9", "unit_key": "uct"})
ok(celdas == [("A7", "R-9"), ("J7", "uct")],
   "las celdas de dos cambios no salen ordenadas por nombre: %r" % (celdas,))

# ⛔ EL CASO DEL MÓDULO: escribir en una columna duplicada se NIEGA.
celdas, motivos = H.celdas_de_cambios(CAB, 7, {"unit_label": "Unidad de Recovery"})
ok(celdas == [], "¡escribe en una columna duplicada! %r" % (celdas,))
ok(len(motivos) == 1, "debería haber un motivo: %r" % (motivos,))
ok(motivos and "2 veces" in motivos[0], "el motivo no dice cuántas veces sale: %r" % (motivos,))
ok(motivos and "K" in motivos[0] and "BZ" in motivos[0],
   "el motivo no dice QUÉ columnas son, que es lo accionable: %r" % (motivos,))

# ⛔ Y no escribe la mitad: si uno de los cambios es malo, no se escribe ninguno.
celdas, motivos = H.celdas_de_cambios(CAB, 7, {"request_id": "R-9", "unit_label": "x"})
ok(celdas == [], "escribe la mitad de un cambio cuando el otro es inválido: %r" % (celdas,))
ok(len(motivos) == 1, "debería seguir habiendo un solo motivo: %r" % (motivos,))

celdas, motivos = H.celdas_de_cambios(["a"], 5, {"no_existe": "x"})
ok(celdas == [] and motivos, "una columna que no existe debería dar motivo")
ok(motivos and "no existe" in motivos[0], "el motivo no explica que la columna no está")

# ⚠️ La fila 1 es la cabecera: escribir ahí renombra columnas.
for mala in (1, 0, -2, None, "x"):
    celdas, motivos = H.celdas_de_cambios(["a"], mala, {"a": "x"})
    ok(celdas == [], "¡escribe en la fila %r! %r" % (mala, celdas))
    ok(any("cabecera" in m for m in motivos),
       "el motivo de la fila %r no dice que la 1 es la cabecera: %r" % (mala, motivos))

ok(H.celdas_de_cambios(["a"], 5, {}) == ([], []), "sin cambios no hay celdas ni motivos")
ok(H.celdas_de_cambios(["a"], 5, None) == ([], []), "unos cambios None no deberían reventar")

# ── FILAS DESPLAZADAS: la cabecera dice una cosa y la celda es de otra ────
# ⛔⛔ Medido en `SOLICITUDES` el 29/09/2026: **4 de las 17 filas** —las cuatro ingeridas el
#    09/07— llevan su cola **dos columnas a la izquierda**. El síntoma real: el tipo MIME
#    (`application/vnd.…wordprocessingml.document`) aparece en `annex_copied_count`, que es un
#    CONTADOR, y el texto libre de `context` aparece en `range_end`.
# ⚠️ Hoy no hace daño **porque nadie lee esas columnas todavía**. El día que se implementen los
#    anexos, `annex_copied_count` valdrá una cadena de 71 caracteres y no habrá ningún error:
#    simplemente se copiarán cero anexos. Por eso se caza por el TIPO, no esperando a que reviente.
_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_CAB = ["request_id", "range_start", "range_end", "annex_copied_count", "source_size_bytes"]
_BUENA = ["SOL-1", "6301", "6499", "0", "415079"]
# ⛔ Copiada de la fila 10 real (`SOL-DOC-20260709-141523-1A7F4NFG`): el texto de `context` cae
#    en `range_end` y el tipo MIME en `annex_copied_count`. Dos síntomas, no tres: los demás
#    huecos quedan **vacíos**, y el vacío no canta.
_DESPL = ["SOL-2", "", "Es un informe bimensual, corres", _MIME, ""]

_avisos = H.desplazadas(H.a_registros([_CAB, _BUENA])[0])
ok(_avisos == [], u"una fila sana no debería dar avisos: %r" % (_avisos,))

_avisos = H.desplazadas(H.a_registros([_CAB, _BUENA, _DESPL])[0])
ok(len(_avisos) == 2, u"la fila desplazada tiene DOS celdas que no son números: %r" % (_avisos,))
ok(all(a_[0] == 3 for a_ in _avisos),
   u"el número de fila no es el de la hoja (cabecera + 1): %r" % (_avisos,))
ok(all(a_[1] == "SOL-2" for a_ in _avisos), u"el aviso no dice de qué expediente es")
_cols = sorted(a_[2] for a_ in _avisos)
ok(_cols == ["annex_copied_count", "range_end"],
   u"no señala las columnas que de verdad están mal: %r" % (_cols,))
ok(any(_MIME[:30] in a_[3] for a_ in _avisos),
   u"el aviso no enseña el valor, que es lo que deja ver el desplazamiento: %r" % (_avisos,))

# ⚠️ Vacío NO es síntoma: la mayoría de las filas sanas tienen estas columnas en blanco, y
#    cantar por eso enseñaría a ignorar el aviso (que es lo que lo mata).
ok(H.desplazadas(H.a_registros([_CAB, ["SOL-3", "", "", "", ""]])[0]) == [],
   u"⛔ canta por columnas VACÍAS: 13 de 17 filas reales las tienen así")
ok(H.desplazadas(H.a_registros([_CAB, ["SOL-4", "  ", None, "", ""]])[0]) == [],
   u"un blanco o un None tampoco son síntoma")
# Un entero de verdad vale venga como texto o como número: Sheets devuelve las dos formas.
ok(H.desplazadas([{"request_id": "x", "annex_copied_count": 7}]) == [],
   u"un entero de verdad no debería cantar")
ok(H.desplazadas([{"request_id": "x", "annex_copied_count": "7"}]) == [],
   u"un entero en texto tampoco")
# ⚠️ Y un decimal SÍ canta: `annex_copied_count` es un contador, no una medida.
ok(len(H.desplazadas([{"request_id": "x", "annex_copied_count": "7.5"}])) == 1,
   u"un 7.5 en un contador debería cantar")
# Las columnas que no son numéricas se dejan en paz, aunque lleven cualquier cosa.
ok(H.desplazadas([{"request_id": "x", "context": _MIME, "title_short": "42"}]) == [],
   u"no debería opinar sobre columnas que no son numéricas")
ok(H.desplazadas([]) == [] and H.desplazadas(None) == [], u"entradas vacías no revientan")
# ⚠️ Y un elemento que no es un registro se salta, no revienta: una lectura a medias de la
#    hoja mete cadenas sueltas, y reventar ahí dejaría el repaso entero sin contestar.
ok(H.desplazadas(["chusta", None, {"request_id": "x", "range_end": "no soy un numero"}]) ==
   [(4, "x", "range_end", "no soy un numero")],
   u"no se salta lo que no es un registro: %r"
   % (H.desplazadas(["chusta", None, {"request_id": "x", "range_end": "no"}]),))
# ⛔ Y la lista de columnas numéricas es la medida, no una corazonada.
ok("annex_copied_count" in H.COLUMNAS_ENTERAS and "range_end" in H.COLUMNAS_ENTERAS,
   u"faltan las columnas donde se vio el desplazamiento real")
ok("closed" not in H.COLUMNAS_ENTERAS,
   u"una bandera no es un número: meterla aquí pondría roja media hoja")

print("%d comprobaciones" % hechas[0])
if fallos:
    print("\n%d ROJO(S):" % len(fallos))
    for f_ in fallos:
        print("  - %s" % f_)
    sys.exit(1)
print("verde")
