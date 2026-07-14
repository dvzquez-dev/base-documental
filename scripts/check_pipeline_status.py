#!/usr/bin/env python3
"""
check_pipeline_status.py — Chequeo externo y barato de "¿hay algo que hacer?"
para el pipeline documental Solaris.

Por qué existe: la tarea programada de Cowork (Claude) hacía, en cada ciclo,
seis lecturas distintas (varias pestañas de Sheets + el JSON de Notion) solo
para decidir si merecía la pena arrancar una pasada completa. Cada una de
esas lecturas consume ejecución/recursos de Cowork. Este script mueve ese
trabajo a GitHub Actions (cómputo gratis en repos públicos), corriendo cada
pocos minutos, y publica un ÚNICO JSON pequeño con la decisión ya calculada.
Cowork pasa de hacer seis lecturas a hacer un solo fetch HTTP.

Salida: data/pipeline_status.json (committeado y publicado por GitHub Pages
en https://dvzquez-dev.github.io/base-documental/data/pipeline_status.json).

CAMBIO 2026-07-10 (cuarta vuelta — diagnóstico corregido) — el fetch HTTP se
MANTIENE como mecanismo principal (existe justo para que Cowork no tenga que
gastar ejecución leyendo Sheets seis veces por ciclo; quitarlo sería resolver
el síntoma equivocado). Lo que estaba mal no era "hacer un fetch", sino la URL
que se fetcheaba: las vueltas anteriores de este diagnóstico culparon a un CDN
externo (GitHub Pages / raw.githubusercontent.com / jsDelivr) de servir una
respuesta atascada en la URL LITERAL sin parámetros. Diagnóstico más fino:
fetchear la MISMA URL literal dos veces seguidas devolvió el mismo byte a byte
exacto aunque el archivo real ya se había republicado (confirmado comparando
con un fetch con parámetro, que sí traía contenido fresco en el mismo
instante) — eso apunta a que el propio mecanismo de fetch cachea por URL
exacta, no a un fallo de tres CDNs independientes coincidiendo exactamente
igual. Cowork tiene bloqueado añadir parámetros de cache-busting él mismo,
pero SÍ lee siempre el valor ACTUAL de CONFIG.QUICKCHECK_STATUS_URL en vez de
uno fijo — así que ahora es este script (el publicador, no quien lee) quien
reescribe esa celda con un parámetro de cache-busting nuevo en cada
publicación (ver rotate_status_url). Cada fetch de Cowork usa entonces una URL
literal genuinamente distinta a la de la ejecución anterior, sin que Cowork
tenga que modificar nada por su cuenta. Como respaldo de auditoría adicional
(no la fuente principal), el resultado también se escribe en la celda
CONFIG.QUICKCHECK_RESULT_JSON vía la Sheets API (requiere scope de escritura,
no solo spreadsheets.readonly).

Limitación conocida y estructural, no una decisión de diseño: no puede
comprobar Gmail (envíos reales de correo, ni si un revisor ya respondió a un
hilo de aprobación), porque eso requiere el conector OAuth de Gmail que solo
tiene Cowork como persona autenticada — una service account no puede leer el
Gmail de nadie sin delegación de dominio, y este Workspace ya tiene bloqueada
por política de organización ese tipo de delegación externa (misma familia de
restricción que DRIVE_STAGING_CLEANUP_DIAGNOSIS). Por eso el Paso 4
(procesar_respuesta_revisor) y el Paso 9 (seguimiento_envios_gmail) nunca
pueden confirmarse aquí con certeza: como mucho, este script puede señalar
"hay un borrador de aprobación esperando desde hace tiempo, merece la pena
que Cowork compruebe Gmail" (ver pasos_necesarios.4_verificar_gmail), pero no
puede saber si ya hay respuesta. El Paso 9 sigue siendo obligatorio en toda
pasada completa y parcial, siempre, sin excepción.

CAMBIO 2026-07-10: además del nivel_pasada_recomendado de 3 valores (NINGUNA /
PARCIAL_SEGUIMIENTO / COMPLETA), este script ahora calcula también
pasos_necesarios: qué pasos concretos del pipeline (1,2,3,5,6,7) tienen
trabajo pendiente de verdad según el estado real de SOLICITUDES, RESERVAS_ID,
SEGUIMIENTO_ENVIOS y el formulario de ingesta — determinista, sin adivinar.
Motivo: en una PASADA COMPLETA de antes, Cowork releía los 8 pasos siempre,
aunque 6 de ellos no tuvieran nada que hacer. Ahora puede leer solo los pasos
que de verdad tienen trabajo. El Paso 4 (requiere Gmail) y el Paso 8 (solo se
dispara reactivamente cuando otro paso falla, no tiene condición propia) no
se pueden determinar aquí con certeza — ver arriba.

Requiere la misma variable de entorno GDRIVE_SA_KEY (JSON de la service
account) que ya usa publish_temp_pdfs.py.
"""

import base64
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

from google.oauth2 import service_account
from googleapiclient.discovery import build

SPREADSHEET_ID = "1EL5luWUYD5_3onxaDUSHmexzzQZEkPNLW1Y4QzzRg20"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]  # CAMBIO 2026-07-10: antes .readonly; ahora necesita escritura para CONFIG.QUICKCHECK_RESULT_JSON (ver docstring del módulo)
OUTPUT_PATH = "data/pipeline_status.json"
META_JSON_PATH = "data/meta.json"  # generado por scripts/sync-notion.mjs en este mismo repo

# CAMBIO 2026-07-13 (a petición de Daniel, evidencia real en EVENTOS_LOG del 2026-07-13
# 00:30-15:27: 8 de 11 ciclos salieron COMPLETA con "falso positivo confirmado" por Cowork
# en el propio ciclo) — snapshot de la corrida anterior, usado por el FIX B de abajo para
# saber si una fila "aprobada, no cerrada, con bloqueo estructural ya diagnosticado" cambió
# de verdad desde la última vez, o si sigue exactamente igual (en cuyo caso no debe forzar
# COMPLETA otra vez). Se commitea junto con OUTPUT_PATH en el mismo push.
STATE_FILE = "data/quickcheck_last_seen.json"

