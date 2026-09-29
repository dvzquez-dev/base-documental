#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Banco del **encargo del paso 2**: qué se le pide al modelo y qué se hace con lo que conteste.

⛔ Lo que este banco defiende, y es lo único que de verdad importa aquí: **la bandera `analyzed`
no se marca si el análisis no vino entero**. Un paso que escribe la bandera sin los datos deja el
expediente **dado por analizado sin análisis**, y el siguiente paso lo publica: el revisor abre
la ficha y no ve ni resumen ni avisos de calidad, que es justo lo que tiene que leer antes de
aprobar. Por eso `servicios.analizar` se negaba en voz alta hasta hoy.

⚠️ Sin red y sin modelo: `preguntar` se inyecta.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding="utf-8")
    except Exception:
        pass

import analisis as A

fallos = []
hechas = [0]


def ok(cond, que):
    hechas[0] += 1
    if not cond:
        fallos.append(que)


# 📏 Una fila real de SOLICITUDES (la 18, la Memoria Técnica de Aviónica para EuRoC).
FILA = {
    "request_id": "SOL-DOC-20260720-113951-79E115DB",
    "reference": "Informe_S-2011_26",
    "doc_title": u"Memoria Técnica Aviónica EuRoC",
    "doc_type": "Informe de Subsistema",
    "unit_label": u"Subsistema de Aviónica",
    "author_name": u"José Martínez",
    "season": "26/27",
}


# ── 1. El encargo ──────────────────────────────────────────────────────────────────────────
p = A.prompt_de(FILA)
ok(isinstance(p, str) and len(p) > 200, u"el encargo sale vacío o minúsculo: %r" % (len(p or ""),))
# ⛔ Sin el título y el tipo, el modelo resume a ciegas.
for _c in (u"Memoria Técnica Aviónica EuRoC", u"Informe de Subsistema", u"Subsistema de Aviónica"):
    ok(_c in p, u"⛔ el encargo no le dice al modelo %r: resume sin saber qué está leyendo" % _c)
ok("Informe_S-2011_26" in p, u"el encargo no nombra la referencia del expediente")
# ⛔⛔ El encargo tiene que PEDIR JSON explícitamente: `leer_json` sabe rebuscarlo entre la prosa,
#    pero eso es el paracaídas, no el plan. Un encargo que no lo pide falla la mitad de las veces.
ok("JSON" in p or "json" in p, u"⛔ el encargo no pide JSON: `leer_json` es el paracaídas, no el plan")
for _k in ("resumen", "etiquetas", "severidad"):
    ok(_k in p, u"⛔ el encargo no nombra la clave %r que luego se lee" % _k)
# ⛔ Y nombra los TRES niveles: si no, el modelo se inventa el vocabulario y `severidad()` lo
#    devuelve como `None` — que es correcto, pero deja el expediente sin severidad.
for _n in A.NIVELES:
    ok(_n in p, u"⛔ el encargo no nombra el nivel %r, así que el modelo se inventa el suyo" % _n)
# ⚠️ Una fila sin nada no revienta: el encargo sale, pobre pero válido.
ok(isinstance(A.prompt_de({}), str) and A.prompt_de({}), u"una fila vacía no debería reventar")
ok(isinstance(A.prompt_de(None), str), u"`None` tampoco revienta")


# ── 2. Lo que se hace con la respuesta ─────────────────────────────────────────────────────
BUENA = {"resumen": u"Describe la aviónica del cohete para EuRoC 2026.",
         "etiquetas": [u"aviónica", "EuRoC"],
         "severidad": "MEDIUM",
         "avisos": [u"Falta la fecha de publicación en la portada."]}

cols, motivos = A.de_la_respuesta(BUENA)
ok(motivos == [], u"una respuesta buena no debería dar motivos: %r" % (motivos,))
ok(cols.get("executive_summary") == BUENA["resumen"], u"no escribe el resumen: %r" % (cols,))
# ⛔ La severidad pasa por el normalizador: el modelo dice `MEDIUM`, la columna quiere `media`.
_q = json.loads(cols.get("quality_issues") or "{}")
ok(_q.get("severity") == "media",
   u"⛔ la severidad NO pasa por `severidad()`: llega %r y la app no la pinta" % (_q.get("severity"),))
ok(_q.get("issues") == BUENA["avisos"], u"los avisos no viajan: %r" % (_q,))
# ⛔ `tags_json` se llama `_json` y **tiene que serlo**: una fila real la trae por comas y eso ya
#    costó una puerta única entera. Lo que escribimos nosotros va bien escrito.
ok(json.loads(cols.get("tags_json")) == [u"aviónica", "EuRoC"],
   u"⛔ `tags_json` no es JSON de verdad: %r" % (cols.get("tags_json"),))
