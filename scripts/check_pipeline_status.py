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

Es de SOLO LECTURA sobre Sheets (scope spreadsheets.readonly) — no escribe
nada en la Sheet de control. La única escritura que hace este workflow es el
commit/push de data/pipeline_status.json a este mismo repo.

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
SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
OUTPUT_PATH = "data/pipeline_status.json"
META_JSON_PATH = "data/meta.json"  # generado por scripts/sync-notion.mjs en este mismo repo
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


def calcular_nivel_pasada(señales, lecturas_fallidas, pasos_necesarios):
    """Devuelve 'NINGUNA', 'PARCIAL_SEGUIMIENTO' o 'COMPLETA'.

    Reglas (en este orden):
    1. Si alguna lectura falló de verdad (no sabemos su valor real), nunca nos
       fiamos de un patrón que parezca "solo seguimiento" — forzamos COMPLETA.
    2. Si hay algún paso concreto (1,2,3,5,6,7) con trabajo detectado, o hay que
       verificar Gmail para el Paso 4, es COMPLETA (aunque ahora Cowork puede
       usar pasos_necesarios para leer solo esos pasos, no todos).
    3. Si ninguna señal ni ningún paso está activo, NINGUNA.
    4. Si las únicas señales activas están dentro de SEÑALES_SOLO_SEGUIMIENTO
       (y no hay ningún paso 1-7 pendiente), PARCIAL_SEGUIMIENTO.
    5. Cualquier otro caso, COMPLETA.
    """
    if lecturas_fallidas:
        return "COMPLETA"
    algun_paso_pendiente = any(pasos_necesarios.values())
    if algun_paso_pendiente:
        return "COMPLETA"
    activas = {k for k, v in señales.items() if v}
    if not activas:
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