# Marcas de texto en SOLICITUDES.last_error que indican "esto ya está diagnosticado como
# bloqueo estructural conocido" (p.ej. un DOCX de ~4.6MB que no se puede volver a subir con
# las herramientas de Cowork) — no un fallo transitorio a reintentar. Usado por el FIX B.
#
# CAMBIO 2026-07-14 (bug real confirmado con evidencia — Daniel reportó pasadas COMPLETA
# repetidas sin motivo real): UAWUVW7 llevaba varios ciclos seguidos forzando COMPLETA
# porque su last_error real en Sheets empieza por "BLOQUEO_PDF_..." — una marca que Cowork
# usa de verdad en la práctica pero que NO estaba en esta tupla. tiene_marca_bloqueo_estructural()
# nunca la reconocía, así que el FIX B (bloqueos_conocidos_sin_cambios) jamás se activaba
# para esa fila, por más que el updated_at llevara horas sin cambiar. Se añade "BLOQUEO_PDF"
# como marca reconocida. Si en el futuro aparece otra variante de texto usada de verdad en
# last_error para el mismo tipo de bloqueo estructural, añadirla aquí también.
STRUCTURAL_BLOCK_MARKERS = ("PENDIENTE_MANUAL_CONFIRMADO", "MANUAL_INTERVENTION", "BLOQUEO_PDF")
STALE_ACTION_MINUTES = 90  # CAMBIO 2026-07-10 (antes 20, luego 45): ver CONFIG.QUICKCHECK_STALENESS_THRESHOLD_MINUTES,
# que es el valor que Cowork usa de verdad (esta constante es solo documentación, mantenerla
# sincronizada a mano). Se subió porque Cowork pasó de revisar cada hora a revisar cada 15 min:
# con ese ciclo tan corto, el propio chequeo frecuente ya actúa de red de seguridad, y ya no
# hace falta un umbral agresivo — un umbral demasiado corto solo generaba pasadas completas
# de más por jitter de publicación (colas de build de GitHub Pages, contención de git entre
# los 3 workflows que comitean a este repo), no por caídas reales del Action.

# Tiempo mínimo que debe llevar un borrador de aprobación en BORRADOR_PENDIENTE antes de que
# valga la pena decirle a Cowork "comprueba Gmail para el Paso 4" — evita marcarlo como
# pendiente de verificación en el mismo minuto en que se creó el borrador, cuando es
# fisicamente imposible que el revisor ya haya contestado.
MIN_MINUTOS_ANTES_DE_VERIFICAR_GMAIL_PASO4 = 10

# Señales que, si son las ÚNICAS activas, solo requieren el Paso 9 (seguimiento de
# envíos de Gmail) en vez de la pasada completa del pipeline. Añadido 2026-07-09:
# antes Cowork tenía que releer el objeto "señales" cada ciclo y aplicar esta regla
# el mismo en lenguaje natural (frágil, sin memoria entre ciclos); ahora el propio
# script decide el nivel exacto y Cowork solo lee un campo, sin reinterpretar nada.
SEÑALES_SOLO_SEGUIMIENTO = {"seguimiento_envios_pendiente", "log_envio_ia_pendiente"}


PASOS_CORE = ("1", "2", "3", "5", "6", "7")  # pasos "de pipeline" de verdad; 4_verificar_gmail NO cuenta como core


def calcular_nivel_pasada(señales, lecturas_fallidas, pasos_necesarios):
    """Devuelve 'NINGUNA', 'PARCIAL_SEGUIMIENTO' o 'COMPLETA'.

    CAMBIO 2026-07-10 (segunda vuelta, a petición de Daniel): al principio,
    cualquier pasos_necesarios activo (incluido "4_verificar_gmail") forzaba
    COMPLETA. Eso era incoherente: "hay que comprobar si el revisor respondió
    en Gmail" es trabajo de la MISMA naturaleza que el Paso 9 (verificación de
    correo, sin tocar ningún paso de pipeline 1-8), no una razón real para
    etiquetar el ciclo como "pasada completa". Ahora "4_verificar_gmail" por
    sí solo NUNCA fuerza COMPLETA — solo lo hacen los pasos "core" de verdad
    (1,2,3,5,6,7, ver PASOS_CORE arriba). Si el único trabajo pendiente es
    4_verificar_gmail (con o sin señales de solo-seguimiento), el nivel sigue
    siendo PARCIAL_SEGUIMIENTO, y Cowork sabe (por el propio JSON) que además
    de Paso 9 debe leer 04_procesar_respuesta_revisor y comprobar Gmail para
    el revisor. Sigue sin poder confirmarse aquí: eso requiere Gmail, que este
    script no tiene.

    Reglas (en este orden):
    1. Si alguna lectura falló de verdad (no sabemos su valor real), nunca nos
       fiamos de un patrón que parezca "solo seguimiento" — forzamos COMPLETA.
    2. Si hay algún paso CORE (1,2,3,5,6,7) con trabajo detectado, es COMPLETA
       (Cowork usa pasos_necesarios para leer solo esos pasos, no todos).
    3. Si no hay ningún paso core pendiente, y ninguna señal ni 4_verificar_gmail
       están activos, NINGUNA.
    4. Si no hay ningún paso core pendiente, y las únicas señales activas están
       dentro de SEÑALES_SOLO_SEGUIMIENTO (4_verificar_gmail puede estar activo
       o no, da igual), PARCIAL_SEGUIMIENTO.
    5. Cualquier otro caso (alguna señal fuera de SEÑALES_SOLO_SEGUIMIENTO sin
       paso core, p.ej. cola_publicacion_pdf_pendiente), COMPLETA.
    """
    if lecturas_fallidas:
        return "COMPLETA"
    core_pendiente = any(pasos_necesarios.get(k) for k in PASOS_CORE)
    if core_pendiente:
        return "COMPLETA"
    activas = {k for k, v in señales.items() if v}
    verificar_gmail_paso4 = bool(pasos_necesarios.get("4_verificar_gmail"))
    if not activas and not verificar_gmail_paso4:
        return "NINGUNA"
    if activas <= SEÑALES_SOLO_SEGUIMIENTO:
        return "PARCIAL_SEGUIMIENTO"
    return "COMPLETA"


