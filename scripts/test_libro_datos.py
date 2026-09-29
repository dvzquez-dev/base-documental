#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Banco de `libro_datos.py`. Sin red, sin credenciales, sin reloj.

⛔ Los casos NO son inventados: son **filas reales** leídas del Libro de Datos el 29/09/2026
(hoja `1QoEY_…`, pestaña «Base de Datos», worksheetId 1462760680). Un fixture inventado prueba
que el código hace lo que pensaste; uno medido prueba que sirve para lo que hay.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding="utf-8")
    except Exception:
        pass

import libro_datos as LD

fallos = []
hechas = [0]


def ok(cond, que):
    hechas[0] += 1
    if not cond:
        fallos.append(que)


def hay(avisos, fila, trozo):
    return any(n == fila and trozo in q for n, _t, q in avisos)


# ── 1. Partir una referencia ───────────────────────────────────────────────────────────────
ok(LD.parte_referencia("Informe_S-4012_27") == ("Informe", "S", "4012", "27"),
   "no parte una referencia actual")
ok(LD.parte_referencia("Informe_A-2001_25") == ("Informe", "A", "2001", "25"),
   "no parte una referencia heredada A-")
ok(LD.parte_referencia("Carpeta_I-1006_25") == ("Carpeta", "I", "1006", "25"),
   "no parte una referencia heredada I-")
ok(LD.parte_referencia("Simulación_S-1001_27") == ("Simulación", "S", "1001", "27"),
   "el tipo con tilde rompe el parseo")
# ⛔ Devuelve la letra TAL CUAL: si normalizara, se perdería la prueba del defecto.
ok(LD.parte_referencia("Informe_i-3004_25")[1] == "i",
   "la minúscula se corrige calladamente: así no se puede denunciar el defecto")
ok(LD.parte_referencia("Carpeta_I-1007-25") is None, "el guion antes del año debería fallar")
ok(LD.parte_referencia("Informe_1005_25") is None, "sin letra no es referencia")
ok(LD.parte_referencia("Informe_X-1005_25") is None, "una letra que no existe no vale")
ok(LD.parte_referencia("") is None, "la cadena vacía no es referencia")
ok(LD.parte_referencia(None) is None, "None no es referencia")

ok(LD.es_canonica("Informe_S-4012_27") is True, "una actual debería ser canónica")
ok(LD.es_canonica("Informe_A-2001_25") is True, "una heredada bien escrita también es canónica")
ok(LD.es_canonica("Informe_i-3004_25") is False, "la minúscula no es canónica")
ok(LD.es_heredada("Informe_A-2001_25") is True, "A- es heredada")
ok(LD.es_heredada("Informe_S-4012_27") is False, "S- no es heredada")

# ⛔ La lista de letras se comprueba contra lo medido, no iterando la constante.
ok(LD.LETRAS == "SAI", "LETRAS ya no es lo medido en el libro")
ok(LD.LETRA_ACTUAL == "S", "la letra actual del pipeline es S")
ok(LD.COLUMNAS == ("Título del Archivo", "Ubicación del Archivo", "Palabras Clave"),
   "las columnas no son las medidas de la hoja")

# ── 2. Palabras clave ──────────────────────────────────────────────────────────────────────
# 📏 Celda real: "Analisis, Cuadricoptero, I+D,Prueba Modelos, Codigo FPS, " (coma colgando)
ok(LD.claves("Analisis, Cuadricoptero, I+D,Prueba Modelos, Codigo FPS, ") ==
   ["Analisis", "Cuadricoptero", "I+D", "Prueba Modelos", "Codigo FPS"],
   "no limpia la celda real con coma colgando y sin espacio tras una coma")
ok(LD.claves("Informe, informe, INFORME") == ["Informe"],
   "no quita la clave repetida en otra caja")
# ⚠️ Y la que queda conserva cómo la escribió su autor.
ok(LD.claves("informe, Informe")[0] == "informe",
   "al deduplicar se reescribe la clave del autor en vez de quedarse con la primera")
ok(LD.claves("") == [], "una celda vacía no da claves")
ok(LD.claves(None) == [], "None no da claves")
ok(LD.claves(" , , ") == [], "sólo comas no da claves")
ok(LD.claves("Áine, aine") == ["Áine"], "la tilde no debería crear una clave distinta")

# ── 3. La fila que se escribe ──────────────────────────────────────────────────────────────
f, m = LD.fila({"reference": "Informe_S-4012_27", "drive_filename": "Informe_S-4012_27.pdf",
                "keywords": "informe, propulsión, ensayo"})
ok(m == [], "un expediente completo no debería dar motivos: %r" % (m,))
ok(f == ["Informe_S-4012_27", "Informe_S-4012_27.pdf", "informe, propulsión, ensayo"],
   "la fila no es la esperada: %r" % (f,))
ok(len(f) == 3, "la fila tiene que tener exactamente tres celdas")

f2, _ = LD.fila({"reference": "Informe_S-4012_27", "keywords": "informe"})
ok(f2[1] == "Informe_S-4012_27",
   "sin nombre en Drive la ubicación debería caer a la referencia, como las 1.000 filas viejas")

