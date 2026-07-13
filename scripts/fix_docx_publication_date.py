#!/usr/bin/env python3
"""
fix_docx_publication_date.py — GitHub Action del pipeline documental Solaris
(UVigo Aerotech).

Por qué existe: Cowork no puede corregir el campo "Fecha de publicación: --/--/----"
en los DOCX grandes (~4.6MB, caso VAXBFDH y similares) porque su conector de Drive
funciona a base de herramientas envueltas en texto: para editar un archivo tiene que
mover su contenido completo en base64 dentro de un único mensaje, y eso excede tanto
el límite práctico de generación de un turno como el aislamiento de red de su sandbox
(sin acceso general a internet, solo un proxy con lista blanca para pip/npm). Ya se
probó exhaustivamente: conector nativo de Drive, conector Pipedream, conversión
server-side sin re-subida, y un túnel propio — los cuatro caminos chocan con ese
mismo límite estructural. Un GitHub Action sí puede: tiene internet completo y la
misma service account que ya usa check_pipeline_status.py, con permiso de Editor
sobre las carpetas relevantes de Drive.

Qué hace, para cada fila de SOLICITUDES con approved=TRUE, closed=FALSE, y last_error
con una marca de bloqueo estructural ya diagnosticada (ver STRUCTURAL_BLOCK_MARKERS,
las mismas que usa el FIX B de check_pipeline_status.py):
  1. Descarga el DOCX real (drive_docx_file_id, o source_drive_file_id si la primera
     columna está vacía) vía Drive API.
  2. Reemplaza "Fecha de publicación: --/--/----" por la fecha de hoy (DD/MM/AAAA,
     huso horario Europe/Madrid) en el footer correspondiente, editando directamente
     el XML dentro del .docx (zip), sin tocar nada más del documento.
  3. Sube el contenido corregido de vuelta AL MISMO fileId (files().update con
     media_body) — mismo enlace y permisos, no crea un archivo nuevo.
  4. Convierte el DOCX corregido a PDF con LibreOffice headless (instalado en el
     runner vía el workflow YAML).
  5. Sube el PDF nuevo a la carpeta del expediente (drive_folder_id).
  6. Actualiza last_error (a una nota RESUELTO_AUTOMATICO_...) y updated_at en
     SOLICITUDES, para que:
       - check_pipeline_status.py (FIX B) deje de tratar esta fila como "bloqueo
         conocido sin cambios" en la siguiente corrida (porque last_error ya no
         contiene la marca original, y updated_at cambió) — vuelve a evaluarse
         desde cero, y
       - el siguiente ciclo de Cowork (Paso 5, 05_publicar_aprobado) recoja el PDF
         ya existente en la carpeta del expediente y siga con el embebido en Notion
         normalmente, sin más intervención manual.

Requisitos del runner (ver workflow YAML fix-docx-publication-date.yml):
  - pip install google-api-python-client google-auth python-docx
  - apt-get install -y libreoffice (conversión DOCX -> PDF headless)
  - Misma variable de entorno GDRIVE_SA_KEY (JSON de la service account, texto plano
    o base64) que ya usa check_pipeline_status.py — mismo parseo, misma cuenta.

NO se toca ningún otro campo del documento ni de la fila más allá de lo descrito
arriba. Nunca se edita un PDF directamente (no aplica aquí: el DOCX es la fuente,
el PDF se regenera desde cero con LibreOffice). Este script NUNCA borra nada.
"""

import base64
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone

try:
    from zoneinfo import ZoneInfo
    _MADRID_TZ = ZoneInfo("Europe/Madrid")
except Exception:  # pragma: no cover - fallback si el runner no tiene tzdata
    _MADRID_TZ = None

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

# --------------------------------------------------------------------------------------
# Configuración — mismos valores/convenciones que check_pipeline_status.py
# --------------------------------------------------------------------------------------

SPREADSHEET_ID = "1EL5luWUYD5_3onxaDUSHmexzzQZEkPNLW1Y4QzzRg20"
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Mismas marcas que STRUCTURAL_BLOCK_MARKERS en check_pipeline_status.py (FIX B) —
# deliberadamente duplicadas aquí en vez de importadas: son dos workflows/Actions
# independientes en el mismo repo, y mantenerlas como constantes locales evita
# acoplar el import a la ruta exacta del otro script en el runner.
STRUCTURAL_BLOCK_MARKERS = ("PENDIENTE_MANUAL_CONFIRMADO", "MANUAL_INTERVENTION")

PLACEHOLDER = "Fecha de publicación: --/--/----"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PDF_MIME = "application/pdf"

