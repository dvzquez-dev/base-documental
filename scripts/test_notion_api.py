#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Banco de `notion_api.py`. Sin red, sin credenciales, sin reloj.

⛔ Las etiquetas de los casos son **reales**: salen de `SOLICITUDES.tags_json` y se cruzan con
opciones que existen de verdad en la propiedad «Etiquetas» de Notion (183 el 29/09/2026).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding="utf-8")
    except Exception:
        pass

import notion_api as N

fallos = []
hechas = [0]


def ok(cond, que):
    hechas[0] += 1
    if not cond:
        fallos.append(que)


# 📏 Un trozo real de las 183 opciones que ya tiene «Etiquetas».
OPC = [u"informe", u"mensual", u"mayo", u"estructuras", u"aerodinámica", u"EuRoC", u"python",
       u"mpc", u"rocketpy", u"vspaero", u"viradinha mkII", u"simulacion", u"análisis",
       u"analisis", u"frenos de aire", u"PCB", u"software"]

PROPS = {"Título": u"Informe de ensayo estático", "ID (XXXX)": 4012,
         "Subsistema o Unidad": u"Subsistema de Propulsión", "Tipo Aerotech": u"Informe",
         "Temporada": u"2026/27"}

# ── 1. Los tipos, contra lo medido ─────────────────────────────────────────────────────────
ok(N.TIPOS_PROP == {"Título": "title", "ID (XXXX)": "number",
                    "Subsistema o Unidad": "select", "Tipo Aerotech": "select",
                    "Temporada": "select", "Etiquetas": "multi_select"},
   "TIPOS_PROP ya no es lo medido del esquema vivo")

ok(N.propiedad("Título", u"Un informe") == {"title": [{"text": {"content": u"Un informe"}}]},
   "el título no se envuelve como `title`")
ok(N.propiedad("ID (XXXX)", 4012) == {"number": 4012}, "el ID no se envuelve como `number`")
# ⚠️ El número va como número: mandarlo en texto deja la propiedad vacía sin decir nada.
ok(N.propiedad("ID (XXXX)", 4012)["number"] == 4012,
   "el ID se manda como texto: Notion dejaría la propiedad vacía")
ok(N.propiedad("Temporada", u"2026/27") == {"select": {"name": u"2026/27"}},
   "la temporada no se envuelve como `select`")
ok(N.propiedad("Etiquetas", [u"a", u"b"]) ==
   {"multi_select": [{"name": u"a"}, {"name": u"b"}]},
   "las etiquetas no se envuelven como `multi_select`")
ok(N.propiedad("Etiquetas", []) == {"multi_select": []}, "sin etiquetas debería ir una lista vacía")
ok(N.propiedad("Etiquetas", None) == {"multi_select": []}, "unas etiquetas None no deberían reventar")
ok(N.propiedad("Inventada", u"x") is None, "una propiedad desconocida debería dar None")
ok(N.propiedad("Subido por", u"x") is None,
   "`Subido por` es de tipo `person` y no está en la tabla: debería dar None, no inventarse")

# ── 2. Las etiquetas: reusar antes que duplicar ────────────────────────────────────────────
# ⛔ EL CASO DEL MÓDULO, con los valores reales medidos.
enviar, reusadas, nuevas = N.casar_etiquetas(
    [u"Python", u"MPC", u"RocketPy", u"VSPAERO", u"simulación", u"Viradinha MkII"], OPC)
ok(u"python" in enviar and u"Python" not in enviar,
   "no reusa la opción `python` que ya existe: %r" % (enviar,))
ok(u"viradinha mkII" in enviar, "no reusa `viradinha mkII`: %r" % (enviar,))
ok(u"simulacion" in enviar, "no reusa `simulacion` (sólo cambia la tilde): %r" % (enviar,))
ok(len(reusadas) == 6, "deberían reusarse las 6: %r" % (reusadas,))
ok(nuevas == [], "ninguna de esas 6 debería crear opción nueva: %r" % (nuevas,))
ok((u"Python", u"python") in reusadas, "el par reusado no dice qué vino y qué se manda")

# ⛔ Y el caso que el propio modelo produjo: DOS grafías del mismo tag en el mismo lote.
enviar, _r, nuevas = N.casar_etiquetas([u"Mallado", u"mallado", u"MALLADO"], [])
ok(enviar == [u"Mallado"], "tres grafías del mismo tag nuevo crean tres opciones: %r" % (enviar,))
ok(len(nuevas) == 1, "debería crearse UNA opción nueva, no %d" % len(nuevas))

# Las nuevas de verdad pasan tal cual y se cuentan.
enviar, reusadas, nuevas = N.casar_etiquetas([u"CFD", u"Fluent", u"informe"], OPC)
ok(enviar == [u"CFD", u"Fluent", u"informe"], "no pasa las nuevas tal cual: %r" % (enviar,))
ok(nuevas == [u"CFD", u"Fluent"], "no señala cuáles son nuevas: %r" % (nuevas,))
ok(reusadas == [], "no debería reusar ninguna aquí")
# ⚠️ Una que coincide EXACTA no cuenta como reusada: no hay nada que rescatar.
enviar, reusadas, _n = N.casar_etiquetas([u"informe"], OPC)
ok(reusadas == [], "una coincidencia exacta no es una reutilización: %r" % (reusadas,))
ok(enviar == [u"informe"], "la exacta debería pasar tal cual")

