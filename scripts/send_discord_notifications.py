#!/usr/bin/env python3
"""
send_discord_notifications.py — GitHub Action del pipeline documental Solaris
(UVigo Aerotech).

Por qué existe: hasta el 2026-07-13 el aviso de "documento publicado" pasaba por
que el revisor copiara y pegara a mano un mensaje en un GPT personalizado de
ChatGPT, que a su vez llamaba a un webhook de Discord (ver Paso 5 /
"05_publicar_aprobado", historial de versión v8). Pedido explícito de Daniel el
2026-07-13: eliminar ese paso manual y publicar en Discord de forma totalmente
automática en cuanto un expediente queda 100% publicado, llamando DIRECTAMENTE
al webhook de Discord desde este GitHub Action — sin pasar por ningún GPT ni
depender de que nadie copie/pegue nada.

Qué hace, para cada fila de SOLICITUDES con:
  - approved == TRUE
  - notion_page_created == TRUE
  - notion_pdf_embedded == TRUE
  - notion_embedding_verified == TRUE
  - drive_primary_file_verified == TRUE   (la publicación está 100% completa)
  - discord_prompt_verified != TRUE       (todavía no se avisó por Discord)

  1. Construye un embed de Discord con los datos reales de la fila (referencia,
     título, tipo documental, unidad, temporada, enlace a la página de Notion).
  2. Hace POST directo al webhook de Discord (URL en la variable de entorno
     DISCORD_WEBHOOK_URL — NUNCA hardcodeada en este archivo ni en el repo).
  3. Si Discord confirma la entrega (?wait=true, respuesta 200 con el mensaje
     creado), guarda el JSON enviado en la columna discord_notification_prompt
     (auditoría/depuración) y marca discord_prompt_verified=TRUE.
  4. Si falla, NO reintenta en bucle dentro de la misma ejecución — la fila
     simplemente se queda pendiente y se recoge en el siguiente ciclo del Action.

Nota sobre el nombre del revisor: SOLICITUDES no tiene una columna limpia de
nombre/email del revisor (reviewer_public_annotations es el texto de su decisión,
no su identidad) — a diferencia del flujo antiguo de Cowork, este Action no puede
mirar Gmail para deducirlo. Por eso el mensaje NO incluye "aprobado por <nombre>":
solo indica que el documento fue aprobado y publicado. Si en el futuro se añade
una columna con el nombre/email real del revisor, se puede incorporar aquí sin
cambiar el resto del diseño.

Requisitos del runner (ver workflow YAML send-discord-notifications.yml):
  - pip install google-api-python-client google-auth
    (la llamada a Discord usa urllib.request de la librería estándar, sin añadir
    'requests' como dependencia nueva — mismo criterio de "menos dependencias"
    que el resto de scripts de este repo).
  - Secrets: GDRIVE_SA_KEY (ya existe, mismo service account que los demás
    Actions) y DISCORD_WEBHOOK_URL (nuevo — hay que añadirlo a los secrets del
    repo; es el mismo webhook que ya usa el GPT "Discord Notifier" de Daniel).

NO se toca ningún otro campo de la fila más allá de discord_notification_prompt y
discord_prompt_verified. Este script NUNCA borra nada ni modifica Drive/Notion.
"""

import base64
import io
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

from google.oauth2 import service_account
from googleapiclient.discovery import build

# --------------------------------------------------------------------------------------
# Configuración — mismos valores/convenciones que check_pipeline_status.py y
# fix_docx_publication_date.py
# --------------------------------------------------------------------------------------

SPREADSHEET_ID = "1EL5luWUYD5_3onxaDUSHmexzzQZEkPNLW1Y4QzzRg20"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

SOLICITUDES_SHEET = "SOLICITUDES"
DISCORD_COLOR_SUCCESS = 3066993  # verde éxito

CAMPOS_PUBLICACION_COMPLETA = (
    "notion_page_created",
    "notion_pdf_embedded",
    "notion_embedding_verified",
    "drive_primary_file_verified",
)


# --------------------------------------------------------------------------------------
# Auth / utilidades — idénticas en espíritu a los otros scripts del repo.
# --------------------------------------------------------------------------------------

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


def get_webhook_url():
    url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not url:
        print("ERROR: falta la variable de entorno DISCORD_WEBHOOK_URL.", file=sys.stderr)
        sys.exit(1)
    return url


