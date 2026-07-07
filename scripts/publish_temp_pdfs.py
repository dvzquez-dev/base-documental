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
  - Acceso de Editor a UNA carpeta de staging dedicada en el Drive personal de
    Daniel (carpeta "STAGING_TEMP_PDF_SOLARIS", no la carpeta general del
    pipeline ni el Drive compartido de la asociación). Claude copia ahí el PDF
    real antes de encolarlo; este script lee de esa copia y, cuando el estado
    pasa a EMBEBIDO_CONFIRMADO, también la borra (por eso hace falta Editor,
    no solo Lector).
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
import time
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
    # Necesitamos escritura (no solo readonly) porque tambien borramos la
    # copia de staging en Drive una vez confirmado el embebido en Notion.
    "https://www.googleapis.com/auth/drive",
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
    """Hace commit de lo que haya en el working tree y empuja con reintentos.
 
    Otro workflow de este mismo repo (sync de Notion) commitea cada ~2 minutos
    a la misma rama, asi que un `git push` directo puede fallar por
    non-fast-forward si hay una carrera. En cada intento fallido, hacemos
    fetch + rebase sobre origin/main y reintentamos.
    """
    git("config", "user.name", "solaris-pdf-bot")
    git("config", "user.email", "actions@users.noreply.github.com")
    # Aseguramos estar en una rama real "main" (no HEAD detached) antes de tocar nada.
    git("checkout", "-B", "main")
    git("add", PDFS_DIR)
    # Si por lo que sea no hay nada que commitear (ya se resolvio en un intento
    # anterior o alguien mas lo hizo), no es un error.
    commit_result = git("commit", "-m", "Publicar/retirar PDFs temporales de Solaris", check=False)
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
            # Conflicto real de contenido (poco probable, tocamos solo pdfs/nuevos archivos).
            git("rebase", "--abort", check=False)
            raise RuntimeError(f"git rebase fallo, no se pudo resolver el conflicto automaticamente: {rebase_result.stderr.strip()}")
 
 
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
            # Tambien borramos la copia de staging en Drive (carpeta
            # STAGING_TEMP_PDF_SOLARIS): ya no hace falta, Notion tiene su
            # propia copia interna del PDF. Si esto falla, NO marcamos
            # EXPIRADO: dejamos la fila en EMBEBIDO_CONFIRMADO para que el
            # siguiente ciclo lo reintente, en vez de perder el aviso.
            drive_deleted = False
            try:
                drive.files().delete(fileId=row["drive_file_id"]).execute()
                drive_deleted = True
                print(f"Copia de staging en Drive borrada: {filename}")
            except Exception as exc:
                print(f"Aviso: no se pudo borrar la copia de staging en Drive ({filename}), se reintentara en el proximo ciclo: {exc}", file=sys.stderr)
 
            if drive_deleted:
                write_row(sheets, row["row_number"], {"estado": "EXPIRADO"})
                print(f"Retirado (embebido confirmado): {filename}")
            else:
                write_row(sheets, row["row_number"], {
                    "notas": f"Pendiente de reintento: fallo al borrar copia de staging en Drive ({now_iso()}).",
                })
 
        elif estado == "PUBLICADO":
            expira = parse_iso(row["fecha_expira"])
            if expira and now >= expira:
                if path and os.path.exists(path):
                    os.remove(path)
                    changed = True
                write_row(sheets, row["row_number"], {"estado": "EXPIRADO"})
                print(f"Retirado (expirado): {filename}")
 
    if changed:
        git_commit_and_push_with_retry()
    else:
        print("Sin cambios.")
 
 
if __name__ == "__main__":
    main()
 
