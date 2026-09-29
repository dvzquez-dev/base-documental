#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Banco de `verificar.py`. Sin red, sin credenciales, sin reloj.

⛔ Lo que este banco protege de verdad es el **falso acuerdo**: una comparación demasiado floja
diría que todo cuadró justo cuando no, y entonces la relectura no sirve para nada — sería trabajo
y ruido para tapar el mismo agujero que dice cerrar.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding="utf-8")
    except Exception:
        pass

import verificar as V

fallos = []
hechas = [0]


def ok(cond, que):
    hechas[0] += 1
    if not cond:
        fallos.append(que)


# ── 1. Lo que Sheets devuelve con OTRO tipo es el mismo valor ──────────────────────────────
# 📏 Medido el 29/09: las columnas de banderas guardan BOOLEANOS, así que se manda "TRUE" y al
#    releer vuelve `True`. Un `==` estricto daría discrepancia en TODAS las celdas.
for pedido, leido in ((u"TRUE", True), (u"FALSE", False), (True, u"TRUE"), (False, u"FALSE"),
                      (u"TRUE", u"TRUE"), (True, True),
                      (5, u"5"), (u"5", 5), (5, 5.0), (u"5.0", 5), (u"5", u"5.0"),
                      (u"  TRUE  ", True), (u"true", True), (u"True", True),
                      (u"", None), (None, u""), (None, None), (u"", u""),
                      (u"hola", u"hola"), (u"  hola  ", u"hola")):
    ok(V.mismo_valor(pedido, leido),
       u"%r y %r deberían ser el mismo valor" % (pedido, leido))

# ⛔ Y LO QUE NO: aflojar aquí diría que todo fue bien precisamente cuando no.
for pedido, leido in ((u"TRUE", u"FALSE"), (True, False), (u"TRUE", False), (u"TRUE", u""),
                      (u"TRUE", None), (5, 6), (u"5", u"6"), (5, 5.5), (u"5", u""),
                      (u"hola", u"adiós"), (u"hola", u""), (u"", u"algo"),
                      (u"hola", u"HOLA")):
    ok(not V.mismo_valor(pedido, leido),
       u"⛔ %r y %r NO son el mismo valor" % (pedido, leido))

# ⚠️ El vacío y el None son lo mismo a propósito: es lo que devuelve una celda vacía y lo que se
#    manda para vaciarla — distinguirlos inventaría una discrepancia en cada limpieza de
#    `last_error`.
ok(V.mismo_valor(u"", None) and V.mismo_valor(None, u""),
   u"vaciar una celda no debería dar discrepancia")

# ── 2. El contraste ────────────────────────────────────────────────────────────────────────
cuadran, disc = V.contrastar([("AW2", u"TRUE"), ("BX2", u"2026-09-29")],
                             {"AW2": True, "BX2": u"2026-09-29"})
ok(cuadran is True, u"debería cuadrar: %r" % (disc,))
ok(disc == [], u"no debería haber discrepancias: %r" % (disc,))

# ⛔ EL CASO QUE JUSTIFICA EL MÓDULO: se escribió y la celda sigue como estaba.
cuadran, disc = V.contrastar([("AW2", u"TRUE")], {"AW2": u"FALSE"})
ok(cuadran is False, u"¡da por buena una celda que NO se escribió!")
ok(len(disc) == 1, u"debería haber una discrepancia: %r" % (disc,))
ok(disc[0][0] == "AW2", u"la discrepancia no dice la celda")
ok("TRUE" in disc[0][3] and "FALSE" in disc[0][3],
   u"el motivo no dice qué se pidió y qué hay: %r" % (disc[0][3],))

# ⛔ Y el fallo medido en este proyecto: el conector devolvió VACÍO y no escribió.
cuadran, disc = V.contrastar([("AW2", u"TRUE"), ("BX2", u"x")], {})
ok(cuadran is False, u"¡una relectura vacía cuenta como acuerdo!")
ok(len(disc) == 2, u"las dos celdas deberían salir: %r" % (disc,))
ok(all("no consta" in d[3] for d in disc),
   u"el motivo no distingue «no se pudo releer» de «tiene otro valor»: %r" % (disc,))

# Una celda que falta y otra que está: sólo sale la que falta.
cuadran, disc = V.contrastar([("A2", u"x"), ("B2", u"y")], {"A2": u"x"})
ok(len(disc) == 1 and disc[0][0] == "B2", u"debería salir sólo B2: %r" % (disc,))

ok(V.contrastar([], {}) == (True, []), u"sin celdas pedidas debería cuadrar")
ok(V.contrastar(None, None) == (True, []), u"None no debería reventar")
# ⚠️ Que sobren celdas releídas no es un problema: se leyó de más, no se escribió de menos.
ok(V.contrastar([("A2", u"x")], {"A2": u"x", "Z9": u"lo que sea"})[0] is True,
   u"una celda releída de más no debería contar como discrepancia")

# La clave se recorta antes de buscarla.
ok(V.contrastar([("  A2  ", u"x")], {"A2": u"x"})[0] is True, u"no recorta la referencia")

# ── 3. El informe ──────────────────────────────────────────────────────────────────────────
ok(V.informe(True, [], 5) == u"", u"si todo cuadró el informe debería estar vacío")
txt = V.informe(*V.contrastar([("AW2", u"TRUE")], {"AW2": u"FALSE"}), cuantas=1)
ok("1 de 1" in txt, u"el informe no dice cuántas de cuántas: %r" % txt)
ok("AW2" in txt, u"el informe no dice la celda")
# ⛔ Y dice la consecuencia, que es lo accionable: nadie va a volver a mirar ese expediente.
ok("nadie va a volver a mirarlo" in txt,
   u"el informe no explica por qué esto importa: %r" % txt)

txt = V.informe(*V.contrastar([("A2", u"x"), ("B2", u"y")], {}), cuantas=2)
ok("2 de 2" in txt, u"el informe no cuenta bien: %r" % txt)
ok(txt.count("\n") == 2, u"el informe debería llevar una línea por discrepancia: %r" % txt)

print("%d comprobaciones" % hechas[0])
if fallos:
    print("\n%d ROJO(S):" % len(fallos))
    for f_ in fallos:
        print("  - %s" % f_)
    sys.exit(1)
print("verde")
