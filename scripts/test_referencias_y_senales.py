#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Banco de los arreglos del 2026-09-28: el regex de referencias y la señal del formulario.

Por qué existe
--------------
Los tres fallos que arregla este banco tenían la misma forma: **no daban error**. El regex no
veía el placeholder de la plantilla nueva y dejaba la referencia sin corregir en las 20+ páginas
del documento; la señal del formulario devolvía `False` siempre porque el parser no entendía el
formato de la hoja; y una `reference` vacía se sustituía por el `request_id`, que acababa
estampado en la cabecera. Ninguno se cae, ninguno avisa: los tres salen en verde.

Por eso las comprobaciones de aquí abajo no miran "¿funciona?", miran **"¿se pone rojo cuando
debe?"** — con el caso concreto que lo destapó en cada uno.

Cómo correrlo
-------------
    python scripts/test_referencias_y_senales.py

No necesita las librerías de Google: se doblan en `sys.modules` antes de importar, porque los
dos scripts las importan a nivel de módulo y lo que se prueba aquí son funciones puras.
"""
import os
import sys
import types
from datetime import datetime, timezone

# ⚠️ La salida va en UTF-8 a la fuerza. En el runner de Actions (Linux) sobra, pero en la
#    consola de Windows (cp1252) este banco REVIENTA al imprimir — y revienta justo en las
#    líneas marcadas con ⛔, o sea en las comprobaciones que más importan. El único caso en
#    que tiene algo que decir sería el que no puede decirlo.
for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding="utf-8")
    except Exception:  # pragma: no cover - consolas antiguas
        pass

# --- dobles de las librerías de Google, para poder importar sin credenciales ---------------
# ⚠️ Los paquetes llevan `__path__`: sin él, Python dice "'googleapiclient' is not a package" y
#    no deja importar `googleapiclient.http`. Un doble más pobre que el real no se nota hasta
#    que alguien lo usa de verdad.
for _nombre in ("google", "google.oauth2", "googleapiclient", "googleapiclient.discovery",
                "googleapiclient.http"):
    if _nombre not in sys.modules:
        _m = types.ModuleType(_nombre)
        _m.__path__ = []
        sys.modules[_nombre] = _m
sys.modules["google.oauth2"].service_account = types.SimpleNamespace(
    Credentials=types.SimpleNamespace(from_service_account_info=lambda *a, **k: None))
sys.modules["googleapiclient.discovery"].build = lambda *a, **k: None
sys.modules["googleapiclient.http"].MediaIoBaseDownload = object
sys.modules["googleapiclient.http"].MediaIoBaseUpload = object

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_pipeline_status as CPS            # noqa: E402
import fix_docx_publication_date as FIX        # noqa: E402

fallos = []


def ok(cond, que):
    print(("  OK    " if cond else "  FALLA ") + que)
    if not cond:
        fallos.append(que)


print("\n1 · el regex de referencias ve la plantilla NUEVA")

# ⛔ EL CASO QUE LO DESTAPÓ. La plantilla que se reparte hoy trae "Informe_S-41xx_2x": el 41 es
#    unidad+subcarpeta (ya se saben), el resto va en equis. El patrón viejo aceptaba O todo
#    dígitos O todo equis, nunca la mezcla, así que salía CIEGO — y habría repetido el caso
#    79E115DB: fecha corregida, referencia intacta, sin error.
ok(bool(FIX.REFERENCE_PATTERN.search("Informe_S-41xx_2x")),
   "caza el placeholder de la plantilla nueva (Informe_S-41xx_2x)")

# Y no puede haber roto los que ya cazaba:
for s in ("Informe_S-6009_26", "Informe_S-XXXX_XX", "Informe_S-xxxx_xx",
          "Acta_S-6301_26", "Memoria_S-6109_26"):
    ok(bool(FIX.REFERENCE_PATTERN.search(s)), "sigue cazando %s" % s)

# ⚠️ Y no se ha vuelto un colador: estas NO son referencias y no deben casar.
for s, por in (("Informe_S-41_26", "id de 2 cifras"),
               ("Informe_S-4100_2", "temporada de 1 cifra"),
               ("_S-4100_26", "sin la palabra del tipo")):
    ok(not FIX.REFERENCE_PATTERN.search(s), "NO caza %s (%s)" % (s, por))


print("\n2 · la forma canónica vive en un solo sitio")

ok(bool(FIX.REFERENCIA_CANONICA.fullmatch("Informe_S-2011_26")),
   "`REFERENCIA_CANONICA` acepta una referencia real")

# ⛔⛔ EL CASO DEL `or request_id`: con la columna `reference` vacía se colaba el request_id como
#    si fuera una referencia, y acababa estampado en la cabecera y dando nombre a la carpeta de
#    Drive. La guarda nueva se apoya en que esto NO case.
ok(not FIX.REFERENCIA_CANONICA.fullmatch("SOL-DOC-20260720-113951-79E115DB"),
   "⛔ RECHAZA un request_id: es lo que impide estamparlo como referencia")

# ⚠️ Y rechaza un placeholder sin rellenar: sirve para DETECTARLO (REFERENCE_PATTERN), no para
#    estamparlo. Confundir las dos es lo que convertiría la corrección en propagación.
ok(not FIX.REFERENCIA_CANONICA.fullmatch("Informe_S-XXXX_XX"),
   "⚠️ RECHAZA un placeholder: se detecta con un patrón y se estampa con el otro")

# El cruce con `reserved_id` se apoya en el grupo 2:
ok(FIX.REFERENCIA_CANONICA.fullmatch("Informe_S-4103_27").group(2) == "4103",
   "el número de la referencia se extrae para cruzarlo con `reserved_id`")

# ⛔ Y la puerta única se USA: `_regex_referencia_tolerante` compartía este criterio escrito a
#    mano. Dos copias que hoy coinciden por casualidad se rompen en silencio.
ok(FIX._regex_referencia_tolerante("SOL-DOC-20260720-113951") is None,
   "`_regex_referencia_tolerante` devuelve None si no es canónica (mejor no tocar que adivinar)")
ok(FIX._regex_referencia_tolerante("Informe_S-2010_26").search("Informe-S-2010_26") is not None,
   "…y sigue cazando la variante con guion (caso INLKHAP, 12 corridas invisible)")


print("\n3 · la señal del formulario, que no podía valer True nunca")

# ⛔⛔ EL CASO, MEDIDO: la columna A de la hoja de respuestas va en "DD/MM/AAAA HH:MM:SS", y
#    `parse_iso` hace `datetime.fromisoformat`, que devuelve None con ese formato. La señal
#    `form_responses_novedad` llevaba muerta desde que se escribió.
REAL = "28/09/2026 14:35:33"

ok(CPS.parse_iso(REAL) is None,
   "⛔ el gemelo que demuestra el fallo: `parse_iso` NO entiende el formato de Forms")
ok(CPS._parse_fecha_form(REAL) is not None,
   "⛔ …y `_parse_fecha_form` SÍ: es lo único que separa la señal viva de la muerta")

_d = CPS._parse_fecha_form(REAL)
ok(_d.year == 2026 and _d.month == 9 and _d.day == 28 and _d.hour == 14,
   "lee día, mes y hora en el orden correcto (28/09, no 09/28)")

# ⚠️ EL HUSO: la hoja escribe en hora local de Madrid y el checkpoint va en UTC. Sin zona, la
#    comparación se desvía hasta DOS horas y una respuesta nueva parecería más vieja que el
#    checkpoint — justo el fallo que la señal debía evitar.
ok(_d.tzinfo is not None, "⚠️ la fecha sale CON zona horaria, no ingenua")

# Sigue entendiendo ISO, por si la hoja cambia de formato algún día:
ok(CPS._parse_fecha_form("2026-07-31T23:44Z") == datetime(2026, 7, 31, 23, 44, tzinfo=timezone.utc),
   "sigue entendiendo ISO")

# Y un valor que no entiende es None, no una fecha inventada:
for basura in ("", "no es una fecha", "31/31/2026 99:99:99"):
    ok(CPS._parse_fecha_form(basura) is None,
       "devuelve None con %r: «no lo sé» no es «no hay novedad»" % basura)

# ⛔ Y LA COMPARACIÓN REAL, que es lo que decide la señal: una respuesta de hoy tiene que salir
#    MÁS NUEVA que el checkpoint de julio. Con el parser viejo esto era imposible de alcanzar.
_check = CPS.parse_iso("2026-07-31T23:44Z")
ok(CPS._parse_fecha_form(REAL) > _check,
   "⛔ una respuesta del 28/09 es más nueva que el checkpoint del 31/07 (la señal ya puede saltar)")


print("\n%s  (%d fallo(s))" % ("TODO OK" if not fallos else "HAY FALLOS", len(fallos)))
sys.exit(1 if fallos else 0)