def get_credentials():
    raw = os.environ.get("GDRIVE_SA_KEY", "").strip()
    if not raw:
        print("ERROR: falta la variable de entorno GDRIVE_SA_KEY.", file=sys.stderr)
        sys.exit(1)
    try:
        info = json.loads(raw)
    except json.JSONDecodeError:
        info = json.loads(base64.b64decode(raw))
    return service_account.Credentials.from_service_account_info(info, scopes=SCOPES)


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def now_dt():
    return datetime.now(timezone.utc)


def parse_iso(value):
    if not value:
        return None
    try:
        v = str(value).strip()
        if v.endswith("Z"):
            v = v[:-1] + "+00:00"
        dt = datetime.fromisoformat(v)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def es_true(value):
    """Interpreta el mismo convenio de booleanos-como-texto que usan todos los
    prompts del pipeline: la celda dice literalmente "TRUE" o "FALSE" (o queda
    vacía, que se trata como FALSE)."""
    return str(value or "").strip().upper() == "TRUE"


def tiene_marca_bloqueo_estructural(last_error):
    """FIX B (2026-07-13): True si last_error ya contiene una de las marcas de
    diagnóstico conocido en STRUCTURAL_BLOCK_MARKERS (p.ej. un DOCX que no se
    puede volver a subir por límite de tamaño). Usado para no forzar COMPLETA
    otra vez en un expediente ya diagnosticado, mientras nada cambie de verdad."""
    if not last_error:
        return False
    texto = str(last_error)
    return any(marker in texto for marker in STRUCTURAL_BLOCK_MARKERS)


def load_state():
    """Carga el snapshot {request_id: updated_at} de la corrida anterior (FIX B).
    Si el archivo no existe todavía (primera corrida) o está corrupto, devuelve
    un dict vacío — en ese caso ninguna fila puede coincidir con "sin cambios",
    así que el comportamiento por defecto es seguro (no se excluye nada por error)."""
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE) or ".", exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, separators=(",", ":"))


class SheetReadError(Exception):
    """Fallo real de lectura (red, permisos, API) — distinto de 'la pestaña está
    vacía'. Se usa para que las señales que dependan de esta lectura se traten
    como 'desconocido' (forzar pasada completa), nunca como 'falso' silencioso."""


def get_values(sheets, rng):
    resp = sheets.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID, range=rng).execute()
    return resp.get("values", [])


def rows_as_dicts(sheets, sheet_name):
    """Lee la pestaña completa y la devuelve como lista de dicts usando la fila 1 como cabecera.
    Busca los nombres de columna dinámicamente, no asume posiciones fijas.
    Lanza SheetReadError si la lectura falla de verdad (para no confundir un error
    de API con 'la pestaña no tiene filas')."""
    try:
        values = get_values(sheets, f"{sheet_name}!A1:ZZ")
    except Exception as exc:
        raise SheetReadError(f"no se pudo leer {sheet_name}: {exc}") from exc
    if not values:
        return []  # pestaña genuinamente vacía (sin ni siquiera cabecera) — no es un error
    header = [h.strip() for h in values[0]]
    out = []
    for row in values[1:]:
        row = row + [""] * (len(header) - len(row))
        out.append(dict(zip(header, row)))
    return out


def read_config(sheets):
    # Deliberadamente NO se atrapa la excepción aquí: si no podemos leer CONFIG
    # (checkpoint, EMERGENCY_STOP), no tenemos base fiable para decidir nada.
    # Dejamos que main() falle y NO escriba pipeline_status.json — el archivo
    # publicado anterior se queda tal cual, y el umbral de antigüedad
    # (checkedAt) que revisa Cowork detectará que este chequeo lleva sin
    # actualizarse y hará la pasada completa por precaución.
    rows = rows_as_dicts(sheets, "CONFIG")
    config = {}
    for row in rows:
        key = row.get("key") or row.get("Key") or row.get("KEY")
        value = row.get("value") or row.get("Value") or row.get("VALUE")
        if key:
            config[key] = value
    return config


def upsert_config_value(sheets, key, value):
    """Escribe o actualiza una fila key/value en la pestaña CONFIG (requiere el
    scope de escritura de SCOPES, ver CAMBIO 2026-07-10 en el docstring del
    módulo). Si la key ya existe, actualiza solo su celda 'value'. Si no
    existe, añade una fila nueva al final. No asume posiciones fijas de
    columna: las busca por cabecera ("key"/"value"), igual que rows_as_dicts."""
    values = get_values(sheets, "CONFIG!A1:Z")
    if not values:
        raise SheetReadError("CONFIG está vacío, no se puede escribir el resultado del quickcheck")
    header = [h.strip() for h in values[0]]
    try:
        key_col = header.index("key")
    except ValueError:
        key_col = 0
    try:
        value_col = header.index("value")
    except ValueError:
        value_col = 1

    row_idx = None
    for i, row in enumerate(values[1:], start=2):  # 1-based; la fila 1 es la cabecera
        cell_key = row[key_col] if key_col < len(row) else ""
        if str(cell_key).strip() == key:
            row_idx = i
            break

    if row_idx is not None:
        rng = f"CONFIG!{_col_letter(value_col)}{row_idx}"
        sheets.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=rng,
            valueInputOption="RAW",
            body={"values": [[value]]},
        ).execute()
    else:
        new_row = [""] * (max(key_col, value_col) + 1)
        new_row[key_col] = key
        new_row[value_col] = value
        sheets.spreadsheets().values().append(
            spreadsheetId=SPREADSHEET_ID,
            range="CONFIG!A1",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": [new_row]},
        ).execute()