for campo, valor, trozo in (("reference", "chusta", "no es canónica"),
                            ("keywords", "", "sin palabras clave")):
    d = {"reference": "Informe_S-4012_27", "drive_filename": "x.pdf", "keywords": "informe"}
    d[campo] = valor
    p, mm = LD.fila(d)
    ok(p is None, "con %s malo no debería devolver fila" % campo)
    ok(len(mm) == 1, "con %s malo debería haber UN motivo, hay %d: %r" % (campo, len(mm), mm))
    ok(mm and trozo in mm[0], "el motivo de %s no explica la causa: %r" % (campo, mm))

# ── 4. El revisor, contra las filas REALES medidas ─────────────────────────────────────────
# 📏 Copiadas literalmente de la hoja. Las cinco primeras son buenas; las demás traen cada una
#    uno de los defectos que se encontraron.
REALES = [
    ["Informe_A-2002_25", "Informe_A-2002_25.pdf", "Informe, Áine, materiales, geometría"],   # 2 ok
    ["Informe_A-3001_25", "Informe_A-3001_25.pdf", "Informe, electronica, componentes"],      # 3 ok
    ["Informe_I-1000_25", "Informe_I-1000_25.pdf", "Informe, I+D, Cuadricóptero"],            # 4 ok
    ["Informe_I-1008_25", "Informe_l-1005_25.pdf", "Infomre,I+D, cuadricoptero"],             # 5 ✗
    ["Informe_I-2002_25", "Informe_I-3002_25.pdf", "Informe, I+D, Fabricación, Moldes"],      # 6 ✗
    ["Informe_i-3004_25", "Informe_I-3004_25.pdf", "Informe, I+D, listado, materiales"],      # 7 ✗
    ["Informe_I-3005_25", "Mixers"],                                                          # 8 ✗
    ["Informe_I-3002_25", "Informe_I-3002_25.pdf", "Informe, I+D, moldes, composite"],        # 9 ok
    ["Informe_l-1003_25", "Informe_l-1003_25.pdf", "Informe, I+D, Cuadricóptero, Hardware"],  # 10 ✗
    ["Carpeta_I-1007-25.pdf", "Distance_Iteration", "Workspace, cuadricóptero"],              # 11 ✗
    # 📏 El libro real trae `Informe_l-1004_25` DOS veces, y `Informe_l-1005_25` otras dos,
    #    y `Informe_S-4001_25` dos veces en bloques distintos. El duplicado es el defecto que más
    #    veces aparece, y hasta medir la columna entera el banco no tenía ningún caso que lo
    #    disparara: la comprobación estaba escrita y **no podía ponerse roja**.
    ["Informe_l-1004_25", "Informe_l-1004_25.pdf", "Informe, I+D"],                            # 12 ✗
    ["Informe_l-1004_25", "Informe_l-1004_25.pdf", "Informe, I+D"],                            # 13 ✗
    ["Infrorme_S-6011_25", "Infrorme_S-6011_25.pdf", "informe, general"],                      # 14 ✗
    ["Informe_S_6005_25", "Informe_S_6005_25.pdf", "informe, general"],                        # 15 ✗
    ["Normativa de Áine v.1.0.0", "Normativa de Áine v.1.0.0.pdf", "normativa, áine"],         # 16 ✗
    # ⛔ EL PAR QUE SE DIFERENCIA SÓLO EN LA ELE. La fila 17 está en el libro tal cual (dos
    #    veces); la 18 es cómo se escribe bien. Es lo que pasa **el día que alguien arregla una de
    #    las dos**: quedan las dos, se leen igual, y sin aplastar homóglifos nadie lo ve.
    #    Sin este par, `_confundible` podía dejar de aplastar la ele y el banco seguía verde:
    #    los demás duplicados son cadenas idénticas y no necesitan aplastar nada.
    ["Informe_l-1005_25", "Informe_l-1005_25.pdf", "Informe, I+D, mejoras"],                   # 17 ✗
    ["Informe_I-1005_25", "Informe_I-1005_25.pdf", "Informe, I+D, mejoras"],                   # 18 ✗
]
av = LD.revisar(REALES)

# ⛔ Cada defecto se comprueba EN SU FILA y por SU motivo: que salgan avisos no basta, porque
#    el aviso podría venir del vecino. Esta noche ya pasó una vez.
ok(hay(av, 5, "la ubicación"), "no ve que I-1008 apunta a l-1005 (homóglifo + otro número)")
ok(hay(av, 6, "es la de otra referencia"),
   "no ve que I-2002 apunta al fichero de I-3002, que existe en otra fila")
ok(hay(av, 7, "minúscula"), "no ve la i minúscula de i-3004")
ok(hay(av, 8, "sin palabras clave"), "no ve la fila de dos celdas sin claves")
ok(hay(av, 10, "no es una I"), "no ve la ele minúscula de l-1003, que se lee igual que I-1003")
ok(hay(av, 11, "no es una referencia"), "no ve el guion y el .pdf metidos en el título")