def calcular_pasos_necesarios(sheets, config, checkpoint_dt, seguimiento_rows, lecturas_fallidas):
    """Calcula, de forma determinista y a partir del estado real en Sheets, qué
    pasos concretos del pipeline (1,2,3,5,6,7) tienen trabajo pendiente ahora
    mismo. Devuelve (pasos: dict[str,bool], detalle: dict[str,str]).

    Pasos 4 y 8 NO se calculan aquí con certeza (ver docstring del módulo):
    - Paso 4 (procesar_respuesta_revisor) depende de si un revisor ya respondió
      un hilo de Gmail. Este script solo puede aproximar "hay un borrador de
      aprobación esperando desde hace más de MIN_MINUTOS_ANTES_DE_VERIFICAR_GMAIL_PASO4
      minutos" como pista de que merece la pena que Cowork compruebe Gmail — se
      expone como pasos["4_verificar_gmail"], no como un "4" de trabajo confirmado.
    - Paso 8 (gestión de errores) no tiene condición propia: solo se dispara
      reactivamente cuando otro paso falla durante la propia pasada de Cowork.
    """
    pasos = {"1": False, "2": False, "3": False, "4_verificar_gmail": False, "5": False, "6": False, "7": False}
    detalle = {}

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
        # --- Paso 2: análisis de documento pendiente ---
        pendientes_paso2 = [r for r in solicitudes if es_true(r.get("received")) and not es_true(r.get("analyzed"))]
        if pendientes_paso2:
            pasos["2"] = True
            detalle["2"] = f"{len(pendientes_paso2)} solicitud(es) con received=TRUE y analyzed=FALSE"

        # --- Paso 3: solicitud de aprobación pendiente de crear ---
        # Candidatas: ya analizadas, sin decisión todavía (ni aprobado, ni rechazado,
        # ni cambios solicitados). De esas, solo cuenta como "pendiente de Paso 3" si
        # todavía NO existe un borrador BORRADOR_PENDIENTE de tipo solicitud_aprobacion
        # en SEGUIMIENTO_ENVIOS para su request_id (si ya existe, el Paso 3 ya se hizo;
        # lo que falta es Paso 4, no Paso 3 otra vez).
        ya_con_borrador = {
            r.get("request_id")
            for r in seguimiento_rows
            if (r.get("tipo_email") or "").strip() == "solicitud_aprobacion"
            and (r.get("estado_final") or "").strip() == "BORRADOR_PENDIENTE"
        }
        candidatas_paso3 = [
            r for r in solicitudes
            if es_true(r.get("analyzed"))
            and not es_true(r.get("approved"))
            and not es_true(r.get("rejected"))
            and not es_true(r.get("changes_requested"))
            and r.get("request_id") not in ya_con_borrador
        ]
        if candidatas_paso3:
            pasos["3"] = True
            detalle["3"] = f"{len(candidatas_paso3)} solicitud(es) analizada(s) sin decisión y sin borrador de aprobación todavía"

        # --- Paso 5: publicar aprobado pendiente ---
        pendientes_paso5 = [r for r in solicitudes if es_true(r.get("approved")) and not es_true(r.get("closed"))]
        if pendientes_paso5:
            pasos["5"] = True
            detalle["5"] = f"{len(pendientes_paso5)} solicitud(es) aprobada(s) y no cerrada(s) todavía"

        # --- Paso 6: libro de datos pendiente ---
        pendientes_paso6 = [
            r for r in solicitudes
            if es_true(r.get("approved")) and not es_true(r.get("base_database_registered"))
        ]
        if pendientes_paso6:
            pasos["6"] = True
            detalle["6"] = f"{len(pendientes_paso6)} solicitud(es) aprobada(s) sin registrar todavía en el Libro de Datos"

        # --- Paso 7: reconciliación/alertas — solo si algún recordatorio ya venció ---
        ahora = now_dt()
        vencidos = []
        for r in solicitudes:
            if es_true(r.get("approved")) and not es_true(r.get("closed")):
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

    return pasos, detalle


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
        "debe_ejecutar_pasada_completa": True,
        "nivel_pasada_recomendado": "COMPLETA",
        "motivo": "",
    }

    if emergency_stop:
        result["debe_ejecutar_pasada_completa"] = False
        result["nivel_pasada_recomendado"] = "NINGUNA"
        result["motivo"] = "EMERGENCY_STOP activo en CONFIG: no se recalculan señales, Cowork debe detenerse en su propio Paso 0."
        write_and_push(result)
        return

    if checkpoint_dt is None:
        result["debe_ejecutar_pasada_completa"] = True
        result["nivel_pasada_recomendado"] = "COMPLETA"
        result["motivo"] = "No hay CONFIG.LAST_CYCLE_CHECKPOINT_AT válido: se recomienda pasada completa por seguridad."
        write_and_push(result)
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
    pasos_necesarios, pasos_detalle = calcular_pasos_necesarios(
        sheets, config, checkpoint_dt, seguimiento_rows, lecturas_fallidas
    )
    result["pasos_necesarios"] = pasos_necesarios
    result["pasos_detalle"] = pasos_detalle

    debe_ejecutar = any(señales.values()) or any(pasos_necesarios.values())
    nivel = calcular_nivel_pasada(señales, lecturas_fallidas, pasos_necesarios)
    result["debe_ejecutar_pasada_completa"] = debe_ejecutar  # retrocompatibilidad / lectura humana
    result["nivel_pasada_recomendado"] = nivel

    pasos_motivo = "; ".join(f"paso {k}: {v}" for k, v in pasos_detalle.items())
    motivos_completo = "; ".join(motivos + ([pasos_motivo] if pasos_motivo else []))
    if nivel == "PARCIAL_SEGUIMIENTO":
        result["motivo"] = "solo seguimiento de envíos pendiente (" + "; ".join(motivos) + ") — basta con el Paso 9, no hace falta pasada completa"
    else:
        result["motivo"] = motivos_completo if motivos_completo else "sin novedades en ninguna señal ni paso comprobado"

    write_and_push(result)


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
    git("add", OUTPUT_PATH)
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
