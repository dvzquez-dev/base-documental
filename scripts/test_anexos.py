#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Banco de `anexos.py`. Sin red, sin credenciales, sin reloj.

⛔ Los casos llevan **los ids reales** de la fila 18 de `SOLICITUDES`
(`SOL-DOC-20260720-113951-79E115DB`, la *Memoria Técnica Aviónica EuRoC*), que es la única del
pipeline que tiene anexos: **siete de origen y siete copiados**, y los de origen vienen
**separados por comas** en una columna que se llama `_json`.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding="utf-8")
    except Exception:
        pass

import anexos as AX

fallos = []
hechas = [0]


def ok(cond, que):
    hechas[0] += 1
    if not cond:
        fallos.append(que)


# 📏 Copiados de SOLICITUDES el 29/09/2026 (CJ18 y CM18), tal cual: comas y espacios.
ORIGEN_REAL = ("1plp-LdBTRIEgShXXGCTyctKUHUiNz4Ue, 1_fHkYU7FeoZHL08Z-Il8rgGu76Xo6fWc, "
               "1wNl26bp6GHpzFoAlYNutef2LLtqls29b, 1tlt_iqwec_HQG0CvAfXe5ZF02y5zp-1N, "
               "1AzLjmKqHqbZs-Wt9fXehUY3z9JH5Zg2M, 1rUjC0dsAQH1FJi3WcrwlPQMak3ZjDMUR, "
               "1By3PxQbpXNvCu7EzP03jbVwBydWVHrt3")
FINALES_REAL = ("1TC0Mmy_vSNZXTNJ1nPEyKVwjZzlF73lM, 1JSJGyn-EbKh28rESG0UohOqdg4FQv4ho, "
                "1sm5WnHkYGyV-J98E4gZkmcx1cAFHLbwP, 1DtzS9zUsTJXY009Vwn70L26AfVbLaOec, "
                "1BdUFIOhmdsH63w_Yjost3yhc8iOvwJuc, 1Agi0ACtQvjJ6pAUqnWL8yIjdFsDmVEdG, "
                "1lzzSLqp64XWCq1WN8gcMrGmUQECTZeeJ")
FILA_18 = {"request_id": "SOL-DOC-20260720-113951-79E115DB",
           AX.COL_ORIGEN: ORIGEN_REAL, AX.COL_FINALES: FINALES_REAL, AX.COL_CUANTOS: "7"}
# Las otras filas reales: la columna trae `[]`, que SÍ es JSON.
SIN_ANEXOS = {"request_id": "SOL-1", AX.COL_ORIGEN: "[]", AX.COL_FINALES: "[]",
              AX.COL_CUANTOS: "0"}

# ── 1. Leer las dos formas ─────────────────────────────────────────────────────────────────
ids, motivos = AX.origen(FILA_18)
ok(len(ids) == 7, u"⛔ no lee los 7 anexos reales: %r" % (len(ids),))
ok(ids[0] == "1plp-LdBTRIEgShXXGCTyctKUHUiNz4Ue", u"no recorta los espacios: %r" % (ids[:1],))
ok(ids[-1] == "1By3PxQbpXNvCu7EzP03jbVwBydWVHrt3", u"pierde el último: %r" % (ids[-1:],))
ok(motivos and "comas" in motivos[0],
   u"no deja constancia de que la columna `_json` no traía JSON: %r" % (motivos,))

ok(AX.finales(FILA_18)[0][0] == "1TC0Mmy_vSNZXTNJ1nPEyKVwjZzlF73lM",
   u"no lee los ids ya copiados")
ok(len(AX.finales(FILA_18)[0]) == 7, u"no lee los 7 copiados")
# ⛔ Los ids de origen y los finales son DISTINTOS: una copia tiene su propio id. Si esta
#    comprobación se cae, es que alguien los está emparejando por id, que es imposible.
ok(not (set(AX.origen(FILA_18)[0]) & set(AX.finales(FILA_18)[0])),
   u"⛔ algún id de origen aparece entre los copiados: una copia tiene su propio id")

ok(AX.origen(SIN_ANEXOS) == ([], []), u"`[]` debería dar lista vacía sin motivos")
ok(AX.origen({}) == ([], []) and AX.origen(None) == ([], []), u"una fila vacía no revienta")
ok(AX.finales({}) == ([], []), u"sin la columna de copiados, lista vacía")

# Ni vacíos ni repetidos: un id repetido copiaría el mismo fichero dos veces.
ok(AX.origen({AX.COL_ORIGEN: "a, , b,  a "})[0] == ["a", "b"],
   u"no quita vacíos ni repetidos: %r" % (AX.origen({AX.COL_ORIGEN: "a, , b,  a "})[0],))