# Y las buenas NO dan aviso: un revisor que marque en rojo lo correcto no lo usa nadie.
for buena in (2, 3, 4, 9):
    ok(not any(n == buena for n, _t, _q in av),
       "marca en rojo la fila %d, que está bien" % buena)

# ⚠️ Las heredadas A-/I- son 30 de estas 45 filas: si el revisor las rechazara por no ser `S-`,
#    marcaría en rojo medio libro y nadie volvería a mirarlo.
ok(not any("letra" in q and "S" == q[:1] for _n, _t, q in av),
   "rechaza las referencias heredadas por no llevar S-")

# ⛔ El duplicado EXACTO: dos filas con el mismo título. Es el defecto más frecuente del libro
#    real y la comprobación que llevaba escrita sin un solo caso que la disparase.
ok(hay(av, 12, "se lee igual que otra"), "no ve el título repetido en las filas 12 y 13")
dobles = [q for _n, _t, q in av if "se lee igual que otra" in q]
# Dos grupos de duplicados en el fixture (12/13 idénticos, 17/18 por homóglifo): UN aviso por
# grupo, no uno por fila — si no, un libro con veinte repetidas escupe cuarenta líneas.
ok(len(dobles) == 2, "los duplicados salen %d veces, deberían ser 2 grupos: %r" % (len(dobles), dobles))
ok(any("fila 12" in q and "fila 13" in q for q in dobles),
   "el aviso del duplicado idéntico no dice las DOS filas: %r" % dobles)
# Y las dos ubicaciones iguales también se denuncian, que es otro defecto distinto.
ok(any("apuntan al mismo archivo" in q for _n, _t, q in av),
   "no ve que dos filas apuntan al mismo archivo")

# ⛔ El par 17/18 se lee igual y se escribe distinto: ni el título ni la ubicación coinciden
#    carácter a carácter, así que sólo lo caza aplastar `l` contra `I`.
ok(hay(av, 17, "se lee igual que otra"),
   "no ve que Informe_l-1005_25 e Informe_I-1005_25 son la misma referencia mal escrita")
# ⚠️ El aviso ancla en la fila 5, no en la 17: `Informe_I-1008_25` apunta TAMBIÉN a
#    `Informe_l-1005_25.pdf`, así que son TRES filas al mismo archivo. Se comprueba por el
#    contenido del aviso, no por dónde ancla — atarlo a la fila 17 lo haría frágil y además
#    estaría escondiendo que el grupo es más grande de lo que se esperaba.
mismos = [q for _n, _t, q in av if "apuntan al mismo archivo" in q]
ok(any("fila 17" in q and "fila 18" in q for q in mismos),
   "no ve que las ubicaciones del par 17/18 se leen igual: %r" % mismos)
ok(any("fila 5" in q and "fila 17" in q for q in mismos),
   "no ve que I-1008 apunta al mismo archivo que el par 17/18: %r" % mismos)

# ⛔ El tipo mal escrito: `Infrorme` está en el libro real. Parsea perfectamente como referencia,
#    así que sin la lista de tipos medida este defecto es invisible.
ok(hay(av, 14, "el tipo"), "no ve el tipo mal escrito de Infrorme_S-6011_25")
ok(not any(n == 14 and "no es una referencia" in q for n, _t, q in av),
   "trata Infrorme_S-6011_25 como si no fuese referencia: lo es, con el tipo mal escrito")

# El guión bajo en vez de guión, y un título que no es referencia en absoluto.
ok(hay(av, 15, "no es una referencia"), "no ve el guión bajo de Informe_S_6005_25")
ok(hay(av, 16, "no es una referencia"), "no ve que la Normativa no lleva referencia")
ok(LD.TIPOS_LIBRO == ("Acta", "Carpeta", "Codigo", "Excel", "Informe", "Manual", "Memoria",
                      "Pieza", "Simulacion", "Simulación", "Tabla"),
   "TIPOS_LIBRO ya no es la lista medida sobre los 196 títulos")

# Un libro limpio no da ni un aviso.
ok(LD.revisar([["Informe_S-4012_27", "Informe_S-4012_27.pdf", "informe"],
               ["Acta_S-6301_27", "Acta_S-6301_27.pdf", "acta"]]) == [],
   "marca defectos en un libro limpio")
ok(LD.revisar([]) == [], "un libro vacío no debería dar avisos")

# Una fila sin título se reporta y no arrastra al resto.
av2 = LD.revisar([["", "", ""], ["Informe_S-4012_27", "Informe_S-4012_27.pdf", "informe"]])
ok(hay(av2, 2, "sin título"), "no reporta la fila sin título")
ok(not any(n == 3 for n, _t, _q in av2), "la fila sin título contamina a la siguiente")

# Los avisos vienen ordenados por fila: quien los lee va a la hoja de arriba abajo.
ok([n for n, _t, _q in av] == sorted(n for n, _t, _q in av),
   "los avisos no salen ordenados por número de fila")

print("%d comprobaciones" % hechas[0])
if fallos:
    print("\n%d ROJO(S):" % len(fallos))
    for f_ in fallos:
        print("  - %s" % f_)
    sys.exit(1)
print("verde")
