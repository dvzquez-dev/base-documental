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

# ---- SUSTITUCION: la referencia ya usada REUSA su numero -------------------
# Lo pidio Daniel el 29/09: "que se pueda poner la referencia ya utilizada y que se sustituya".
# El formulario YA lo pregunta -- "Sustituye o revisa otro documento?", "Indica la referencia
# del archivo que deseas sustituir" y "Motivo" -- y nadie lo leia: `siguiente_id` coge siempre
# el siguiente libre, asi que una reentrega se llevaba un NUMERO NUEVO y quedaba como documento
# distinto. Hoy eso lo arregla Cowork a mano en cada ciclo.
YA = [
    {"reference": "Informe_S-2011_27", "reserved_id": "2011", "request_id": "SOL-VIEJA"},
    {"reference": "Acta_S-6301_27", "reserved_id": "6301", "request_id": "SOL-ACTA"},
]

r = I.sustitucion_de({"sustituye": "Si", "referencia_sustituida": "Informe_S-2011_27",
                      "motivo_sustitucion": "errata"}, YA)
ok(r is not None, "no reconoce una sustitucion declarada con referencia existente")
ok(r and r.get("reserved_id") == "2011", "no REUSA el numero: %r" % (r,))
ok(r and r.get("replaces_document") == "SOL-VIEJA", "no anota a quien sustituye: %r" % (r,))
ok(r and r.get("replacement_reference") == "Informe_S-2011_27", "no anota la referencia")
ok(r and r.get("replacement_reason") == "errata", "no arrastra el motivo: %r" % (r,))
ok(r and not r.get("motivo_error"), "una sustitucion buena no deberia dar error")

ok(I.sustitucion_de({"sustituye": "No", "referencia_sustituida": "Informe_S-2011_27"}, YA)
   is None, "un No no deberia sustituir aunque traiga referencia")
ok(I.sustitucion_de({}, YA) is None, "sin respuesta no hay sustitucion")
ok(I.sustitucion_de(None, None) is None, "entradas vacias no revientan")

r = I.sustitucion_de({"sustituye": "Si", "referencia_sustituida": "Informe_S-9999_27"}, YA)
ok(r is not None and r.get("motivo_error"),
   "dice sustituir a una referencia que NO existe y pasa callando: %r" % (r,))
ok(r and r.get("reserved_id") is None,
   "se inventa un numero para una referencia que no existe: %r" % (r,))

r = I.sustitucion_de({"sustituye": "Si", "referencia_sustituida": ""}, YA)
ok(r is not None and r.get("motivo_error"), "sustituye sin decir a que, y no se canta")
# Y el motivo TIENE que ser el de "no dice cual", no el de "no existe": sin esto la guarda
# salia CIEGA -- con la referencia vacia el bucle tampoco encuentra nada y el caso seguia
# verde diciendo lo que no era. Mandan a arreglar cosas distintas.
ok(r and u"no dice cuál" in r.get("motivo_error", ""),
   "confunde 'no dice cual' con 'no existe': %r" % (r.get("motivo_error"),))
ok(r and r.get("reserved_id") is None, "sin referencia tampoco se inventa un numero")

# ⚠️ El «Sí» va LITERAL: fabricarlo con `unicode_escape` lo destroza y el caso sale rojo
#    sobre código correcto, que es como se pierde media hora buscando donde no hay nada.
for _si in (u"Si", u"Sí", u"SI", u" sí ", u"Yes", u"TRUE"):
    ok(I.sustitucion_de({"sustituye": _si, "referencia_sustituida": "Acta_S-6301_27"},
                        YA) is not None, "no entiende %r como que SI sustituye" % _si)
for _no in (u"No", u"NO", u" no ", u""):
    ok(I.sustitucion_de({"sustituye": _no, "referencia_sustituida": "Acta_S-6301_27"},
                        YA) is None, "toma %r por un si" % _no)