ok(cols.get("analyzed") == "TRUE", u"con el análisis entero, la bandera se marca: %r" % (cols,))

# ── 3. Lo que NO se da por analizado ───────────────────────────────────────────────────────
# ⛔⛔ ÉSTE es el caso que justifica el fichero. Sin resumen no hay nada que archivar
#    (`crear_resumen` se niega a crear un fichero vacío) y el revisor se queda sin lo que lee.
cols, motivos = A.de_la_respuesta({"etiquetas": ["x"], "severidad": "baja"})
ok(cols.get("analyzed") != "TRUE",
   u"⛔⛔ marca `analyzed` SIN RESUMEN: el expediente queda dado por analizado sin análisis")
ok(any("resumen" in m for m in motivos), u"el motivo no dice que falta el resumen: %r" % (motivos,))

# Un resumen de dos palabras no es un resumen.
cols, motivos = A.de_la_respuesta({"resumen": "ok", "etiquetas": ["x"], "severidad": "baja"})
ok(cols.get("analyzed") != "TRUE", u"⛔ da por bueno un resumen de dos caracteres")

# ⛔ Una severidad que no se reconoce no se inventa, y sin ella no está analizado: la severidad
#    es lo que la app pinta en la tarjeta que se mira ANTES de aprobar.
cols, motivos = A.de_la_respuesta({"resumen": u"Un resumen bastante largo y con sentido.",
                                   "etiquetas": ["x"], "severidad": "CHUNGO"})
ok(cols.get("analyzed") != "TRUE", u"⛔ marca analizado con una severidad que nadie reconoce")
ok(any("severidad" in m for m in motivos), u"el motivo no nombra la severidad: %r" % (motivos,))

# ⚠️ `LOW_MEDIUM` es real y compuesto: sube al más alto. Equivocarse hacia abajo hace que
#    alguien apruebe un documento que no estaba bien.
cols, _ = A.de_la_respuesta({"resumen": u"Un resumen bastante largo y con sentido.",
                             "etiquetas": ["x"], "severidad": "LOW_MEDIUM"})
ok(json.loads(cols["quality_issues"])["severity"] == "media",
   u"⛔ un compuesto baja en vez de subir: %r" % (cols.get("quality_issues"),))

# ⚠️ Sin etiquetas SÍ se puede dar por analizado: no todo documento tiene etiquetas que poner,
#    y exigirlas pararía expedientes correctos. Pero la columna queda como lista vacía, no vacía.
cols, motivos = A.de_la_respuesta({"resumen": u"Un resumen bastante largo y con sentido.",
                                   "severidad": "baja"})
ok(cols.get("analyzed") == "TRUE", u"⚠️ sin etiquetas se para un expediente correcto: %r" % (motivos,))
ok(cols.get("tags_json") == "[]", u"la columna queda como lista vacía: %r" % (cols.get("tags_json"),))

# Entradas rotas: nunca lanzan, y nunca marcan.
for mala in (None, [], "chusta", {"resumen": 42}, {"resumen": u"x" * 40, "etiquetas": "a,b",
                                                   "severidad": "baja"}):
    try:
        c, m = A.de_la_respuesta(mala)
        ok(c.get("analyzed") != "TRUE" or isinstance(mala, dict) and mala.get("etiquetas") == "a,b",
           u"⛔ marca analizado con una respuesta rota: %r" % (mala,))
    except Exception as e:
        ok(False, u"⛔ `de_la_respuesta` lanza con %r: %s" % (mala, e))

# ⚠️ Una lista de etiquetas que llega como texto por comas se lee igual: es la forma que ya trae
#    una fila real, y rechazarla sería parar un análisis por cómo lo escribió el modelo.
cols, _ = A.de_la_respuesta({"resumen": u"Un resumen bastante largo y con sentido.",
                             "etiquetas": u"aviónica, EuRoC", "severidad": "baja"})
ok(json.loads(cols["tags_json"]) == [u"aviónica", "EuRoC"],
   u"⛔ unas etiquetas por comas se pierden: %r" % (cols.get("tags_json"),))

# ⚠️ Y el motivo de un fallo se puede leer: lista de textos, no objetos.
_, motivos = A.de_la_respuesta({})
ok(motivos and all(isinstance(m, str) for m in motivos), u"los motivos no son texto: %r" % (motivos,))

print("%d comprobaciones" % hechas[0])
if fallos:
    print("\n%d ROJO(S):" % len(fallos))
    for f_ in fallos:
        print("  - %s" % f_)
    sys.exit(1)
print("verde")
