#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Banco de `sheets_api.py`. Sin red, sin credenciales, sin reloj.

⛔ Los dos nombres de pestaña de los casos son **reales**: `SOLICITUDES` (sin espacios) y
`Base de Datos` (con ellos, la del Libro de Datos). El segundo es el que obliga a entrecomillar.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding="utf-8")
    except Exception:
        pass

import sheets_api as S

fallos = []
hechas = [0]


def ok(cond, que):
    hechas[0] += 1
    if not cond:
        fallos.append(que)


# ── 1. Qué es una celda de datos ───────────────────────────────────────────────────────────
for buena in ("A2", "AW2", "BZ78", "A10", "ZZ1000", "K7"):
    ok(S.es_celda(buena), u"%r debería ser una celda de datos" % buena)

# ⛔⛔ Lo que NO puede pasar, y cada una tiene su desastre propio.
for mala, porque in (
        ("A1", u"es la CABECERA: escribir ahí renombra la columna"),
        ("A", u"Sheets lo lee como A1, o sea la cabecera"),
        ("A:A", u"es la COLUMNA ENTERA"),
        ("A2:B3", u"es un rango, no una celda"),
        ("2", u"no lleva columna"),
        ("", u"vacío"),
        (None, u"None"),
        ("a2", u"en minúscula: A1 usa mayúsculas"),
        ("AAAA2", u"cuatro letras no es una columna de Sheets"),
        ("A0", u"la fila 0 no existe"),
        ("SOLICITUDES!A2", u"ya trae la pestaña dentro")):
    ok(not S.es_celda(mala), u"%r NO debería valer como celda (%s)" % (mala, porque))

# ── 2. El nombre de la pestaña ─────────────────────────────────────────────────────────────
ok(S.nombre_pestana("SOLICITUDES") == "SOLICITUDES",
   u"un nombre simple no necesita comillas: %r" % S.nombre_pestana("SOLICITUDES"))
# ⛔ EL CASO REAL: la pestaña del Libro lleva espacios.
ok(S.nombre_pestana("Base de Datos") == u"'Base de Datos'",
   u"la pestaña con espacios no se entrecomilla: %r" % S.nombre_pestana("Base de Datos"))
ok(S.nombre_pestana("  RUTAS  ") == "RUTAS", u"no recorta el nombre")
# ⚠️ El apóstrofo se duplica: si no, cierra la cadena antes de tiempo y el rango apunta a otro sitio.
ok(S.nombre_pestana("O'Brien") == u"'O''Brien'",
   u"el apóstrofo no se escapa: %r" % S.nombre_pestana("O'Brien"))
ok(S.nombre_pestana("2026-27") == u"'2026-27'", u"un nombre con guiones necesita comillas")
ok(S.nombre_pestana("Hoja 1") == u"'Hoja 1'", u"un nombre con espacio necesita comillas")
# Un nombre que se lee como una referencia también se entrecomilla, o Sheets lo toma por celda.
ok(S.nombre_pestana("A1") == u"'A1'", u"un nombre que parece una celda debería entrecomillarse")
ok(S.nombre_pestana("") is None, u"un nombre vacío no vale")
ok(S.nombre_pestana(None) is None, u"None no vale como pestaña")
ok(S.nombre_pestana("   ") is None, u"sólo espacios no vale")

# ── 3. El rango ────────────────────────────────────────────────────────────────────────────
ok(S.rango("SOLICITUDES", "AW2") == u"SOLICITUDES!AW2", u"el rango simple no cuadra")
ok(S.rango("Base de Datos", "C5") == u"'Base de Datos'!C5", u"el rango con comillas no cuadra")
ok(S.rango("SOLICITUDES", "A1") is None, u"la cabecera no debería dar rango")
ok(S.rango("SOLICITUDES", "A:A") is None, u"una columna entera no debería dar rango")
ok(S.rango("", "A2") is None, u"sin pestaña no hay rango")

# ── 4. El cuerpo ───────────────────────────────────────────────────────────────────────────
cuerpo, motivos = S.cuerpo_batch("SOLICITUDES", [("AW2", "TRUE"), ("BX2", "2026-09-29")])
ok(motivos == [], u"un cuerpo correcto no debería dar motivos: %r" % (motivos,))
ok(cuerpo["valueInputOption"] == "USER_ENTERED",
   u"el modo por defecto debería ser USER_ENTERED: las banderas son BOOLEANOS")
ok(len(cuerpo["data"]) == 2, u"deberían viajar las dos celdas: %r" % (cuerpo["data"],))
ok(cuerpo["data"][0] == {"range": u"SOLICITUDES!AW2", "values": [["TRUE"]]},
   u"la primera entrada no cuadra: %r" % (cuerpo["data"][0],))
ok(cuerpo["data"][0]["values"] == [["TRUE"]],
   u"el valor no va envuelto en la matriz de una fila y una columna")

cuerpo, _m = S.cuerpo_batch("Base de Datos", [("A2", "x")])
ok(cuerpo["data"][0]["range"] == u"'Base de Datos'!A2",
   u"el rango del Libro no lleva comillas: %r" % (cuerpo["data"][0]["range"],))

# ⛔ Si UNA celda es inválida no se manda NINGUNA: media escritura deja la fila en un estado que
#    no corresponde a nada, y la pasada dice que hizo su trabajo.
cuerpo, motivos = S.cuerpo_batch("SOLICITUDES", [("AW2", "TRUE"), ("A:A", "x")])
ok(cuerpo is None, u"¡escribe la mitad cuando una celda es inválida!")
ok(any("no toca" in m for m in motivos), u"el motivo no explica el desastre: %r" % (motivos,))
ok(any("A:A" in m for m in motivos), u"el motivo no dice CUÁL es la celda mala")