ok(N.casar_etiquetas([], OPC) == ([], [], []), "sin etiquetas, las tres listas vacías")
ok(N.casar_etiquetas(None, None) == ([], [], []), "None no debería reventar")
ok(N.casar_etiquetas([u"", u"   ", None, u"CFD"], [])[0] == [u"CFD"],
   "no limpia vacíos ni nulos")
ok(N.casar_etiquetas([u"  CFD  "], [u"CFD"])[0] == [u"CFD"], "no recorta antes de comparar")

# ⚠️ Lo aplanado se usa para comparar y NUNCA para enviar: mandar `analisis` donde Notion tiene
#    `análisis` crearía una TERCERA opción.
enviar, _r, _n = N.casar_etiquetas([u"ANÁLISIS"], [u"análisis"])
ok(enviar == [u"análisis"], "manda la forma aplanada en vez de la que existe: %r" % (enviar,))

# ── 3. El cuerpo entero ────────────────────────────────────────────────────────────────────
cuerpo, avisos = N.cuerpo_pagina("ds-123", PROPS)
ok(cuerpo is not None, "un cuerpo correcto no debería ser None: %r" % (avisos,))
ok(cuerpo["parent"] == {"type": "data_source_id", "data_source_id": "ds-123"},
   "el `parent` no es el esperado: %r" % (cuerpo["parent"],))
ok(sorted(cuerpo["properties"]) == sorted(PROPS), "no viajan todas las propiedades")
ok(cuerpo["properties"]["ID (XXXX)"] == {"number": 4012}, "el ID no viaja envuelto")
ok("children" not in cuerpo, "sin fichero no debería haber `children`")
ok(avisos == [], "un cuerpo limpio no debería dar avisos: %r" % (avisos,))

# Con fichero subido: el `markdown_source` de la subida directa, sin URL pública.
cuerpo, _a = N.cuerpo_pagina("ds-123", PROPS, markdown_source="fu-999")
ok(cuerpo["children"][0]["file"]["file_upload"]["id"] == "fu-999",
   "el fichero subido no se engancha a la página: %r" % (cuerpo.get("children"),))
ok(cuerpo["children"][0]["type"] == "file", "el bloque del fichero no es de tipo `file`")

# ⛔ Una propiedad que no se sabe envolver PARA la creación entera.
cuerpo, avisos = N.cuerpo_pagina("ds-123", dict(PROPS, Inventada=u"x"))
ok(cuerpo is None, "¡crea la página omitiendo una propiedad que no sabe envolver!")
ok(any("Inventada" in a for a in avisos), "el aviso no dice cuál es la propiedad: %r" % (avisos,))
ok(any("sin clasificar" in a for a in avisos),
   "el aviso no dice la consecuencia de crearla a medias: %r" % (avisos,))

# Sin data_source_id tampoco se crea nada.
cuerpo, avisos = N.cuerpo_pagina("", PROPS)
ok(cuerpo is None, "crea la página sin saber en qué base")
ok(any("data_source_id" in a for a in avisos), "el aviso no menciona el data_source_id")
ok(N.cuerpo_pagina(None, PROPS)[0] is None, "un data_source_id None debería parar la creación")

# Las etiquetas, dentro del cuerpo: se reusan y se avisa de las nuevas SIN parar la creación.
cuerpo, avisos = N.cuerpo_pagina(
    "ds-123", dict(PROPS, Etiquetas=[u"Python", u"CFD"]), opciones_etiquetas=OPC)
ok(cuerpo is not None, "una etiqueta nueva no debería impedir publicar: %r" % (avisos,))
nombres = [x["name"] for x in cuerpo["properties"]["Etiquetas"]["multi_select"]]
ok(nombres == [u"python", u"CFD"], "las etiquetas del cuerpo no son las casadas: %r" % (nombres,))
ok(any("ya existe" in a for a in avisos), "no avisa de la etiqueta rescatada: %r" % (avisos,))
ok(any("opciones nuevas" in a and "CFD" in a for a in avisos),
   "no avisa de cuántas opciones se van a crear: %r" % (avisos,))

# Sin la lista de opciones no se rescata nada, y eso se nota: todas cuentan como nuevas.
cuerpo, avisos = N.cuerpo_pagina("ds-123", dict(PROPS, Etiquetas=[u"Python"]))
ok(any("opciones nuevas" in a for a in avisos),
   "sin opciones conocidas debería decir que va a crear una: %r" % (avisos,))

cuerpo, avisos = N.cuerpo_pagina("ds-123", {})
ok(cuerpo is not None and cuerpo["properties"] == {},
   "un cuerpo sin propiedades debería construirse igual (lo decide quien llama)")

print("%d comprobaciones" % hechas[0])
if fallos:
    print("\n%d ROJO(S):" % len(fallos))
    for f_ in fallos:
        print("  - %s" % f_)
    sys.exit(1)
print("verde")