def rotate_status_url(sheets, result):
    """Reescribe CONFIG.QUICKCHECK_STATUS_URL con un parámetro de cache-busting
    NUEVO en cada publicación, horneado por el propio publicador (no por quien
    lee la URL).

    CAMBIO 2026-07-10 (cuarta vuelta — diagnóstico corregido a petición de
    Daniel): las vueltas anteriores culpaban a un CDN externo (GitHub Pages /
    raw.githubusercontent.com / jsDelivr) de servir una respuesta atascada en
    la URL literal. Diagnóstico más fino: fetchear la MISMA URL literal dos
    veces seguidas, en la misma sesión interactiva, devolvió el mismo byte a
    byte exacto aunque el archivo real en el servidor ya se había publicado de
    nuevo (confirmado comparando con un fetch con parámetro, que sí devolvía
    contenido distinto/más reciente en el mismo instante). Eso apunta a que el
    propio mecanismo de fetch de Cowork cachea por URL exacta, no a un
    problema de los tres servidores de contenido (que coincidan los tres en el
    mismo comportamiento ya era la pista: no tiene sentido que tres CDNs
    independientes fallen exactamente igual).

    Cowork tiene bloqueado añadir parámetros de cache-busting él mismo (para
    no ser manipulable por contenido no confiable que le pida modificar URLs),
    pero SÍ lee siempre el valor ACTUAL de CONFIG.QUICKCHECK_STATUS_URL en vez
    de un valor fijo. Por tanto, si el propio publicador (este script) cambia
    el valor de esa celda en cada ejecución, cada fetch de Cowork usa una URL
    literal genuinamente distinta a la de la ejecución anterior — nunca puede
    coincidir con una entrada ya cacheada, sin que Cowork tenga que modificar
    nada por su cuenta. Esto mantiene "el fetch" como mecanismo (a petición
    explícita de Daniel), solo corrige por qué estaba trayendo el dato
    equivocado."""
    base = "https://dvzquez-dev.github.io/base-documental/data/pipeline_status.json"
    token = result["checkedAt"].replace(":", "").replace("-", "").rstrip("Z")
    nueva_url = f"{base}?v={token}"
    try:
        upsert_config_value(sheets, "QUICKCHECK_STATUS_URL", nueva_url)
    except Exception as exc:
        print(f"ERROR: no se pudo rotar CONFIG.QUICKCHECK_STATUS_URL: {exc}", file=sys.stderr)


def publish_result(sheets, result):
    """Publica el resultado por varios caminos: (1) commit/push de
    data/pipeline_status.json a este repo (GitHub Pages) — sigue siendo LA
    fuente que Cowork lee, vía fetch, como siempre; (2) CONFIG.QUICKCHECK_STATUS_URL
    se reescribe con un parámetro de cache-busting nuevo cada vez (ver
    rotate_status_url) para que ese fetch nunca devuelva una respuesta
    cacheada de una ejecución anterior; (3) CONFIG.QUICKCHECK_RESULT_JSON se
    mantiene también como respaldo de auditoría vía Sheets (no es la fuente
    principal). Si (2) o (3) fallan (p.ej. el service account todavía no
    tiene permiso de EDITOR en esta hoja, solo Lector), no lo ocultamos: se
    deja constancia clara en stderr, pero (1) sigue publicándose igual para
    no perder el histórico."""
    compact = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    try:
        upsert_config_value(sheets, "QUICKCHECK_RESULT_JSON", compact)
    except Exception as exc:
        print(
            f"ERROR: no se pudo escribir CONFIG.QUICKCHECK_RESULT_JSON (¿el service account "
            f"tiene permiso de EDITOR en esta hoja, no solo lector?): {exc}",
            file=sys.stderr,
        )
    write_and_push(result)
    rotate_status_url(sheets, result)