def get_avatar_url():
    """AÑADIDO 2026-07-14. Opcional: URL pública de un logo/avatar para que el
    webhook se muestre como "Solaris · Documentación" con icono en vez del icono
    genérico de un webhook. Si no se define, el mensaje se envía sin avatar_url
    (Discord usa el icono por defecto del webhook) — nunca falla por su ausencia."""
    return os.environ.get("DISCORD_AVATAR_URL", "").strip()


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def hoy_es():
    return datetime.now(timezone.utc).strftime("%d/%m/%Y")


def es_true(value):
    """Mismo convenio que el resto del pipeline: la celda dice literalmente
    'TRUE'/'FALSE' (o vacía = FALSE)."""
    return str(value or "").strip().upper() == "TRUE"


def col_letter(idx):
    """Convierte un índice 0-based de columna a letra de Sheets (0->A, 25->Z, 26->AA...).
    Idéntica a col_letter en fix_docx_publication_date.py."""
    letter = ""
    idx += 1
    while idx > 0:
        idx, rem = divmod(idx - 1, 26)
        letter = chr(65 + rem) + letter
    return letter


# --------------------------------------------------------------------------------------
# Sheets — lectura/escritura de SOLICITUDES vía la API cruda (sin gspread, mismo
# estilo que el resto del repo).
# --------------------------------------------------------------------------------------

def leer_solicitudes(sheets):
    resp = sheets.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID, range=f"{SOLICITUDES_SHEET}!A1:ZZ"
    ).execute()
    values = resp.get("values", [])
    if not values:
        return [], []
    header = [h.strip() for h in values[0]]
    filas = []
    for i, row in enumerate(values[1:], start=2):  # fila 1 = cabecera
        row = row + [""] * (len(header) - len(row))
        d = dict(zip(header, row))
        d["_row_number"] = i
        filas.append(d)
    return header, filas


def actualizar_discord_columnas(sheets, header, row_number, prompt_json, verificado):
    """Escribe discord_notification_prompt y discord_prompt_verified de una fila
    concreta en una sola llamada (batchUpdate), localizando las columnas
    dinámicamente por cabecera. Si alguna de las dos columnas no existiera en la
    hoja (no debería pasar, ya existen desde antes), se salta esa escritura en vez
    de fallar todo el ciclo."""
    data = []
    if "discord_notification_prompt" in header:
        idx = header.index("discord_notification_prompt")
        data.append({
            "range": f"{SOLICITUDES_SHEET}!{col_letter(idx)}{row_number}",
            "values": [[prompt_json]],
        })
    if "discord_prompt_verified" in header:
        idx = header.index("discord_prompt_verified")
        data.append({
            "range": f"{SOLICITUDES_SHEET}!{col_letter(idx)}{row_number}",
            "values": [["TRUE" if verificado else "FALSE"]],
        })
    if not data:
        print("AVISO: no existen las columnas discord_notification_prompt/discord_prompt_verified en SOLICITUDES; no se pudo dejar constancia.", file=sys.stderr)
        return
    sheets.spreadsheets().values().batchUpdate(
        spreadsheetId=SPREADSHEET_ID,
        body={"valueInputOption": "RAW", "data": data},
    ).execute()


# --------------------------------------------------------------------------------------
# Discord — construcción del embed y llamada al webhook.
# --------------------------------------------------------------------------------------

def _parse_tags(tags_json):
    """Convierte la columna tags_json (string JSON con una lista) en un texto
    separado por comas para el campo 'Etiquetas'. Nunca falla: si no es JSON
    válido o no es una lista, devuelve cadena vacía (el campo simplemente se
    omite del embed)."""
    if not tags_json:
        return ""
    try:
        tags = json.loads(tags_json)
    except (json.JSONDecodeError, TypeError):
        return ""
    if not isinstance(tags, list):
        return ""
    return ", ".join(str(t) for t in tags if t)


