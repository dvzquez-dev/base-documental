#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Banco de `ingesta_forms.py`. Sin red ni credenciales: todo lo de aquí es lógica pura.

Las etiquetas y los rangos NO son inventados: salen del `FB_PUBLIC_LOAD_DATA_` del formulario
publicado y de la pestaña `RUTAS`, medidos el 28/09/2026.

    python scripts/test_ingesta_forms.py
"""
import os
import sys
from datetime import date, datetime, timezone

for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding="utf-8")
    except Exception:  # pragma: no cover
        pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ingesta_forms as I  # noqa: E402

fallos = []


def ok(cond, que):
    print(("  OK    " if cond else "  FALLA ") + que)
    if not cond:
        fallos.append(que)


# RUTAS reales (activas) el 28/09/2026, con los rangos tal cual están en la hoja.
RUTAS = [
    {"unit_key": "dinamica_control", "subfolder_key": "general", "range_start": "1001",
     "range_end": "1099", "active": "TRUE"},
    {"unit_key": "electronica", "subfolder_key": "general", "range_start": "2001",
     "range_end": "2199", "active": "TRUE"},
    {"unit_key": "electronica", "subfolder_key": "software", "range_start": "2201",
     "range_end": "2299", "active": "TRUE"},
    {"unit_key": "electronica", "subfolder_key": "hardware", "range_start": "2301",
     "range_end": "2399", "active": "TRUE"},
    {"unit_key": "electronica", "subfolder_key": "ground_station", "range_start": "2401",
     "range_end": "2499", "active": "TRUE"},
    {"unit_key": "estructuras_aerodinamica", "subfolder_key": "general", "range_start": "3001",
     "range_end": "3099", "active": "TRUE"},
    {"unit_key": "propulsion", "subfolder_key": "general", "range_start": "4001",
     "range_end": "4099", "active": "TRUE"},
    # ⚠️ Esta está en FALSE en la hoja de verdad: la sustituyó `srad`, con el mismo rango.
    {"unit_key": "propulsion", "subfolder_key": "informes_tecnicos", "range_start": "4101",
     "range_end": "4199", "active": "FALSE"},
    {"unit_key": "propulsion", "subfolder_key": "srad", "range_start": "4101",
     "range_end": "4199", "active": "TRUE"},
    {"unit_key": "uct", "subfolder_key": "general", "range_start": "6001",
     "range_end": "6099", "active": "TRUE"},
    {"unit_key": "uct", "subfolder_key": "memorias_fabricacion", "range_start": "6101",
     "range_end": "6199", "active": "TRUE"},
    {"unit_key": "uct", "subfolder_key": "actas", "range_start": "6301",
     "range_end": "6499", "active": "TRUE"},
]

print("\n1 · la marca temporal del formulario NO es ISO")

REAL = "28/09/2026 14:35:33"
_d = I.fecha_form(REAL)
ok(_d is not None and (_d.year, _d.month, _d.day, _d.hour) == (2026, 9, 28, 14),
   "lee el formato de Forms y en el orden correcto (28/09, no 09/28)")
ok(_d is not None and _d.tzinfo is not None,
   "⚠️ sale CON zona horaria: la hoja escribe en local y el resto del pipeline compara en UTC, "
   "así que sin zona hay hasta dos horas de desvío")
ok(I.fecha_form("2026-07-31T23:44Z") is not None, "sigue entendiendo ISO por si la hoja cambia")
for basura in ("", "no es fecha", "31/31/2026 99:99:99"):
    ok(I.fecha_form(basura) is None,
       "devuelve None con %r: «no lo sé» no es «hoy»" % basura)

print("\n2 · la temporada acaba el 1 de septiembre")

# ⛔⛔ EL CASO QUE DISTINGUE LAS DOS LECTURAS. De enero a agosto, año natural y temporada dan lo
#     mismo; sólo de septiembre a diciembre divergen. Un error aquí no da síntomas 8 meses de 12.
ok(I.temporada_de(date(2024, 10, 29))[1] == "25",
   "⛔ octubre de 2024 da sufijo 25, no 24: lo fija `Tabla_S-4301_25`, creada ese día")
ok(I.temporada_de(date(2026, 7, 19))[1] == "26",
   "⚠️ julio de 2026 da 26, donde ambas lecturas coinciden — por eso los datos no distinguían")
ok(I.temporada_de(date(2026, 9, 1)) == ("2026/27", "27"), "el 1 de septiembre ya es la nueva")
ok(I.temporada_de(date(2026, 8, 31)) == ("2025/26", "26"), "y el 31 de agosto todavía no")

print("\n3 · de las etiquetas del Form a la ruta, por el RANGO")

_r = I.ruta_de("Propulsión (4)", "SRAD - 1", RUTAS)
ok(_r is not None and _r["subfolder_key"] == "srad",
   "⛔ «SRAD - 1» da la ruta `srad`, no `informes_tecnicos`: los nombres NO coinciden y por eso "
   "se empareja por el número, no por el texto")
ok(_r is not None and str(_r.get("active")).upper() == "TRUE",
   "…y coge la ACTIVA, no la vieja que comparte rango")

# ⛔⛔ EL CASO DE LOS DOS DÍGITOS: `actas` va de 6301 a 6499, así que la subcarpeta NO se puede
#     deducir de la segunda cifra. Si alguien lo hiciera, fallaría justo en lo más frecuente.
_a = I.ruta_de("Unidad de Coordinación Técnica (6)", "Actas - (3/4)", RUTAS)
ok(_a is not None and _a["subfolder_key"] == "actas",
   "⛔⛔ «Actas - (3/4)» resuelve aunque su rango ocupe DOS dígitos (6301–6499)")

_c = I.ruta_de("Aviónica (2)", "Común - (0/1)", RUTAS)
ok(_c is not None and _c["subfolder_key"] == "general",
   "⛔ y el común de Aviónica igual: dos dígitos (2001–2199), un solo rango")

ok(I.ruta_de("Aviónica (2)", "Software - 2", RUTAS)["subfolder_key"] == "software",
   "las subcarpetas nuevas de Aviónica resuelven")

# ⚠️ Y LO QUE TIENE QUE FALLAR: una unidad sin ruta activa. Adivinar aquí archiva el documento
#    en el sitio equivocado sin dar error.
ok(I.ruta_de("Unidad de Logística (9)", "General - 0", RUTAS) is None,
   "⚠️ una unidad sin ruta ACTIVA en la tabla da None, no una ruta parecida")
ok(I.ruta_de("sin numero", "General - 0", RUTAS) is None,
   "una etiqueta sin cifras da None")

print("\n4 · el siguiente identificador libre")

_ruta_actas = [r for r in RUTAS if r["subfolder_key"] == "actas"][0]
_res = [{"season_suffix": "27", "reserved_id": "6301", "released": "FALSE"},
        {"season_suffix": "27", "reserved_id": "6302", "released": "FALSE"}]
ok(I.siguiente_id(_ruta_actas, _res, "27") == 6303, "da el primer hueco del rango")

# ⚠️ Los rangos se reparten POR TEMPORADA: el 6301 del curso pasado no ocupa el de éste.
ok(I.siguiente_id(_ruta_actas, [{"season_suffix": "26", "reserved_id": "6301",
                                 "released": "FALSE"}], "27") == 6301,
   "⚠️ no cuenta las reservas de OTRA temporada: los rangos se reparten por curso")
ok(I.siguiente_id(_ruta_actas, [{"season_suffix": "27", "reserved_id": "6301",
                                 "released": "TRUE"}], "27") == 6301,
   "ni las liberadas")

# ⛔ AGOTARSE NO ES DAR LA VUELTA: dos documentos con la misma referencia se pisan en el upsert.
_lleno = [{"season_suffix": "27", "reserved_id": str(n), "released": "FALSE"}
          for n in range(6301, 6500)]
ok(I.siguiente_id(_ruta_actas, _lleno, "27") is None,
   "⛔ con el rango agotado devuelve None en vez de reutilizar un número")

print("\n5 · la referencia y el identificador de solicitud")

ok(I.referencia("Informe de Subsistema", 2011, "27") == "Informe_S-2011_27",
   "⚠️ el prefijo es la PRIMERA palabra del tipo: «Informe de Subsistema» da `Informe`")
ok(I.referencia("Acta", 6303, "27") == "Acta_S-6303_27", "y un tipo de una palabra, igual")
ok(I.referencia("Acta", None, "27") is None, "sin número no se inventa una referencia")

_f = I.fecha_form("19/07/2026 23:48:31")
_rid = I.request_id(_f, "17|Acta_S-6301_26")
ok(_rid is not None and _rid.startswith("SOL-DOC-20260719-234831-"),
   "⛔ el request_id lleva la hora DEL ENVÍO, no la de la pasada: es el dato con el que se mide "
   "si el pipeline va con retraso")
ok(I.request_id(_f, "x") != I.request_id(_f, "y"), "y dos filas distintas no colisionan")

print("\n6 · el fichero adjunto y las filas pendientes")

ok(I.file_id_de("https://drive.google.com/open?id=1N6vG0zRyPHi5LjVFAOhtvd0zebPOewo7CgPlZY9Le4o")
   == "1N6vG0zRyPHi5LjVFAOhtvd0zebPOewo7CgPlZY9Le4o",
   "saca el id del enlace que escribe Forms")
ok(I.file_id_de("") is None and I.file_id_de("no es una url") is None,
   "un enlace que no se entiende no es un fichero vacío")
ok(len(I.ids_de_lista("https://drive.google.com/open?id=AAAAAAAAAAAA, "
                      "https://drive.google.com/open?id=BBBBBBBBBBBB")) == 2,
   "la columna de anexos admite varios separados por comas")

# ⚠️ En la hoja los números llegan unas veces como 17 y otras como '17 con espacios.
_pend = I.pendientes([{"form_row": 17}, {"form_row": "18"}, {"form_row": 19}],
                     [{"form_row": "17"}, {"form_row": " 18 "}])
ok([p["form_row"] for p in _pend] == [19],
   "⚠️ compara `form_row` como TEXTO recortado: si no, se re-ingiere lo ya ingerido")

print("\n%s  (%d fallo(s))" % ("TODO OK" if not fallos else "HAY FALLOS", len(fallos)))
sys.exit(1 if fallos else 0)