def calcular_pasos_necesarios(sheets, config, checkpoint_dt, seguimiento_rows, lecturas_fallidas, previous_state):
    """Calcula, de forma determinista y a partir del estado real en Sheets, qué
    pasos concretos del pipeline (1,2,3,5,6,7) tienen trabajo pendiente ahora
    mismo. Devuelve (pasos: dict[str,bool], detalle: dict[str,str],
    bloqueos_conocidos_sin_cambios: list[str], nuevo_estado: dict[str,str]).

    Pasos 4 y 8 NO se calculan aquí con certeza (ver docstring del módulo):
    - Paso 4 (procesar_respuesta_revisor) depende de si un revisor ya respondió
      un hilo de Gmail. Este script solo puede aproximar "hay un borrador de
      aprobación esperando desde hace más de MIN_MINUTOS_ANTES_DE_VERIFICAR_GMAIL_PASO4
      minutos" como pista de que merece la pena que Cowork compruebe Gmail — se
      expone como pasos["4_verificar_gmail"], no como un "4" de trabajo confirmado.
    - Paso 8 (gestión de errores) no tiene condición propia: solo se dispara
      reactivamente cuando otro paso falla durante la propia pasada de Cowork.

    CAMBIO 2026-07-13 (dos arreglos pedidos por Daniel, con evidencia real de
    EVENTOS_LOG del 2026-07-13 00:30-15:27: 8 de 11 ciclos salieron COMPLETA con
    "falso positivo confirmado" por el propio Cowork en el ciclo):

    FIX A — Paso 2 contaba filas de prueba/duplicadas ya cerradas (closed=TRUE)
    como "pendientes de analizar" para siempre, porque el criterio solo miraba
    received/analyzed sin mirar closed. Una fila cerrada ya está resuelta por
    definición, sin importar lo que diga analyzed. Ver el "and not es_true(closed)"
    añadido más abajo.

    FIX B — Paso 5/7 forzaban COMPLETA para siempre en expedientes ya diagnosticados
    como bloqueados por un límite estructural (caso VAXBFDH/A7F4NFG/UAWUVW7: DOCX
    de ~4.6MB que las herramientas de Cowork no pueden volver a subir). Ahora, si
    una fila approved=TRUE/closed=FALSE tiene en last_error una marca de
    STRUCTURAL_BLOCK_MARKERS Y su updated_at no cambió desde la corrida anterior
    (comparado contra previous_state, ver load_state/save_state), no cuenta para
    marcar el paso 5/7 como necesario ni para forzar COMPLETA — pero sí se reporta
    en bloqueos_conocidos_sin_cambios para no perderla de vista. En cuanto
    updated_at cambie (p.ej. porque el GitHub Action fix_docx_publication_date.py
    lo resolvió), se re-evalúa desde cero automáticamente en la siguiente corrida.
    """
    pasos = {"1": False, "2": False, "3": False, "4_verificar_gmail": False, "5": False, "6": False, "7": False}
    detalle = {}
    bloqueos_conocidos_sin_cambios = []
    nuevo_estado = {}

    # Lectura única y completa de SOLICITUDES, reutilizada por los pasos 2,3,5,6,7.
    try:
        solicitudes = rows_as_dicts(sheets, "SOLICITUDES")
    except SheetReadError as exc:
        print(str(exc), file=sys.stderr)
        lecturas_fallidas.append("SOLICITUDES_FULL")
        # Sin poder leer SOLICITUDES de verdad, no podemos afirmar nada sobre los
        # pasos 2,3,5,6,7 con seguridad: los marcamos todos como pendientes para
        # forzar la pasada completa, igual que ya hacen las demás señales.
        for k in ("2", "3", "5", "6", "7"):
            pasos[k] = True
        detalle["SOLICITUDES_FULL"] = "no se pudo leer SOLICITUDES, se asumen todos los pasos pendientes por seguridad"
        solicitudes = []

    if solicitudes:
        # Snapshot de esta corrida (todas las filas, no solo las aprobadas) para que la
        # próxima corrida pueda comparar updated_at — FIX B.
        nuevo_estado = {
            r.get("request_id"): r.get("updated_at", "")
            for r in solicitudes
            if r.get("request_id")
        }

        # --- Paso 2: análisis de documento pendiente ---
        # FIX A (2026-07-13): se excluyen las filas ya cerradas (closed=TRUE). Antes,
        # una fila de test o un duplicado ya resuelto pero con analyzed=FALSE contaba
        # como pendiente para siempre (p.ej. FORM-TEST-ROW-2-IGNORED, o los duplicados
        # SOL-DOC-20260703-130905-1RM72OTI / ...-115545-1IJZX9QI-ROW4). Una fila cerrada
        # ya está resuelta por definición, sin importar analyzed.
        pendientes_paso2 = [
            r for r in solicitudes
            if es_true(r.get("received")) and not es_true(r.get("analyzed")) and not es_true(r.get("closed"))
        ]
        if pendientes_paso2:
            pasos["2"] = True
            detalle["2"] = f"{len(pendientes_paso2)} solicitud(es) con received=TRUE y analyzed=FALSE (excluyendo cerradas)"

        # --- Paso 3: solicitud de aprobación pendiente de crear ---
        # Candidatas: ya analizadas, sin decisión todavía (ni aprobado, ni rechazado,
        # ni cambios solicitados), y no cerradas. De esas, solo cuenta como "pendiente
        # de Paso 3" si todavía NO existe NINGÚN registro de tipo solicitud_aprobacion
        # en SEGUIMIENTO_ENVIOS para su request_id (si ya existe, el Paso 3 ya se hizo;
        # lo que falta como mucho es Paso 4 — verificar la respuesta del revisor —, no
        # Paso 3 otra vez).
        #
        # CAMBIO 2026-07-14 (dos bugs reales confirmados con evidencia — Daniel reportó
        # pasadas COMPLETA repetidas con falsos positivos confirmados por Cowork en el
        # propio ciclo, dos ciclos seguidos):
        #
        # FIX C.1 — faltaba "and not es_true(r.get('closed'))" aquí, a diferencia del
        # Paso 2 (que sí lo tiene desde el FIX A). Una fila cerrada ya está resuelta por
        # definición, tenga o no decisión registrada (p.ej. duplicados/históricos
        # cerrados por otra vía) — no debe seguir contando como "pendiente" para siempre.
        #
        # FIX C.2 — el filtro anterior solo excluía filas con un borrador TODAVÍA en
        # estado_final=="BORRADOR_PENDIENTE". En cuanto un borrador de aprobación se
        # enviaba de verdad y el Paso 9 lo verificaba (estado_final pasa a
        # ENVIADO_VERIFICADO_GMAIL, DISCREPANCIA o DESCONOCIDO), la fila DESAPARECÍA de
        # ya_con_borrador y volvía a contarse como "sin borrador todavía" — falso
        # positivo permanente para cualquier solicitud cuyo correo de aprobación ya se
        # envió. Ahora se considera "ya se hizo el Paso 3" si existe CUALQUIER registro
        # solicitud_aprobacion para ese request_id, sin importar en qué estado_final esté.
        ya_tiene_solicitud_aprobacion = {
            r.get("request_id")
            for r in seguimiento_rows
            if (r.get("tipo_email") or "").strip() == "solicitud_aprobacion"
        }
        candidatas_paso3 = [
            r for r in solicitudes
            if es_true(r.get("analyzed"))
            and not es_true(r.get("approved"))
            and not es_true(r.get("rejected"))
            and not es_true(r.get("changes_requested"))
            and not es_true(r.get("closed"))
            and r.get("request_id") not in ya_tiene_solicitud_aprobacion
        ]
        if candidatas_paso3:
            pasos["3"] = True
            detalle["3"] = f"{len(candidatas_paso3)} solicitud(es) analizada(s) sin decisión y sin borrador de aprobación todavía"

        # --- Paso 5 y 7: base común "aprobada y no cerrada" ---
        # FIX B (2026-07-13): antes, CUALQUIER fila approved=TRUE/closed=FALSE bastaba
        # para marcar el paso 5 (y, vía el mismo conjunto, el paso 7) como pendiente,
        # forzando COMPLETA ciclo tras ciclo aunque el expediente llevara horas/días
        # exactamente igual (caso VAXBFDH/A7F4NFG/UAWUVW7: DOCX ~4.6MB que las
        # herramientas de Cowork no pueden volver a subir, diagnóstico ya conocido y
        # escrito en last_error). Ahora se separan en dos grupos:
        #   - aprobadas_no_cerradas_nuevas: SÍ cuentan para paso 5/7 y para forzar COMPLETA.
        #   - bloqueos_conocidos_sin_cambios: tienen una marca de STRUCTURAL_BLOCK_MARKERS
        #     en last_error Y su updated_at es idéntico al de la corrida anterior (según
        #     previous_state) — no cuentan para nada de lo anterior, pero se reportan
        #     aparte para que no se pierdan de vista. En cuanto updated_at cambie de
        #     verdad (p.ej. lo resuelve fix_docx_publication_date.py), vuelven a
        #     evaluarse desde cero en la siguiente corrida.
        aprobadas_no_cerradas = [r for r in solicitudes if es_true(r.get("approved")) and not es_true(r.get("closed"))]
        aprobadas_no_cerradas_nuevas = []
        for r in aprobadas_no_cerradas:
            request_id = r.get("request_id")
            last_error = r.get("last_error", "")
            updated_at = r.get("updated_at", "")
            if tiene_marca_bloqueo_estructural(last_error) and previous_state.get(request_id) == updated_at and updated_at:
                bloqueos_conocidos_sin_cambios.append(request_id)
            else:
                aprobadas_no_cerradas_nuevas.append(r)

        # --- Paso 5: publicar aprobado pendiente ---
        if aprobadas_no_cerradas_nuevas:
            pasos["5"] = True
            detalle["5"] = (
                f"{len(aprobadas_no_cerradas_nuevas)} solicitud(es) aprobada(s) y no cerrada(s) todavía "
                f"(nuevas; excluye {len(bloqueos_conocidos_sin_cambios)} bloqueo(s) estructural(es) ya conocido(s) sin cambios)"
                if bloqueos_conocidos_sin_cambios
                else f"{len(aprobadas_no_cerradas_nuevas)} solicitud(es) aprobada(s) y no cerrada(s) todavía"
            )

        # --- Paso 6: libro de datos pendiente (SIN TOCAR — lógica intacta a petición de Daniel) ---
        pendientes_paso6 = [
            r for r in solicitudes
            if es_true(r.get("approved")) and not es_true(r.get("base_database_registered"))
        ]
        if pendientes_paso6:
            pasos["6"] = True
            detalle["6"] = f"{len(pendientes_paso6)} solicitud(es) aprobada(s) sin registrar todavía en el Libro de Datos"

        # --- Paso 7: reconciliación/alertas — solo si algún recordatorio ya venció ---
        # FIX B aplicado también aquí: itera solo sobre aprobadas_no_cerradas_nuevas,
        # no sobre todas las aprobadas-no-cerradas (mismo motivo que Paso 5 arriba).
        ahora = now_dt()
        vencidos = []
        for r in aprobadas_no_cerradas_nuevas:
            next_reminder = parse_iso(r.get("next_reminder_at"))
            if next_reminder is None or next_reminder <= ahora:
                vencidos.append(r)
        if vencidos:
            pasos["7"] = True
            detalle["7"] = f"{len(vencidos)} solicitud(es) aprobada(s)-no-cerrada(s) con recordatorio vencido o sin fijar"

    # --- Paso 4 (proxy, no confirmable sin Gmail): borradores de aprobación
    # esperando desde hace tiempo ---
    ahora = now_dt()
    esperando_revisor = []
    for r in seguimiento_rows:
        if (r.get("tipo_email") or "").strip() == "solicitud_aprobacion" and (r.get("estado_final") or "").strip() == "BORRADOR_PENDIENTE":
            creado = parse_iso(r.get("fecha_borrador_creado"))
            if creado is None or (ahora - creado) >= timedelta(minutes=MIN_MINUTOS_ANTES_DE_VERIFICAR_GMAIL_PASO4):
                esperando_revisor.append(r)
    if esperando_revisor:
        pasos["4_verificar_gmail"] = True
        detalle["4_verificar_gmail"] = (
            f"{len(esperando_revisor)} borrador(es) de aprobación en BORRADOR_PENDIENTE desde hace más de "
            f"{MIN_MINUTOS_ANTES_DE_VERIFICAR_GMAIL_PASO4} min — no se puede confirmar sin Gmail, Cowork debe comprobarlo"
        )

    # --- Paso 1: entradas nuevas del formulario sin ingerir en SOLICITUDES ---
    try:
        form_spreadsheet_id = config.get("FORM_RESPONSES_SPREADSHEET_ID")
        form_sheet_name = config.get("FORM_RESPONSES_SHEET_NAME")
        if form_spreadsheet_id and form_sheet_name:
            resp = sheets.spreadsheets().values().get(
                spreadsheetId=form_spreadsheet_id,
                range=f"{form_sheet_name}!A2:A",
            ).execute()
            form_rows = resp.get("values", [])
            total_form_rows = len(form_rows)
            if total_form_rows:
                # form_row en SOLICITUDES referencia el número de fila real del Forms
                # (la fila 2 del Forms = form_row "2", etc.), tal como describe
                # 01_forms_ingesta. Comparamos por conteo de filas ya conocidas.
                form_rows_conocidos = {
                    str(r.get("form_row")).strip()
                    for r in solicitudes
                    if str(r.get("form_row") or "").strip()
                }
                total_esperado = total_form_rows + 1  # +1 porque la fila 1 es cabecera
                pendientes_paso1 = [
                    str(i) for i in range(2, total_esperado + 1) if str(i) not in form_rows_conocidos
                ]
                if pendientes_paso1:
                    pasos["1"] = True
                    detalle["1"] = f"{len(pendientes_paso1)} fila(s) del formulario sin ingerir todavía en SOLICITUDES (form_row: {', '.join(pendientes_paso1[:10])}{'...' if len(pendientes_paso1) > 10 else ''})"
    except Exception as exc:
        print(f"Aviso: no se pudo calcular el Paso 1 de forma precisa: {exc}", file=sys.stderr)
        # Best-effort, igual que la señal form_responses_novedad original: si falla,
        # no forzamos el paso 1 a pendiente (evita falsos positivos por un fallo
        # puntual de acceso a la hoja externa del formulario), pero sí queda
        # registrado como aviso — no como lectura_fallida crítica.

    return pasos, detalle, bloqueos_conocidos_sin_cambios, nuevo_estado