# ---- LA HOJA DE RESPUESTAS, TRADUCIDA ------------------------------------
# La cabecera es LA REAL, medida el 29/09/2026: el formulario no escribe claves, escribe las
# preguntas tal cual. Y la subcarpeta son CINCO columnas, una por unidad -- la respuesta esta
# en la que toque y las otras cuatro vienen vacias.
CAB_REAL = [
    u"Marca temporal", u"Dirección de correo electrónico", u"Nombre y apellidos",
    u"Título breve y descriptivo", u"Tipo de documento", u"Subsistema o unidad",
    u"Elige la subcarpeta de GNC en la que deseas incluir el archivo:",
    u"Elige la subcarpeta de Aviónica en la que deseas incluir el archivo:",
    u"Elige la subcarpeta de Aeroestructuras en la que deseas incluir el archivo:",
    u"Elige la subcarpeta de Propulsión en la que deseas incluir el archivo:",
    u"Elige la subcarpeta de la UCT en la que deseas incluir el archivo:",
    u"Adjunta aquí el documento", u"Adjunta aquí los anexos",
    u"Contexto para la revisión", u"Anotaciones propuestas",
    u"¿Sustituye o revisa otro documento?",
    u"Indica la referencia del archivo que deseas sustituir",
    u"Declara si afirmas lo siguiente:", u"Motivo de la sustitución o revisión"]
# La fila 3 REAL, tal cual.
FILA_REAL = [u"2/07/2026 14:58:08", u"daniel.vazquez.pineiro@uvigoaerotech.com",
             u"Daniel Vázquez Piñeiro", u"Acta Reunión 27/06/2026", u"Acta",
             u"Unidad de Coordinación Técnica (6)", u"", u"", u"", u"", u"Actas - (3/4)",
             u"https://drive.google.com/open?id=1d8Kj9WFfhjZmJRrTRan_Lf8VKmSWKUF3",
             u"", u"", u"", u"No", u"", u"Confirmo", u""]

r = I.respuesta_de(CAB_REAL, FILA_REAL, 3)
ok(r.get("form_row") == "3", "`form_row` es el NUMERO DE FILA, no una columna: %r" % (r,))
ok(r.get("title_short") == u"Acta Reunión 27/06/2026", "no traduce el titulo")
ok(r.get("document_type") == u"Acta", "no traduce el tipo")
ok(r.get("unit_label") == u"Unidad de Coordinación Técnica (6)", "no traduce la unidad")
# La subcarpeta sale de la UNICA de las cinco que viene rellena.
ok(r.get("subfolder_label") == u"Actas - (3/4)",
   "no coge la subcarpeta de la columna que toca: %r" % (r.get("subfolder_label"),))
ok(r.get("source_drive_url", "").endswith("1d8Kj9WFfhjZmJRrTRan_Lf8VKmSWKUF3"), "no coge el enlace")
ok(r.get("sustituye") == "No", "no lee la pregunta de sustitucion")
ok(not r.get("motivo_error"), "una fila buena no deberia dar error: %r" % (r.get("motivo_error"),))

# Con DOS subcarpetas marcadas no se elige a dedo: archivaria donde no es SIN DAR ERROR.
_dos = list(FILA_REAL); _dos[6] = u"General - 0"
r2 = I.respuesta_de(CAB_REAL, _dos, 4)
ok(r2.get("subfolder_label") == "", "elige una de dos subcarpetas a dedo: %r" % (r2,))
ok(r2.get("motivo_error") and "2" in r2["motivo_error"], "no canta las dos: %r" % (r2,))

# Una fila mas corta que la cabecera no revienta (Sheets recorta las celdas vacias del final).
r3 = I.respuesta_de(CAB_REAL, [u"2/07/2026 14:58:08", u"a@b.c"], 5)
ok(r3.get("form_email") == "a@b.c" and r3.get("title_short") == "",
   "una fila corta deberia rellenarse con vacios: %r" % (r3,))
ok(I.respuesta_de([], [], 2).get("form_row") == "2", "sin cabecera no revienta")

print("\n%s  (%d fallo(s))" % ("TODO OK" if not fallos else "HAY FALLOS", len(fallos)))
sys.exit(1 if fallos else 0)