def construir_embed(row):
    """AÑADIDO/REDISEÑADO 2026-07-14 (pedido explícito de Daniel, a partir de un
    ejemplo real de formato de mensaje que quería replicar): construye el PAYLOAD
    COMPLETO del webhook (no solo el embed) — incluye username/avatar_url para que
    el mensaje se vea como viene de "Solaris · Documentación" en vez del nombre
    genérico del webhook, un resumen real (executive_summary) como descripción,
    campos Referencia/Tipo/Unidad en fila, y filas a ancho completo para Autoría,
    Etiquetas y Accesos (enlaces a Notion y a la carpeta de Drive)."""
    reference = row.get("reference") or row.get("request_id") or ""
    title_short = row.get("title_short") or ""
    document_type = row.get("document_type") or "-"
    unit_label = row.get("unit_label") or "-"
    author = row.get("author_name") or row.get("author_name_raw") or ""
    notion_url = row.get("notion_page_url") or ""
    drive_url = row.get("drive_folder_url") or ""
    etiquetas = _parse_tags(row.get("tags_json"))

    resumen = (row.get("executive_summary") or "").strip()
    if len(resumen) > 500:
        resumen = resumen[:497] + "..."

    titulo = "📄 Nuevo documento publicado"
    if title_short:
        titulo += f" · {title_short}"

    embed = {
        "title": titulo,
        "color": DISCORD_COLOR_SUCCESS,
        "timestamp": now_iso(),
        "footer": {"text": f"Solaris Rocketry Team · Banco de Documentos · Publicado el {hoy_es()}"},
    }
    if resumen:
        embed["description"] = resumen
    if notion_url:
        embed["url"] = notion_url

    fields = [
        {"name": "Referencia", "value": reference or "-", "inline": True},
        {"name": "Tipo", "value": document_type, "inline": True},
        {"name": "Unidad", "value": unit_label, "inline": True},
    ]
    if author:
        fields.append({"name": "Autoría", "value": author, "inline": False})
    if etiquetas:
        fields.append({"name": "Etiquetas", "value": etiquetas, "inline": False})

    accesos = []
    if notion_url:
        accesos.append(f"[Abrir en Notion]({notion_url})")
    if drive_url:
        accesos.append(f"[Abrir carpeta en Drive]({drive_url})")
    if accesos:
        fields.append({"name": "Accesos", "value": " · ".join(accesos), "inline": False})

    embed["fields"] = fields

    payload = {
        "username": "Solaris · Documentación",
        "embeds": [embed],
    }
    avatar_url = get_avatar_url()
    if avatar_url:
        payload["avatar_url"] = avatar_url
        embed["footer"]["icon_url"] = avatar_url

    return payload


def enviar_a_discord(webhook_url, payload):
    """POST directo al webhook de Discord, con ?wait=true para recibir de vuelta
    el mensaje creado (así podemos confirmar de verdad la entrega, no solo un
    204 vacío). Devuelve (ok: bool, detalle: str)."""
    url = webhook_url
    url += "&wait=true" if "?" in url else "?wait=true"
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as resp:
            status = resp.status
            resp_body = resp.read().decode("utf-8", errors="replace")
            if status in (200, 204):
                return True, f"HTTP {status}: {resp_body[:300]}"
            return False, f"HTTP inesperado {status}: {resp_body[:300]}"
    except urllib.error.HTTPError as exc:
        detalle = exc.read().decode("utf-8", errors="replace") if exc.fp else str(exc)
        return False, f"HTTPError {exc.code}: {detalle[:300]}"
    except urllib.error.URLError as exc:
        return False, f"URLError: {exc}"


# --------------------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------------------

def main():
    creds = get_credentials()
    webhook_url = get_webhook_url()
    sheets = build("sheets", "v4", credentials=creds)

    header, filas = leer_solicitudes(sheets)
    if not filas:
        print("SOLICITUDES vacío o no se pudo leer; nada que hacer.")
        return

    candidatas = [
        r for r in filas
        if es_true(r.get("approved"))
        and all(es_true(r.get(campo)) for campo in CAMPOS_PUBLICACION_COMPLETA)
        and not es_true(r.get("discord_prompt_verified"))
    ]

    if not candidatas:
        print("No hay expedientes 100% publicados pendientes de aviso por Discord. Nada que hacer.")
        return

    enviados = []
    errores = []

    for row in candidatas:
        request_id = row.get("request_id")
        if not request_id:
            continue

        payload = construir_embed(row)
        print(f"[{request_id}] enviando notificacion a Discord ...")
        ok, detalle = enviar_a_discord(webhook_url, payload)

        if ok:
            print(f"[{request_id}] OK: {detalle}")
            actualizar_discord_columnas(
                sheets, header, row["_row_number"],
                prompt_json=json.dumps(payload, ensure_ascii=False),
                verificado=True,
            )
            enviados.append(request_id)
        else:
            print(f"[{request_id}] ERROR: {detalle}", file=sys.stderr)
            errores.append((request_id, detalle))

    print("\n--- Resumen ---")
    print(f"Enviados: {enviados}")
    print(f"Errores: {errores}")

    if errores:
        sys.exit(1)


if __name__ == "__main__":
    main()