def main():
    creds = get_credentials()
    sheets = build("sheets", "v4", credentials=creds)

    señales = {}
    motivos = []
    lecturas_fallidas = []

    config = read_config(sheets)
    emergency_stop = str(config.get("EMERGENCY_STOP", "")).strip().upper() == "TRUE"
    checkpoint_raw = config.get("LAST_CYCLE_CHECKPOINT_AT", "")
    checkpoint_dt = parse_iso(checkpoint_raw)

    result = {
        "checkedAt": now_iso(),
        "checkpointUsado": checkpoint_raw or None,
        "señales": señales,
        "lecturas_fallidas": lecturas_fallidas,
        "pasos_necesarios": {},
        "pasos_detalle": {},
        "bloqueos_conocidos_sin_cambios": [],
        "debe_ejecutar_pasada_completa": True,
        "nivel_pasada_recomendado": "COMPLETA",
        "motivo": "",
    }

    if emergency_stop:
        result["debe_ejecutar_pasada_completa"] = False
        result["nivel_pasada_recomendado"] = "NINGUNA"
        result["motivo"] = "EMERGENCY_STOP activo en CONFIG: no se recalculan señales, Cowork debe detenerse en su propio Paso 0."
        publish_result(sheets, result)
        return

    if checkpoint_dt is None:
        result["debe_ejecutar_pasada_completa"] = True
        result["nivel_pasada_recomendado"] = "COMPLETA"
        result["motivo"] = "No hay CONFIG.LAST_CYCLE_CHECKPOINT_AT válido: se recomienda pasada completa por seguridad."
        publish_result(sheets, result)
        return

    # Regla general para las señales "críticas" de abajo: si la lectura FALLA
    # de verdad (no si la pestaña está simplemente vacía), no asumimos "no hay
    # nada pendiente" — asumimos lo contrario (fuerza pasada completa) y lo
    # registramos en lecturas_fallidas, para no convertir un error transitorio
    # de la API de Sheets en un falso "todo tranquilo".

    # --- Señal 1: COLA_PUBLICACION_TEMPORAL_PDF ---
    try:
        cola = rows_as_dicts(sheets, "COLA_PUBLICACION_TEMPORAL_PDF")
        cola_pendiente = any(
            (row.get("estado") or "").strip() in ("PENDIENTE", "PUBLICADO")
            for row in cola
        )
    except SheetReadError as exc:
        print(str(exc), file=sys.stderr)
        lecturas_fallidas.append("COLA_PUBLICACION_TEMPORAL_PDF")
        cola_pendiente = True
    señales["cola_publicacion_pdf_pendiente"] = cola_pendiente
    if cola_pendiente:
        motivos.append("hay filas pendientes en COLA_PUBLICACION_TEMPORAL_PDF" if "COLA_PUBLICACION_TEMPORAL_PDF" not in lecturas_fallidas else "no se pudo leer COLA_PUBLICACION_TEMPORAL_PDF (se asume pendiente por seguridad)")

    # --- Señal 2: LOG_ENVIO_IA ---
    try:
        log_ia = rows_as_dicts(sheets, "LOG_ENVIO_IA")
        log_ia_pendiente = any(
            (row.get("estado_conversacion") or "").strip() == "PENDIENTE_RESPUESTA"
            for row in log_ia
        )
    except SheetReadError as exc:
        print(str(exc), file=sys.stderr)
        lecturas_fallidas.append("LOG_ENVIO_IA")
        log_ia_pendiente = True
    señales["log_envio_ia_pendiente"] = log_ia_pendiente
    if log_ia_pendiente:
        motivos.append("hay preguntas sin responder en LOG_ENVIO_IA" if "LOG_ENVIO_IA" not in lecturas_fallidas else "no se pudo leer LOG_ENVIO_IA (se asume pendiente por seguridad)")

    # --- Señal 3: SEGUIMIENTO_ENVIOS ---
    seguimiento_rows = []
    try:
        seguimiento_rows = rows_as_dicts(sheets, "SEGUIMIENTO_ENVIOS")
        seguimiento_pendiente = any(
            (row.get("estado_final") or "").strip() in ("BORRADOR_PENDIENTE", "DISCREPANCIA")
            for row in seguimiento_rows
        )
    except SheetReadError as exc:
        print(str(exc), file=sys.stderr)
        lecturas_fallidas.append("SEGUIMIENTO_ENVIOS")
        seguimiento_pendiente = True
    señales["seguimiento_envios_pendiente"] = seguimiento_pendiente
    if seguimiento_pendiente:
        motivos.append("hay seguimiento de envíos pendiente en SEGUIMIENTO_ENVIOS" if "SEGUIMIENTO_ENVIOS" not in lecturas_fallidas else "no se pudo leer SEGUIMIENTO_ENVIOS (se asume pendiente por seguridad)")

    # --- Señal 4: SOLICITUDES.updated_at (lectura ligera, solo la columna) ---
    try:
        solicitudes_header = get_values(sheets, "SOLICITUDES!A1:ZZ1")
        solicitudes_novedad = False
        if solicitudes_header:
            header = solicitudes_header[0]
            if "updated_at" in header:
                col_idx = header.index("updated_at")
                col_letter = _col_letter(col_idx)
                col_values = get_values(sheets, f"SOLICITUDES!{col_letter}2:{col_letter}")
                if col_values:
                    max_dt = None
                    for row in col_values:
                        dt = parse_iso(row[0]) if row else None
                        if dt and (max_dt is None or dt > max_dt):
                            max_dt = dt
                    if max_dt and max_dt > checkpoint_dt:
                        solicitudes_novedad = True
    except Exception as exc:
        print(f"no se pudo leer SOLICITUDES.updated_at: {exc}", file=sys.stderr)
        lecturas_fallidas.append("SOLICITUDES")
        solicitudes_novedad = True
    señales["solicitudes_updated_at_novedad"] = solicitudes_novedad
    if solicitudes_novedad:
        motivos.append("SOLICITUDES tiene expedientes con updated_at más reciente que el checkpoint" if "SOLICITUDES" not in lecturas_fallidas else "no se pudo leer SOLICITUDES.updated_at (se asume pendiente por seguridad)")

    # --- Señal 5: formulario de ingesta (best-effort, puede no tener acceso) ---
    form_novedad = False
    try:
        form_spreadsheet_id = config.get("FORM_RESPONSES_SPREADSHEET_ID")
        form_sheet_name = config.get("FORM_RESPONSES_SHEET_NAME")
        if form_spreadsheet_id and form_sheet_name:
            resp = sheets.spreadsheets().values().get(
                spreadsheetId=form_spreadsheet_id,
                range=f"{form_sheet_name}!A2:A",
            ).execute()
            values = resp.get("values", [])
            if values:
                last_ts = parse_iso(values[-1][0]) if values[-1] else None
                if last_ts and last_ts > checkpoint_dt:
                    form_novedad = True
    except Exception as exc:
        print(f"Aviso: no se pudo comprobar la hoja de respuestas del formulario: {exc}", file=sys.stderr)
    señales["form_responses_novedad"] = form_novedad
    if form_novedad:
        motivos.append("hay respuestas nuevas en el formulario de ingesta")

    # --- Señal 6: meta.json de Notion (generado por sync-notion.mjs en este mismo repo) ---
    notion_novedad = False
    try:
        with open(META_JSON_PATH, "r", encoding="utf-8") as f:
            meta = json.load(f)
        notion_ts = parse_iso(meta.get("lastContentChangeAt") or meta.get("updatedAt"))
        if notion_ts and notion_ts > checkpoint_dt:
            notion_novedad = True
    except Exception as exc:
        print(f"Aviso: no se pudo leer {META_JSON_PATH}: {exc}", file=sys.stderr)
    señales["notion_content_novedad"] = notion_novedad
    if notion_novedad:
        motivos.append("Notion tiene contenido más reciente que el checkpoint (lastContentChangeAt)")

    # --- Pasos concretos (1,2,3,5,6,7) + proxy de Paso 4, deterministas ---
    # FIX B (2026-07-13): previous_state es el snapshot {request_id: updated_at} de la
    # corrida anterior (ver STATE_FILE) — permite distinguir un bloqueo estructural ya
    # diagnosticado que sigue exactamente igual, de un cambio real que sí debe re-evaluarse.
    previous_state = load_state()
    pasos_necesarios, pasos_detalle, bloqueos_conocidos_sin_cambios, nuevo_estado = calcular_pasos_necesarios(
        sheets, config, checkpoint_dt, seguimiento_rows, lecturas_fallidas, previous_state
    )
    result["pasos_necesarios"] = pasos_necesarios
    result["pasos_detalle"] = pasos_detalle
    result["bloqueos_conocidos_sin_cambios"] = bloqueos_conocidos_sin_cambios
    if nuevo_estado:
        save_state(nuevo_estado)

    debe_ejecutar = any(señales.values()) or any(pasos_necesarios.values())
    nivel = calcular_nivel_pasada(señales, lecturas_fallidas, pasos_necesarios)
    result["debe_ejecutar_pasada_completa"] = debe_ejecutar  # retrocompatibilidad / lectura humana
    result["nivel_pasada_recomendado"] = nivel

    pasos_motivo = "; ".join(f"paso {k}: {v}" for k, v in pasos_detalle.items())
    extra_motivos = [pasos_motivo] if pasos_motivo else []
    if bloqueos_conocidos_sin_cambios:
        extra_motivos.append(
            "bloqueos estructurales ya conocidos, sin cambios desde la corrida anterior "
            "(no fuerzan pasada completa): " + ", ".join(bloqueos_conocidos_sin_cambios)
        )
    motivos_completo = "; ".join(motivos + extra_motivos)
    if nivel == "PARCIAL_SEGUIMIENTO":
        result["motivo"] = "solo seguimiento de envíos pendiente (" + "; ".join(motivos) + ") — basta con el Paso 9, no hace falta pasada completa"
    else:
        result["motivo"] = motivos_completo if motivos_completo else "sin novedades en ninguna señal ni paso comprobado"

    publish_result(sheets, result)


