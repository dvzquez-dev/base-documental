#!/usr/bin/env python3
"""
publish_temp_pdfs.py — Publicación temporal de PDFs de Solaris para embebido en Notion.
 
Lee la pestaña "COLA_PUBLICACION_TEMPORAL_PDF" de la Google Sheet "Solaris - Registro
documental" y:
 
  1. Para filas con estado=PENDIENTE: descarga el archivo de Drive, lo escribe en
     pdfs/<filename> de este repo, y marca la fila como PUBLICADO con la URL pública
     resultante (servida por GitHub Pages) y una fecha de expiración.
  2. Para filas con estado=EMBEBIDO_CONFIRMADO (Claude ya lo embebió en Notion con
     éxito), o estado=PUBLICADO cuya fecha_expira ya pasó: borra pdfs/<filename> del
     repo y marca la fila como EXPIRADO.
 
Pensado para ejecutarse cada 10-15 minutos vía GitHub Actions. Hace commit y push de
los cambios en pdfs/ cuando hay alguno.
 
Requiere una service account de Google con:
  - Acceso de lectura (Viewer) a la(s) carpeta(s) de Drive donde viven los PDFs de
    Solaris (compartida una sola vez por Daniel, no pública).
  - Acceso de edición (Editor) a la Google Sheet "Solaris - Registro documental".
 
Las credenciales llegan por la variable de entorno GDRIVE_SA_KEY (el JSON de la
service account, como texto o en base64).
"""
 
import base64
import io
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
 
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
 
SPREADSHEET_ID = "1EL5luWUYD5_3onxaDUSHmexzzQZEkPNLW1Y4QzzRg20"
SHEET_NAME = "COLA_PUBLICACION_TEMPORAL_PDF"
PDFS_DIR = "pdfs"
PUBLIC_BASE_URL = "https://dvzquez-dev.github.io/base-documental/pdfs"
EXPIRY_HOURS = 48
 
SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/spreadsheets",
]
 
# El orden debe coincidir exactamente con la fila de cabecera de la hoja.
COLUMNS = [
    "request_id", "drive_file_id", "filename", "fecha_solicitud",
    "estado", "fecha_publicado", "public_url", "fecha_expira", "notas",
]
 
 
def get_credentials():
    raw = os.environ.get("GDRIVE_SA_KEY", "").strip()
    if not raw:
        print(
            "ERROR: la variable de entorno GDRIVE_SA_KEY esta vacia o no existe.\n"
            "Revisa: Settings > Secrets and variables > Actions > pestana "
            "'Repository secrets' (NO 'Environment secrets', salvo que el job "
            "declare 'environment:' en el YAML) -> debe existir un secret llamado "
            "exactamente GDRIVE_SA_KEY con el JSON completo de la service account "
            "(empieza por '{' y termina por '}').",
            file=sys.stderr,
        )
        sys.exit(1)
    try:
        info = json.loads(raw)
    except json.JSONDecodeError:
        try:
            info = json.loads(base64.b64decode(raw))
        except Exception as exc:
            print(
                f"ERROR: GDRIVE_SA_KEY no es JSON valido ni base64-de-JSON valido "
                f"({exc}). Vuelve a copiar el JSON completo de la service account "
                f"sin comillas extra alrededor.",
                file=sys.stderr,
            )
            sys.exit(1)
    return service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
 
 
def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
 
 
def parse_iso(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
 
 
def read_rows(sheets):
    resp = sheets.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{SHEET_NAME}!A2:I",
    ).execute()
    values = resp.get("values", [])
    rows = []
    for i, row in enumerate(values, start=2):  # la fila 1 es la cabecera
        row = row + [""] * (len(COLUMNS) - len(row))
        rows.append({"row_number": i, **dict(zip(COLUMNS, row))})
    return rows
 
 
def write_row(sheets, row_number, updates: dict):
    data = []
    for col_name, value in updates.items():
        col_index = COLUMNS.index(col_name)
        col_letter = chr(ord("A") + col_index)
        data.append({
            "range": f"{SHEET_NAME}!{col_letter}{row_number}",
            "values": [[value]],
        })
    sheets.spreadsheets().values().batchUpdate(
        spreadsheetId=SPREADSHEET_ID,
        body={"valueInputOption": "RAW", "data": data},
    ).execute()
 
 
def download_drive_file(drive, file_id: str) -> bytes:
    request = drive.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buf.getvalue()
 
 
def git(*args):
    subprocess.run(["git", *args], check=True)
 
 
def main():
    creds = get_credentials()
    sheets = build("sheets", "v4", credentials=creds)
    drive = build("drive", "v3", credentials=creds)
 
    os.makedirs(PDFS_DIR, exist_ok=True)
    rows = read_rows(sheets)
    changed = False
    now = datetime.now(timezone.utc).astimezone()
 
    for row in rows:
        estado = row["estado"]
        filename = row["filename"]
        path = os.path.join(PDFS_DIR, filename) if filename else None
 
        if estado == "PENDIENTE":
            try:
                content = download_drive_file(drive, row["drive_file_id"])
                with open(path, "wb") as f:
                    f.write(content)
                published_at = now_iso()
                expires_at = (now + timedelta(hours=EXPIRY_HOURS)).isoformat(timespec="seconds")
                write_row(sheets, row["row_number"], {
                    "estado": "PUBLICADO",
                    "fecha_publicado": published_at,
                    "public_url": f"{PUBLIC_BASE_URL}/{filename}",
                    "fecha_expira": expires_at,
                })
                changed = True
                print(f"Publicado: {filename}")
            except Exception as exc:
                write_row(sheets, row["row_number"], {
                    "estado": "ERROR",
                    "notas": f"Fallo al publicar: {exc}",
                })
                print(f"ERROR publicando {filename}: {exc}", file=sys.stderr)
 
        elif estado == "EMBEBIDO_CONFIRMADO":
            if path and os.path.exists(path):
                os.remove(path)
                changed = True
            write_row(sheets, row["row_number"], {"estado": "EXPIRADO"})
            print(f"Retirado (embebido confirmado): {filename}")
 
        elif estado == "PUBLICADO":
            expira = parse_iso(row["fecha_expira"])
            if expira and now >= expira:
                if path and os.path.exists(path):
                    os.remove(path)
                    changed = True
                write_row(sheets, row["row_number"], {"estado": "EXPIRADO"})
                print(f"Retirado (expirado): {filename}")
 
    if changed:
        git("config", "user.name", "solaris-pdf-bot")
        git("config", "user.email", "actions@users.noreply.github.com")
        git("add", PDFS_DIR)
        git("commit", "-m", "Publicar/retirar PDFs temporales de Solaris")
        git("push")
    else:
        print("Sin cambios.")
 
 
if __name__ == "__main__":
    main()
 