SOLICITUDES_SHEET = "SOLICITUDES"


# --------------------------------------------------------------------------------------
# Auth — idéntico a get_credentials() de check_pipeline_status.py, solo cambian los
# SCOPES (aquí necesitamos Drive de escritura completo, no solo Sheets).
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


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def today_es():
    """Fecha de hoy en formato DD/MM/AAAA, huso horario Europe/Madrid (mismo huso que
    usan Daniel/José) — evita un desfase de un día si el Action corre cerca de
    medianoche UTC. Si el runner no tiene tzdata disponible (raro en Ubuntu, pero por
    si acaso), cae a UTC+2 fijo como aproximación razonable (CEST, horario de verano)."""
    if _MADRID_TZ is not None:
        return datetime.now(_MADRID_TZ).strftime("%d/%m/%Y")
    from datetime import timedelta
    return (datetime.now(timezone.utc) + timedelta(hours=2)).strftime("%d/%m/%Y")


def es_true(value):
    """Mismo convenio que check_pipeline_status.py: la celda dice literalmente
    'TRUE'/'FALSE' (o vacía = FALSE)."""
    return str(value or "").strip().upper() == "TRUE"


def tiene_marca_bloqueo_estructural(last_error):
    if not last_error:
        return False
    texto = str(last_error)
    return any(marker in texto for marker in STRUCTURAL_BLOCK_MARKERS)


def col_letter(idx):
    """Convierte un índice 0-based de columna a letra de Sheets (0->A, 25->Z, 26->AA...).
    Idéntica a _col_letter en check_pipeline_status.py."""
    letter = ""
    idx += 1
    while idx > 0:
        idx, rem = divmod(idx - 1, 26)
        letter = chr(65 + rem) + letter
    return letter


# --------------------------------------------------------------------------------------
# Sheets — lectura/escritura de SOLICITUDES vía la API cruda (mismo estilo que
# check_pipeline_status.py: sin gspread, para no añadir una dependencia nueva).
# --------------------------------------------------------------------------------------

def leer_solicitudes(sheets):
    """Devuelve (header: list[str], filas: list[dict]) — cada fila incluye además
    la clave interna "_row_number" (1-based, tal como la espera la Sheets API) para
    poder escribir de vuelta en la fila exacta sin tener que rebuscarla otra vez."""
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


def actualizar_last_error_y_updated_at(sheets, header, row_number, nuevo_last_error, nuevo_updated_at):
    """Escribe last_error y updated_at de una fila concreta en una sola llamada
    (batchUpdate), localizando las columnas dinámicamente por cabecera — igual que
    upsert_config_value en check_pipeline_status.py, nunca por posición fija."""
    idx_last_error = header.index("last_error")
    idx_updated_at = header.index("updated_at")
    data = [
        {
            "range": f"{SOLICITUDES_SHEET}!{col_letter(idx_last_error)}{row_number}",
            "values": [[nuevo_last_error]],
        },
        {
            "range": f"{SOLICITUDES_SHEET}!{col_letter(idx_updated_at)}{row_number}",
            "values": [[nuevo_updated_at]],
        },
    ]
    sheets.spreadsheets().values().batchUpdate(
        spreadsheetId=SPREADSHEET_ID,
        body={"valueInputOption": "RAW", "data": data},
    ).execute()


# --------------------------------------------------------------------------------------
# Drive — descarga, parcheo del DOCX, conversión a PDF, subida.
# --------------------------------------------------------------------------------------

def download_file(drive, file_id):
    request = drive.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buf.getvalue()


