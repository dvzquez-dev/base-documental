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

Limitación conocida: no puede comprobar Gmail (envíos reales de correo),
porque eso requiere el conector OAuth de Gmail que solo tiene Cowork, no una
service account. Ese chequeo se sigue haciendo solo durante la pasada
completa (Paso 9, seguimiento de envíos). Las colas relacionadas con correo
que SÍ son Sheets (SEGUIMIENTO_ENVIOS, LOG_ENVIO_IA) sí están cubiertas aquí.

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
STALE_ACTION_MINUTES = 20  # umbral que usará Cowork para desconfiar de este JSON si está viejo

# Señales que, si son las ÚNICAS activas, solo requieren el Paso 9 (seguimiento de
# envíos de Gmail) en vez de la pasada completa del pipeline. Añadido 2026-07-09:
# antes Cowork tenía que releer el objeto "señales" cada ciclo y aplicar esta regla
# el mismo en lenguaje natural (frágil, sin memoria entre ciclos); ahora el propio
# script decide el nivel exacto y Cowork solo lee un campo, sin reinterpretar nada.
SEÑALES_SOLO_SEGUIMIENTO = {"seguimiento_envios_pendiente", "log_envio_ia_pendiente"}


def calcular_nivel_pasada(señales, lecturas_fallidas):
    """Devuelve 'NINGUNA', 'PARCIAL_SEGUIMIENTO' o 'COMPLETA'.

    Reglas (en este orden):
    1. Si alguna lectura falló de verdad (no sabemos su valor real), nunca nos
       fiamos de un patrón que parezca "solo seguimiento" — forzamos COMPLETA.
    2. Si ninguna señal está activa, NINGUNA (no hace falta hacer nada).
    3. Si las únicas señales activas están dentro de SEÑALES_SOLO_SEGUIMIENTO,
       PARCIAL_SEGUIMIENTO (basta con el Paso 9).
    4. Cualquier otro caso, COMPLETA.
    """
    if lecturas_fallidas:
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

    # Regla general para las 4 señales "críticas" de abajo: si la lectura FALLA
    # de verdad (no si la pestaña está simplemente vacía), no asumimos "no hay
    # nada pendiente" — asumimos lo contrario (fuerza pasada completa) y lo
    # registramos en lecturas_fallidas, para no convertir un error transitorio
    # de la API de Sheets en un falso "todo tranquilo".

    # --- Señal 1: COLA_PUBLICACION_TEMPORAL_PDF ---
    # OJO: EMBEBIDO_CONFIRMADO se excluye a propósito. Una fila en ese estado
    # ya tiene el trabajo de Cowork terminado (embebido en Notion verificado,
    # el cierre del expediente NO depende de la limpieza de Drive). Lo único
    # pendiente ahi es el propio GitHub Action reintentando mover la copia de
    # staging a la papelera, algo que puede fallar indefinidamente por la
    # politica de organizacion del Workspace (ver CONFIG.DRIVE_STAGING_CLEANUP_*)
    # y que Cowork no necesita ni puede resolver. Si se incluyera aqui,
    # cualquier fila asi dejaria debe_ejecutar_pasada_completa=true para
    # siempre, anulando el proposito entero de este chequeo rapido.
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
    try:
        seguimiento = rows_as_dicts(sheets, "SEGUIMIENTO_ENVIOS")
        seguimiento_pendiente = any(
            (row.get("estado_final") or "").strip() in ("BORRADOR_PENDIENTE", "DISCREPANCIA")
            for row in seguimiento
        )
    except SheetReadError as exc:
        print(str(exc), file=sys.stderr)
        lecturas_fallidas.append("SEGUIMIENTO_ENVIOS")
        seguimiento_pendiente = True
    señales["seguimiento_envios_pendiente"] = seguimiento_pendiente
    if seguimiento_pendiente:
        motivos.append("hay seguimiento de envíos pendiente en SEGUIMIENTO_ENVIOS" if "SEGUIMIENTO_ENVIOS" not in lecturas_fallidas else "no se pudo leer SEGUIMIENTO_ENVIOS (se asume pendiente por seguridad)")

    # --- Señal 4: SOLICITUDES.updated_at ---
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

    debe_ejecutar = any(señales.values())
    nivel = calcular_nivel_pasada(señales, lecturas_fallidas)
    result["debe_ejecutar_pasada_completa"] = debe_ejecutar  # retrocompatibilidad / lectura humana
    result["nivel_pasada_recomendado"] = nivel
    if nivel == "PARCIAL_SEGUIMIENTO":
        result["motivo"] = "solo seguimiento de envíos pendiente (" + "; ".join(motivos) + ") — basta con el Paso 9, no hace falta pasada completa"
    else:
        result["motivo"] = "; ".join(motivos) if motivos else "sin novedades en ninguna señal comprobada"

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