cuerpo, motivos = S.cuerpo_batch("SOLICITUDES", [("A1", "x")])
ok(cuerpo is None, u"escribe en la cabecera")

# La misma celda dos veces con valores distintos: gana la última y nadie sabe cuál.
cuerpo, motivos = S.cuerpo_batch("SOLICITUDES", [("AW2", "TRUE"), ("AW2", "FALSE")])
ok(cuerpo is None, u"deja pasar dos valores distintos para la misma celda")
ok(any("dos veces" in m for m in motivos), u"el motivo no lo explica: %r" % (motivos,))
# Pero repetida con el MISMO valor no es un problema: se manda una vez.
# ⚠️ Con la MISMA grafía: `aw2` en minúscula ya lo rechaza `es_celda` — comprobado arriba —,
#    así que usarlo aquí mediría esa regla otra vez y no el deduplicado.
cuerpo, motivos = S.cuerpo_batch("SOLICITUDES", [("AW2", "TRUE"), ("AW2", "TRUE")])
ok(motivos == [], u"la misma celda con el mismo valor no debería quejarse: %r" % (motivos,))
ok(cuerpo and len(cuerpo["data"]) == 1, u"la repetida debería mandarse una sola vez")

# Sin celdas, sin pestaña y con un modo inventado.
ok(S.cuerpo_batch("SOLICITUDES", [])[0] is None, u"sin celdas no debería construirse cuerpo")
ok(S.cuerpo_batch("SOLICITUDES", None)[0] is None, u"unas celdas None no deberían reventar")
ok(S.cuerpo_batch("", [("A2", "x")])[0] is None, u"sin pestaña no debería construirse cuerpo")
cuerpo, motivos = S.cuerpo_batch("SOLICITUDES", [("A2", "x")], modo="INVENTADO")
ok(cuerpo is None and any("no existe" in m for m in motivos),
   u"un valueInputOption inventado debería pararse: %r" % (motivos,))

# El otro modo sí vale, y es el que hará falta si las columnas guardan booleanos de verdad.
cuerpo, motivos = S.cuerpo_batch("SOLICITUDES", [("A2", "x")], modo="USER_ENTERED")
ok(motivos == [] and cuerpo["valueInputOption"] == "USER_ENTERED",
   u"USER_ENTERED debería ser válido: %r" % (motivos,))
ok(S.MODOS == ("RAW", "USER_ENTERED"), u"los modos ya no son los dos de la API")
# ⛔⛔ MEDIDO el 29/09: las columnas de banderas guardan BOOLEANOS, no texto. Se vio por la
#    alineación — `B2` (número) sale `RIGHT` y `A2`/`C2` (texto) salen `LEFT`, o sea que la
#    herramienta informa de la EFECTIVA; y `AW3` (bandera) sale `CENTER` mientras sus vecinas
#    inmediatas `AX3`/`AY3` (texto) salen `LEFT`, o sea que el centrado es POR TIPO y no un
#    formato puesto al bloque. Con `RAW` quedaría un texto "TRUE" entre booleanos y cualquier
#    COUNTIF de la hoja dejaría de contarlo, sin dar ningún error.
ok(S.MODO_POR_DEFECTO == "USER_ENTERED",
   u"el modo por defecto debe guardar BOOLEANOS, que es lo que hay en esas columnas")

# ── 5. Lo que `USER_ENTERED` leería como fórmula ────────────────────────────────────
for peligroso in ("=SUM(A1:A9)", "+A1", "@aqui", "=1+1", "  =A1  ", "-A1", "=BORRA()"):
    ok(S.es_formula(peligroso), u"%r debería leerse como fórmula" % peligroso)
# ⚠️ Lo que PARECE una fórmula y no lo es: cualquier cosa que Sheets entienda como NÚMERO acaba
#    siendo el número que aparenta — `-3` y también `+1`, que entra como el 1. Rechazarlos sería un
#    falso rojo sobre valores normales, y una guarda que griñe por lo correcto se acaba quitando.
for bueno in ("-3", "-3.5", "-0", "+1", "+2.5", 5, -5, -2.5, "TRUE", "", None, "hola", "a=b",
              True, False):
    ok(not S.es_formula(bueno), u"%r NO debería leerse como fórmula" % (bueno,))

cuerpo, motivos = S.cuerpo_batch("SOLICITUDES", [("AW2", "TRUE"), ("BY2", "=BORRA()")])
ok(cuerpo is None, u"¡manda un valor que Sheets guardaría como FÓRMULA!")
ok(any("FÓRMULA" in m for m in motivos), u"el motivo no lo explica: %r" % (motivos,))
ok(any("BY2" in m for m in motivos), u"el motivo no dice en qué celda")

# Con RAW no hay fórmulas que valgan: se guarda tal cual.
cuerpo, motivos = S.cuerpo_batch("SOLICITUDES", [("BY2", "=BORRA()")], modo="RAW")
ok(motivos == [], u"con RAW un texto que empieza por = es sólo texto: %r" % (motivos,))

# Y un error normal, que es el caso que de verdad viaja por ahí, pasa sin problema.
cuerpo, motivos = S.cuerpo_batch(
    "SOLICITUDES", [("BY2", "RuntimeError: la hoja contestó 503")])
ok(motivos == [], u"un mensaje de error normal no debería rechazarse: %r" % (motivos,))

print("%d comprobaciones" % hechas[0])
if fallos:
    print("\n%d ROJO(S):" % len(fallos))
    for f_ in fallos:
        print("  - %s" % f_)
    sys.exit(1)
print("verde")