def patch_docx_publication_date(docx_bytes, new_date):
    """Reemplaza el placeholder de fecha de publicación dentro del .docx, editando
    directamente el XML del footer correspondiente. Devuelve (nuevo_docx_bytes, cambiado).

    Busca el placeholder en CUALQUIER footer*.xml del documento (footer1/2/3.xml —
    Word numera los footers según si hay portada distinta, páginas pares/impares,
    etc.), por si la plantilla exacta varía de un expediente a otro. No toca ningún
    otro contenido del documento."""
    zin = zipfile.ZipFile(io.BytesIO(docx_bytes), "r")
    changed = False
    out_buf = io.BytesIO()

    with zipfile.ZipFile(out_buf, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if re.match(r"word/footer\d*\.xml$", item.filename):
                text = data.decode("utf-8")
                if PLACEHOLDER in text:
                    new_text = "Fecha de publicación: " + new_date
                    text = text.replace(PLACEHOLDER, new_text)
                    data = text.encode("utf-8")
                    changed = True
            zout.writestr(item, data)

    return out_buf.getvalue(), changed


def convert_docx_to_pdf(docx_bytes, workdir):
    docx_path = os.path.join(workdir, "input.docx")
    with open(docx_path, "wb") as f:
        f.write(docx_bytes)

    result = subprocess.run(
        ["soffice", "--headless", "--convert-to", "pdf", "--outdir", workdir, docx_path],
        capture_output=True,
        text=True,
        timeout=180,
    )
    if result.returncode != 0:
        raise RuntimeError(f"LibreOffice fallo: {result.stdout}\n{result.stderr}")

    pdf_path = os.path.join(workdir, "input.pdf")
    with open(pdf_path, "rb") as f:
        return f.read()


def update_drive_file_content(drive, file_id, new_bytes, mime_type):
    """Sube new_bytes AL MISMO fileId (files().update) — nunca crea un archivo nuevo,
    conserva enlace y permisos existentes."""
    media = MediaIoBaseUpload(io.BytesIO(new_bytes), mimetype=mime_type, resumable=True)
    drive.files().update(fileId=file_id, media_body=media).execute()


def upload_new_file(drive, parent_id, filename, content_bytes, mime_type):
    file_metadata = {"name": filename, "parents": [parent_id]}
    media = MediaIoBaseUpload(io.BytesIO(content_bytes), mimetype=mime_type, resumable=True)
    created = drive.files().create(body=file_metadata, media_body=media, fields="id").execute()
    return created["id"]


# --------------------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------------------

def main():
    creds = get_credentials()
    sheets = build("sheets", "v4", credentials=creds)
    drive = build("drive", "v3", credentials=creds)

    header, filas = leer_solicitudes(sheets)
    if not filas:
        print("SOLICITUDES vacío o no se pudo leer; nada que hacer.")
        return

    candidatas = [
        r for r in filas
        if es_true(r.get("approved"))
        and not es_true(r.get("closed"))
        and tiene_marca_bloqueo_estructural(r.get("last_error", ""))
    ]

    if not candidatas:
        print("No hay expedientes aprobados-no-cerrados con bloqueo estructural conocido. Nada que hacer.")
        return

    fixed = []
    skipped = []
    errors = []

    for row in candidatas:
        request_id = row.get("request_id")
        if not request_id:
            continue

        docx_file_id = row.get("drive_docx_file_id") or row.get("source_drive_file_id")
        folder_id = row.get("drive_folder_id")
        reference = row.get("reference") or request_id

        if not docx_file_id or not folder_id:
            skipped.append((request_id, "sin drive_docx_file_id/source_drive_file_id o drive_folder_id"))
            continue

        try:
            print(f"[{request_id}] descargando {docx_file_id} ...")
            original_bytes = download_file(drive, docx_file_id)

            fecha_hoy = today_es()
            new_bytes, changed = patch_docx_publication_date(original_bytes, fecha_hoy)
            if not changed:
                skipped.append((request_id, "placeholder de fecha no encontrado en ningún footer (¿ya corregido a mano?)"))
                continue

            print(f"[{request_id}] subiendo DOCX corregido al mismo fileId ({docx_file_id}) ...")
            update_drive_file_content(drive, docx_file_id, new_bytes, DOCX_MIME)

            with tempfile.TemporaryDirectory() as workdir:
                print(f"[{request_id}] convirtiendo a PDF con LibreOffice ...")
                pdf_bytes = convert_docx_to_pdf(new_bytes, workdir)

            pdf_filename = f"{reference}.pdf"
            print(f"[{request_id}] subiendo PDF nuevo a la carpeta del expediente ({folder_id}) ...")
            pdf_file_id = upload_new_file(drive, folder_id, pdf_filename, pdf_bytes, PDF_MIME)

            resolved_note = (
                f"RESUELTO_AUTOMATICO_{now_iso()}_via_github_action_fix_docx_publication_date: "
                f"fecha de publicacion corregida ({fecha_hoy}), DOCX actualizado en el mismo "
                f"fileId ({docx_file_id}), PDF generado y subido (fileId {pdf_file_id})."
            )
            actualizar_last_error_y_updated_at(sheets, header, row["_row_number"], resolved_note, now_iso())

            fixed.append((request_id, pdf_file_id))
            print(f"[{request_id}] OK.")

        except Exception as exc:  # noqa: BLE001 — queremos capturar y seguir con el resto
            errors.append((request_id, str(exc)))
            print(f"[{request_id}] ERROR: {exc}", file=sys.stderr)

    print("\n--- Resumen ---")
    print(f"Corregidos: {fixed}")
    print(f"Omitidos: {skipped}")
    print(f"Errores: {errors}")

    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
