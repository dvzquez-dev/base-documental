#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Banco de `analisis.py`. Sin red, sin credenciales, sin reloj.

⛔ Las celdas de los casos son **literales de la hoja**: `SOLICITUDES.quality_issues` y
`tags_json`, filas 3–6, leídas el 29/09/2026. Las dos formas de `severity` que conviven ahí son
el motivo de que este módulo exista.
"""
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


# 📏 Copiadas tal cual de la hoja.
REAL_MEDIA = (u'{"severity":"MEDIA","issues":["El documento se identifica como versión 0.1 y '
              u'mantiene la aprobación del Consejo pendiente.","La versión 1.0 figura como TBD."]}')
REAL_LOW_MEDIUM = (u'{"severity": "LOW_MEDIUM", "issues": ["Tareas aún en fase preliminar/en '
                   u'progreso.", "No hay métricas cuantitativas de mallado ni de par del '
                   u'servomotor."]}')
REAL_TAGS = u'["informe", "mensual", "mayo", "estructuras", "aerodinámica", "EuRoC", "CFD"]'
REAL_TAGS_RAROS = u'["EKF/ESKF", "C++", "SVB v1.2", "Viradinha MkII", "control EuRoC"]'

# ── 1. La severidad, en las dos lenguas y con compuestos ───────────────────────────────────
ok(A.NIVELES == ("baja", "media", "alta"), "los niveles ya no son los del contrato")

ok(A.severidad("MEDIA") == "media", "la forma REAL en español no se reconoce")
ok(A.severidad("LOW_MEDIUM") == "media", "la forma REAL compuesta no se reconoce")
ok(A.severidad("media") == "media", "el valor del contrato no se reconoce")
ok(A.severidad("baja") == "baja", "baja no se reconoce")
ok(A.severidad("alta") == "alta", "alta no se reconoce")
ok(A.severidad("LOW") == "baja", "LOW no se reconoce")
ok(A.severidad("HIGH") == "alta", "HIGH no se reconoce")
ok(A.severidad("  Media  ") == "media", "no recorta ni ignora la caja")
ok(A.severidad("crítica") is None or A.severidad("critica") == "alta",
   "critica debería ser alta (sin tilde, que es como la manda el modelo)")

# ⛔ LA DECISIÓN DEL MÓDULO: un compuesto sube, no baja. Equivocarse hacia abajo hace que alguien
#    apruebe un documento que no estaba bien.
ok(A.severidad("LOW_MEDIUM") == "media", "LOW_MEDIUM debería resolver al más ALTO")
ok(A.severidad("MEDIUM_HIGH") == "alta", "MEDIUM_HIGH debería resolver a alta")
ok(A.severidad("media-alta") == "alta", "el compuesto con guion debería resolver a alta")
ok(A.severidad("baja/media") == "media", "el compuesto con barra debería resolver a media")
ok(A.severidad("LOW_HIGH") == "alta", "de baja y alta debería quedarse con alta")
ok(A.severidad("alta_baja") == "alta", "el orden de los trozos no debería importar")

# ⚠️ Lo que no se entiende devuelve None. Inventarse un nivel es peor que decir que no se sabe.
for malo in ("chusta", "", "   ", None, "SEVERE_ISH", 42, [], {}):
    ok(A.severidad(malo) is None, "la severidad %r debería dar None" % (malo,))

# ── 2. Los avisos ──────────────────────────────────────────────────────────────────────────
avs = A.avisos(REAL_MEDIA)
ok(len(avs) == 2, "no saca los 2 avisos de la celda real: %r" % (avs,))
ok(avs[0].startswith("El documento se identifica"), "el primer aviso no es el de la celda")
ok(len(A.avisos(REAL_LOW_MEDIUM)) == 2, "no saca los avisos de la celda con espacios")
# Acepta el dict ya parseado tanto como la cadena de la hoja.
ok(A.avisos({"issues": ["uno", "  dos  ", "", None]}) == ["uno", "dos"],
   "no limpia los avisos de un dict")
ok(A.avisos({"avisos": ["uno"]}) == ["uno"], "no acepta la clave en español")
ok(A.avisos({}) == [], "sin avisos debería dar lista vacía")
ok(A.avisos("no soy json") == [], "una cadena que no es JSON no debería reventar")
ok(A.avisos(None) == [], "None no debería reventar")
ok(A.avisos('{"issues":"uno solo"}') == ["uno solo"],
   "un aviso suelto en vez de lista debería aceptarse")
ok(A.avisos('["no", "soy", "un", "dict"]') == [], "una lista en vez de dict no debería reventar")

# ── 3. Las etiquetas ───────────────────────────────────────────────────────────────────────
etq, m = A.etiquetas(REAL_TAGS)
ok(m == [], "las etiquetas reales no deberían dar motivos: %r" % (m,))
ok(len(etq) == 7, "no saca las 7 etiquetas reales: %r" % (etq,))
ok(etq[0] == "informe" and etq[-1] == "CFD", "las etiquetas no conservan el orden")

etq, m = A.etiquetas(REAL_TAGS_RAROS)
ok(m == [], "las etiquetas con barras y signos no deberían dar motivos: %r" % (m,))
ok("EKF/ESKF" in etq and "C++" in etq, "se pierden etiquetas con signos raros: %r" % (etq,))
ok("SVB v1.2" in etq, "se pierde una etiqueta con espacios y puntos")

# ⛔ EL CASO DEL MÓDULO: una coma parte la etiqueta en dos opciones nuevas de Notion.
etq, m = A.etiquetas(u'["informe", "control, EKF", "mayo"]')
ok("control, EKF" not in etq, "¡deja pasar una etiqueta con coma!")
ok(len(m) == 1 and "coma" in m[0], "no explica por qué se rechaza: %r" % (m,))
# ⚠️ Pero las buenas SÍ pasan: perderlas todas por una deja el documento sin indexar.
ok(etq == ["informe", "mayo"], "tira las etiquetas buenas por culpa de la mala: %r" % (etq,))

etq, m = A.etiquetas(u'["informe", "INFORME", " informe "]')
ok(etq == ["informe"], "no deduplica ignorando la caja: %r" % (etq,))
etq, m = A.etiquetas(u'["", "  ", null, "buena"]')
ok(etq == ["buena"], "no quita vacíos ni nulos: %r" % (etq,))

etq, m = A.etiquetas("esto no es json")
ok(etq == [] and m and "JSON" in m[0], "un tags_json inválido debería decirse: %r" % (m,))
etq, m = A.etiquetas(u'{"no":"soy lista"}')
ok(etq == [] and m and "lista" in m[0], "un tags_json que no es lista debería decirse")
ok(A.etiquetas(None) == ([], []), "None no debería dar motivos")
ok(A.etiquetas([]) == ([], []), "una lista vacía no debería dar motivos")
ok(A.etiquetas(["ya", "parseadas"]) == (["ya", "parseadas"], []),
   "una lista ya parseada debería pasar tal cual")

# ── 4. El repaso completo, sobre las dos filas reales ──────────────────────────────────────
norm, motivos = A.revisar_analisis(REAL_MEDIA, REAL_TAGS)
ok(norm["severidad"] == "media", "no normaliza la severidad real")
ok(len(norm["avisos"]) == 2, "no trae los avisos")
ok(len(norm["etiquetas"]) == 7, "no trae las etiquetas")
# ⚠️ `MEDIA` NO genera aviso: sólo difiere del contrato en la caja, y avisar por eso sería
#    una línea de ruido en cada fila — y una herramienta que grita por lo benigno se deja de
#    mirar, con lo que el aviso que SÍ importa (`LOW_MEDIUM`) se pierde entre ellos.
ok(motivos == [], "avisa por una diferencia sólo de caja: %r" % (motivos,))

norm, motivos = A.revisar_analisis(REAL_LOW_MEDIUM, REAL_TAGS)
ok(norm["severidad"] == "media", "LOW_MEDIUM no llega a media en el repaso")
ok(any("LOW_MEDIUM" in m for m in motivos), "el aviso no dice qué valor venía: %r" % (motivos,))

# El valor del contrato NO genera aviso: una herramienta que grita por lo correcto se deja de mirar.
norm, motivos = A.revisar_analisis(u'{"severidad":"media","avisos":["uno"]}', u'["x"]')
ok(motivos == [], "avisa por un valor que SÍ es del contrato: %r" % (motivos,))
ok(norm["severidad"] == "media", "no entiende el vocabulario del contrato")

# Una severidad ilegible se dice, y se dice la consecuencia.
norm, motivos = A.revisar_analisis(u'{"severity":"chusta","issues":["uno"]}', u'[]')
ok(norm["severidad"] is None, "una severidad ilegible no debería inventarse")
ok(any("revisor" in m for m in motivos),
   "el motivo no dice la consecuencia (que el revisor decide sin verla): %r" % (motivos,))

# ⚠️ Severidad media o alta sin un solo aviso: o falta el detalle o la severidad sobra.
_n, motivos = A.revisar_analisis(u'{"severity":"alta","issues":[]}', u'[]')
ok(any("sin un solo aviso" in m for m in motivos),
   "no avisa de una severidad alta sin avisos: %r" % (motivos,))
_n, motivos = A.revisar_analisis(u'{"severity":"baja","issues":[]}', u'[]')
ok(not any("sin un solo aviso" in m for m in motivos),
   "avisa por una severidad BAJA sin avisos, que es lo normal: %r" % (motivos,))

# ⛔ Con motivos se devuelve igual lo que sí se entendió: tirarlo todo deja al revisor sin los
#    avisos justo cuando hay algo raro.
norm, motivos = A.revisar_analisis(u'{"severity":"chusta","issues":["un aviso real"]}',
                                   u'["buena", "mala, con coma"]')
ok(motivos, "debería haber motivos")
ok(norm["avisos"] == ["un aviso real"], "tira los avisos buenos por la severidad mala")
ok(norm["etiquetas"] == ["buena"], "tira las etiquetas buenas: %r" % (norm["etiquetas"],))
ok(sorted(norm) == ["avisos", "etiquetas", "severidad"],
   "el normalizado no trae las tres claves: %r" % (sorted(norm),))

# Una celda vacía no revienta: es el estado de una fila recién ingerida.
norm, motivos = A.revisar_analisis("", "")
ok(norm["severidad"] is None and norm["avisos"] == [] and norm["etiquetas"] == [],
   "una celda vacía debería dar todo vacío sin reventar: %r" % (norm,))
norm, _m = A.revisar_analisis(None, None)
ok(norm["severidad"] is None, "None no debería reventar")

print("%d comprobaciones" % hechas[0])
if fallos:
    print("\n%d ROJO(S):" % len(fallos))
    for f_ in fallos:
        print("  - %s" % f_)
    sys.exit(1)
print("verde")