def _col_letter(idx):
    """Convierte un índice 0-based de columna a letra de Sheets (0->A, 25->Z, 26->AA...)."""
    letter = ""
    idx += 1
    while idx > 0:
        idx, rem = divmod(idx - 1, 26)
        letter = chr(65 + rem) + letter
    return letter


def git(*args, check=True):
    result = subprocess.run(["git", *args], capture_output=True, text=True)
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.stderr.strip():
        print(result.stderr.strip(), file=sys.stderr)
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} fallo (codigo {result.returncode}): {result.stderr.strip()}")
    return result


def git_commit_and_push_with_retry(max_attempts=5):
    """Mismo mecanismo que publish_temp_pdfs.py: otro workflow de este repo (sync de
    Notion, publish_temp_pdfs) puede commitear a la vez, así que reintenta con
    fetch+rebase en vez de fallar directamente por non-fast-forward."""
    git("config", "user.name", "solaris-status-bot")
    git("config", "user.email", "actions@users.noreply.github.com")
    git("checkout", "-B", "main")
    # CAMBIO 2026-07-13: también se commitea STATE_FILE (snapshot para el FIX B de
    # calcular_pasos_necesarios) si existe — "git add" con un path que no existe fallaría,
    # pero para cuando llegamos aquí siempre se ha llamado a save_state() antes.
    add_args = [OUTPUT_PATH]
    if os.path.exists(STATE_FILE):
        add_args.append(STATE_FILE)
    git("add", *add_args)
    commit_result = git("commit", "-m", "Actualizar pipeline_status.json", check=False)
    if commit_result.returncode != 0 and "nothing to commit" not in commit_result.stdout:
        raise RuntimeError(f"git commit fallo: {commit_result.stderr.strip()}")

    for attempt in range(1, max_attempts + 1):
        push_result = git("push", "origin", "HEAD:main", check=False)
        if push_result.returncode == 0:
            print(f"git push OK (intento {attempt}/{max_attempts}).")
            return
        print(f"git push fallo (intento {attempt}/{max_attempts}): {push_result.stderr.strip()}", file=sys.stderr)
        if attempt == max_attempts:
            raise RuntimeError(f"git push fallo tras {max_attempts} intentos: {push_result.stderr.strip()}")
        time.sleep(2 + attempt)
        git("fetch", "origin", "main")
        rebase_result = git("rebase", "origin/main", check=False)
        if rebase_result.returncode != 0:
            git("rebase", "--abort", check=False)
            raise RuntimeError(f"git rebase fallo: {rebase_result.stderr.strip()}")


def write_and_push(result):
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=None, separators=(",", ":"))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    git_commit_and_push_with_retry()


if __name__ == "__main__":
    main()
