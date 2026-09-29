#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Banco de `drive_api.py`. Sin red, sin credenciales, sin reloj.

⛔ Las rutas de los casos son **las reales** de la pestaña `RUTAS`, incluidas las dos que ocupan
dos dígitos (`uct/actas` 6301–6499 y `electronica/general` 2001–2199) y la **inactiva**
(`propulsion/informes_tecnicos`), que es la que hace daño si se cuela.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding="utf-8")
    except Exception:
        pass

import drive_api as D

fallos = []
hechas = [0]


def ok(cond, que):
    hechas[0] += 1
    if not cond:
        fallos.append(que)


# 📏 Copiadas de `RUTAS` el 29/09/2026.
RUTAS = [
    {"unit_key": "uct", "subfolder_key": "general", "range_start": "6001",
     "range_end": "6099", "drive_folder_id": "F-uct-gen", "active": "TRUE"},
    {"unit_key": "uct", "subfolder_key": "actas", "range_start": "6301",
     "range_end": "6499", "drive_folder_id": "F-uct-actas", "active": "TRUE"},
    {"unit_key": "electronica", "subfolder_key": "general", "range_start": "2001",
     "range_end": "2199", "drive_folder_id": "F-elec-gen", "active": "TRUE"},
    {"unit_key": "propulsion", "subfolder_key": "srad", "range_start": "4101",
     "range_end": "4199", "drive_folder_id": "F-srad", "active": "TRUE"},
    # ⛔ La INACTIVA, con el MISMO rango que `srad` y apuntando al curso pasado.
    {"unit_key": "propulsion", "subfolder_key": "informes_tecnicos", "range_start": "4101",
     "range_end": "4199", "drive_folder_id": "F-VIEJA-25-26", "active": "FALSE"},
]

# ── 1. La carpeta-ruta, por RANGO ──────────────────────────────────────────────────────────
ok(D.carpeta_ruta(RUTAS, "uct", "actas", 6301) == "F-uct-actas", u"no encuentra el inicio del rango")
ok(D.carpeta_ruta(RUTAS, "uct", "actas", 6499) == "F-uct-actas", u"no encuentra el final del rango")
ok(D.carpeta_ruta(RUTAS, "uct", "actas", 6400) == "F-uct-actas", u"no encuentra el medio")
ok(D.carpeta_ruta(RUTAS, "uct", "general", 6050) == "F-uct-gen", u"confunde general con actas")
# ⛔ Las DOS que ocupan dos dígitos: aquí es donde fallaría deducir la subcarpeta del dígito.
ok(D.carpeta_ruta(RUTAS, "uct", "actas", 6450) == "F-uct-actas",
   u"⛔ un acta del segundo dígito (64xx) no se encuentra: es lo más frecuente del pipeline")
ok(D.carpeta_ruta(RUTAS, "electronica", "general", 2150) == "F-elec-gen",
   u"⛔ el común de Aviónica del segundo dígito (21xx) no se encuentra")

# ⛔ LA INACTIVA NO VALE, aunque su rango case: apunta a la carpeta del curso pasado, y archivar
#    ahí no da ningún error — sólo deja el documento en el año que no es.
ok(D.carpeta_ruta(RUTAS, "propulsion", "srad", 4150) == "F-srad", u"no encuentra la activa")
ok(D.carpeta_ruta(RUTAS, "propulsion", "informes_tecnicos", 4150) is None,
   u"⛔ ¡usa la ruta INACTIVA! archivaría en la carpeta de 25/26 sin dar error")

# Fuera de rango, unidad que no existe, id ilegible.
ok(D.carpeta_ruta(RUTAS, "uct", "actas", 6500) is None, u"acepta un id fuera del rango")
ok(D.carpeta_ruta(RUTAS, "uct", "actas", 6300) is None, u"acepta un id justo por debajo")
ok(D.carpeta_ruta(RUTAS, "inventada", "general", 6050) is None, u"acepta una unidad que no existe")
ok(D.carpeta_ruta(RUTAS, "uct", "actas", "chusta") is None, u"un id ilegible debería dar None")
ok(D.carpeta_ruta(RUTAS, "uct", "actas", None) is None, u"None debería dar None")
ok(D.carpeta_ruta([], "uct", "actas", 6301) is None, u"sin rutas no puede encontrar ninguna")
ok(D.carpeta_ruta(None, "uct", "actas", 6301) is None, u"unas rutas None no deberían reventar")
# Una ruta con el id de carpeta vacío no vale: colgaría de la raíz.
ok(D.carpeta_ruta([{"unit_key": "x", "subfolder_key": "y", "range_start": "1",
                    "range_end": "9", "drive_folder_id": "", "active": "TRUE"}],
                  "x", "y", 5) is None, u"una ruta sin carpeta no debería valer")

# ── 2. El cuerpo de la carpeta ─────────────────────────────────────────────────────────────
cuerpo, motivos = D.cuerpo_carpeta("Informe_S-2011_26", "F-elec-gen")
ok(motivos == [], u"un caso bueno no debería dar motivos: %r" % (motivos,))
ok(cuerpo == {"name": "Informe_S-2011_26", "mimeType": D.MIME_CARPETA,
              "parents": ["F-elec-gen"]}, u"el cuerpo no es el esperado: %r" % (cuerpo,))
ok(cuerpo["mimeType"] == "application/vnd.google-apps.folder",
   u"el mimeType no es el de una carpeta: crearía un fichero")
# ⚠️ El nombre ES la referencia: con otro, nadie encuentra la carpeta buscando el documento.
ok(cuerpo["name"] == "Informe_S-2011_26", u"la carpeta no se llama como la referencia")
ok(D.cuerpo_carpeta("Acta_S-6301_26", "F-uct-actas")[0]["name"] == "Acta_S-6301_26",
   u"un acta debería llevar su propio nombre")

for mala in ("chusta", "", None, "Informe_S-2011", "informe_s-2011_26 "):
    c, m = D.cuerpo_carpeta(mala, "F-x")
    ok(c is None, u"⛔ crea una carpeta llamada %r" % (mala,))
    ok(m and "canónica" in m[0], u"el motivo de %r no lo explica: %r" % (mala, m))

c, m = D.cuerpo_carpeta("Informe_S-2011_26", "")
ok(c is None and m and "raíz" in m[0],
   u"⛔ sin carpeta-ruta colgaría de la raíz de Drive, fuera del árbol del subsistema")
ok(D.cuerpo_carpeta("Informe_S-2011_26", None)[0] is None, u"un padre None no debería valer")

# ── 3. La URL ──────────────────────────────────────────────────────────────────────────────
ok(D.url_de("1Eig") == "https://drive.google.com/drive/folders/1Eig", u"la URL no cuadra")
ok(D.url_de("") is None and D.url_de(None) is None, u"sin id no hay URL")
ok(D.url_de("  1Eig  ") == "https://drive.google.com/drive/folders/1Eig", u"no recorta el id")

print("%d comprobaciones" % hechas[0])
if fallos:
    print("\n%d ROJO(S):" % len(fallos))
    for f_ in fallos:
        print("  - %s" % f_)
    sys.exit(1)
print("verde")