# ── 2. Cuántos faltan ──────────────────────────────────────────────────────────────────────
ok(AX.faltan(FILA_18) == 0, u"la fila real está completa: no debería faltar ninguno")
ok(AX.faltan(SIN_ANEXOS) == 0, u"sin anexos no falta ninguno")
ok(AX.faltan({AX.COL_ORIGEN: "a, b, c"}) == 3, u"sin copiar ninguno, faltan los tres")
ok(AX.faltan({AX.COL_ORIGEN: "a, b, c", AX.COL_FINALES: '["x"]'}) == 2, u"copiado uno, faltan dos")
# ⚠️ Nunca negativo: con más copiados que de origen, `faltan` es 0 y lo canta `revisar`.
ok(AX.faltan({AX.COL_ORIGEN: "a", AX.COL_FINALES: '["x","y"]'}) == 0,
   u"⛔ `faltan` devuelve un número negativo: nadie lo va a mirar esperando eso")
ok(isinstance(AX.faltan({}), int), u"`faltan` debería devolver siempre un número")

# ── 3. Lo que no cuadra ────────────────────────────────────────────────────────────────────
ok(AX.revisar(FILA_18) == [], u"la fila real está en regla: %r" % (AX.revisar(FILA_18),))
ok(AX.revisar(SIN_ANEXOS) == [], u"una fila sin anexos está en regla")
ok(AX.revisar({}) == [] and AX.revisar("chusta") == [], u"entradas raras no revientan")

_m = AX.revisar({AX.COL_ORIGEN: "a", AX.COL_FINALES: '["x","y"]', AX.COL_CUANTOS: "2"})
ok(any("sobra" in x for x in _m), u"⛔ no canta una copia de más: %r" % (_m,))
ok(any("duplicado" in x for x in _m), u"el motivo no dice la consecuencia: %r" % (_m,))

# ⛔ El contador y la lista tienen que decir lo mismo.
_m = AX.revisar({AX.COL_ORIGEN: "a, b", AX.COL_FINALES: '["x","y"]', AX.COL_CUANTOS: "1"})
ok(any("miente" in x for x in _m), u"⛔ el contador dice 1 y hay 2 ids, y no se canta: %r" % (_m,))
_m = AX.revisar({AX.COL_FINALES: '["x"]'})
ok(any("vacío" in x for x in _m), u"un contador vacío con copias debería cantarse: %r" % (_m,))
ok(AX.revisar({AX.COL_ORIGEN: "a", AX.COL_CUANTOS: ""}) == [],
   u"⚠️ sin copias, un contador vacío es normal y no debe cantar")

# ⛔ Y el contador con un tipo MIME dentro: es la fila desplazada, medida en 4 filas reales.
_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_m = AX.revisar({AX.COL_CUANTOS: _MIME})
ok(any("desplazada" in x for x in _m),
   u"⛔ un contador que no es un número debería señalar el desplazamiento: %r" % (_m,))
# ⚠️ Y **enseñando el valor**: «no es un número» a secas no deja ver que lo que hay dentro es
#    un tipo MIME, que es lo único que explica el desplazamiento sin abrir la hoja.
ok(any("openxmlformats" in x for x in _m),
   u"⛔ el aviso no enseña lo que hay en la celda: %r" % (_m,))

# Un JSON roto en los anexos se dice, y no se lee «como se pueda».
_m = AX.revisar({AX.COL_ORIGEN: '["a", "b"'})
ok(any("JSON" in x for x in _m), u"un JSON roto en los anexos debería cantarse: %r" % (_m,))
ok(AX.origen({AX.COL_ORIGEN: '["a", "b"'})[0] == [],
   u"⛔ un JSON roto NO se lee como lista por comas: serían ids llamados `[\"a\"` y `\"b\"`")

# ── 4. Lo que se escribe después de copiar ─────────────────────────────────────────────────
c = AX.cambios(["x", "y"])
ok(c == {AX.COL_FINALES: '["x", "y"]', AX.COL_CUANTOS: 2},
   u"lo que se escribe no es lo esperado: %r" % (c,))
# ⚠️ Se escribe JSON de verdad, que es lo que la columna promete: escribir bien es lo único
#    que hace que la excepción se vaya muriendo sola.
ok(AX.origen({AX.COL_ORIGEN: c[AX.COL_FINALES]}) == (["x", "y"], []),
   u"⛔ lo que se escribe no se vuelve a leer limpio: %r" % (c[AX.COL_FINALES],))
ok(AX.cambios([]) == {} and AX.cambios(None) == {}, u"sin ids copiados no se escribe nada")
ok(AX.cambios(["", "  ", "x"]) == {AX.COL_FINALES: '["x"]', AX.COL_CUANTOS: 1},
   u"no limpia los ids vacíos antes de escribir")
ok(AX.cambios(["x"])[AX.COL_CUANTOS] == 1,
   u"el contador debería ir como número, no como texto")

print("%d comprobaciones" % hechas[0])
if fallos:
    print("\n%d ROJO(S):" % len(fallos))
    for f_ in fallos:
        print("  - %s" % f_)
    sys.exit(1)
print("verde")
