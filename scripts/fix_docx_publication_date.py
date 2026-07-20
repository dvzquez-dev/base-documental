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
  2b. AÑADIDO 2026-07-13 (pedido explícito de Daniel): además, busca en las cabeceras
     y pies de página (word/header*.xml, word/footer*.xml) cualquier texto con forma
     de referencia documental (patrón tipo "Informe_S-6009_26": palabra + "_S-" +
     dígitos + "_" + dígitos) que NO coincida con la reference realmente reservada
     para este expediente (columna reference de SOLICITUDES), y lo sustituye por la
     correcta. Esto cubre el caso de documentos reentregados/copiados de una plantilla
     u otro expediente que conservan en la cabecera una referencia antigua o de
     ejemplo. Es una detección por PATRÓN (regex), no una lista cerrada de valores
     conocidos — puede no encontrar nada si la cabecera no sigue ese formato exacto
     (mismo tipo de limitación que el placeholder de fecha: no falla, simplemente no
     encuentra nada que corregir), y en textos partidos por Word en varias runs de
     XML tras ediciones manuales previas tampoco lo detectará (limitación conocida y
     aceptada, igual que con la fecha).
  2c. AÑADIDO 2026-07-20 (causa raíz real diagnosticada tras el caso 79E115DB): el
     GATE OBLIGATORIO DE REFERENCIA de Cowork ("05_publicar_aprobado" v10) corta la
     publicación ANTES de crear la carpeta de Drive del expediente, así que un
     expediente puede llegar aquí con drive_folder_id vacío. Antes, este script
     descartaba la fila en silencio para siempre (nunca la volvía a intentar). Ahora,
     si drive_folder_id viene vacío, resuelve la carpeta-ruta del subsistema en la
     pestaña RUTAS (por unit_key + subfolder_key + reserved_id dentro de rango) y
     crea ahí mismo la subcarpeta del expediente, guardando el resultado en
     SOLICITUDES antes de seguir. Si tampoco hay una ruta activa que encaje, sigue
     sin poder hacer nada y lo reporta como omitido (igual que antes).
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

# AÑADIDO 2026-07-13 (pedido explícito de Daniel): patrón para detectar una referencia
# documental con forma "Palabra_S-NNNN_NN" (p.ej. "Informe_S-6009_26") dentro de
# cabeceras/pies, para poder sustituirla por la reference real reservada cuando el
# documento llega con una referencia antigua/de plantilla copiada de otro expediente.
#
# AMPLIADO 2026-07-20 (bug real detectado en el caso 79E115DB): el patrón original
# solo admitía DÍGITOS en el ID y el año (\d{3,5} y \d{2}), así que nunca detectaba
# un placeholder de plantilla sin rellenar del tipo "Informe_S-XXXX_XX" (letras X,
# no dígitos) — el caso más común de "referencia incorrecta o ausente" que reporta
# 02_analisis_documento. El run real de 79E115DB confirmó esto: corrigió la fecha
# pero dejó "Informe_S-XXXX_XX" intacto en las 20+ páginas del documento porque el
# regex simplemente no hacía match. Ahora el patrón admite también series de X/x en
# vez de dígitos en cualquiera de las dos partes, para cubrir ambos casos (referencia
# de OTRO expediente copiada por error, Y placeholder de plantilla sin rellenar) con
# la misma lógica de sustitución de más abajo (cualquier match que no sea ya igual a
# correct_reference se sustituye).
REFERENCE_PATTERN = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]+_S-(?:\d{3,5}|[Xx]{3,5})_(?:\d{2}|[Xx]{2})")

SOLICITUDES_SHEET = "SOLICITUDES"

# AÑADIDO 2026-07-20: pestaña de rutas por subsistema, usada solo como fallback
# cuando drive_folder_id viene vacío (ver leer_rutas / resolver_carpeta_ruta).
RUTAS_SHEET = "RUTAS"


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


# AÑADIDO 2026-07-20 — lectura de RUTAS y resolución/creación de la carpeta del
# expediente cuando drive_folder_id viene vacío (ver punto 2c del docstring).
# --------------------------------------------------------------------------------------

def leer_rutas(sheets):
    """Devuelve la lista de filas de la pestaña RUTAS como dicts (columnas: unit_key,
    subfolder_key, label, range_start, range_end, drive_folder_id, active)."""
    resp = sheets.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID, range=f"{RUTAS_SHEET}!A1:G"
    ).execute()
    values = resp.get("values", [])
    if not values:
        return []
    header = [h.strip() for h in values[0]]
    filas = []
    for row in values[1:]:
        row = row + [""] * (len(header) - len(row))
        filas.append(dict(zip(header, row)))
    return filas


def resolver_carpeta_ruta(rutas, unit_key, subfolder_key, reserved_id):
    """Busca en RUTAS la fila activa cuyo unit_key+subfolder_key coincida y cuyo
    rango [range_start, range_end] contenga reserved_id. Devuelve el drive_folder_id
    de esa ruta (la carpeta PADRE del subsistema, no la del expediente concreto), o
    None si no hay ninguna coincidencia activa."""
    try:
        rid = int(reserved_id)
    except (TypeError, ValueError):
        return None
    for r in rutas:
        if r.get("unit_key") == unit_key and r.get("subfolder_key") == subfolder_key and es_true(r.get("active")):
            try:
                start, end = int(r.get("range_start")), int(r.get("range_end"))
            except (TypeError, ValueError):
                continue
            if start <= rid <= end:
                return r.get("drive_folder_id") or None
    return None


def crear_carpeta_expediente(drive, parent_id, nombre):
    """Crea una carpeta nueva (nombre = reference del expediente, p.ej.
    'Informe_S-2011_26') dentro de la carpeta-ruta del subsistema. Devuelve el
    fileId de la carpeta recién creada."""
    metadata = {
        "name": nombre,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id],
    }
    created = drive.files().create(body=metadata, fields="id", supportsAllDrives=True).execute()
    return created["id"]


def actualizar_folder_id(sheets, header, row_number, folder_id, folder_url):
    """Escribe drive_folder_id y drive_folder_url de una fila concreta, igual estilo
    que actualizar_last_error_y_updated_at. No toca drive_folder_created: esa la
    decide 05_publicar_aprobado cuando el resto de la publicación esté completa."""
    idx_folder_id = header.index("drive_folder_id")
    idx_folder_url = header.index("drive_folder_url")
    data = [
        {
            "range": f"{SOLICITUDES_SHEET}!{col_letter(idx_folder_id)}{row_number}",
            "values": [[folder_id]],
        },
        {
            "range": f"{SOLICITUDES_SHEET}!{col_letter(idx_folder_url)}{row_number}",
            "values": [[folder_url]],
        },
    ]
    sheets.spreadsheets().values().batchUpdate(
        spreadsheetId=SPREADSHEET_ID,
        body={"valueInputOption": "RAW", "data": data},
    ).execute()


# --------------------------------------------------------------------------------------
# Drive — descarga, parcheo del DOCX, conversión a PDF, subida.
#
# IMPORTANTE (2026-07-13, tras varias ejecuciones reales fallando con 404 solo en
# escritura pese a que la lectura funcionaba y el rol ya era Gestor de contenido):
# todo el contenido de este pipeline vive dentro de una Unidad Compartida de Drive.
# La API de Drive v3 exige el parámetro supportsAllDrives=True en CUALQUIER llamada
# que toque contenido de una Unidad Compartida para operaciones de escritura
# (update/create) — sin él, la API devuelve 404 "File not found" en vez de un error
# más claro, incluso con permisos correctos. Las lecturas (get_media) toleraban su
# ausencia en las pruebas reales, pero se añade también por consistencia y para
# evitar el mismo problema si algún día se lee un archivo directamente dentro de la
# Unidad Compartida sin pasar por una carpeta ya visitada.
# --------------------------------------------------------------------------------------

def download_file(drive, file_id):
    request = drive.files().get_media(fileId=file_id, supportsAllDrives=True)
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


def patch_docx_reference(docx_bytes, correct_reference):
    """AÑADIDO 2026-07-13. Busca en CUALQUIER header*.xml/footer*.xml del documento
    texto con forma de referencia documental (REFERENCE_PATTERN) que no coincida con
    correct_reference, y lo sustituye. Devuelve (nuevo_docx_bytes, cambiado,
    referencias_incorrectas_encontradas). No toca el cuerpo del documento ni ningún
    otro contenido. Detección por patrón, no por lista cerrada: si la cabecera no
    sigue ese formato exacto, o el texto está partido en varias runs de XML por
    ediciones previas de Word, simplemente no encontrará nada que corregir (mismo
    tipo de limitación ya conocida y aceptada para el placeholder de fecha)."""
    zin = zipfile.ZipFile(io.BytesIO(docx_bytes), "r")
    changed = False
    encontradas = set()
    out_buf = io.BytesIO()

    def _reemplazar(match):
        nonlocal changed
        texto_encontrado = match.group(0)
        if texto_encontrado == correct_reference:
            return texto_encontrado
        encontradas.add(texto_encontrado)
        changed = True
        return correct_reference

    with zipfile.ZipFile(out_buf, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if re.match(r"word/(header|footer)\d*\.xml$", item.filename):
                text = data.decode("utf-8")
                new_text = REFERENCE_PATTERN.sub(_reemplazar, text)
                if new_text != text:
                    data = new_text.encode("utf-8")
            zout.writestr(item, data)

    return out_buf.getvalue(), changed, sorted(encontradas)


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
    drive.files().update(fileId=file_id, media_body=media, supportsAllDrives=True).execute()


def upload_new_file(drive, parent_id, filename, content_bytes, mime_type):
    file_metadata = {"name": filename, "parents": [parent_id]}
    media = MediaIoBaseUpload(io.BytesIO(content_bytes), mimetype=mime_type, resumable=True)
    created = drive.files().create(body=file_metadata, media_body=media, fields="id", supportsAllDrives=True).execute()
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

    # AÑADIDO 2026-07-20: se lee una sola vez, se usa como fallback si drive_folder_id
    # viene vacío en alguna candidata (ver resolver_carpeta_ruta más abajo).
    rutas = leer_rutas(sheets)

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

        if not docx_file_id:
            skipped.append((request_id, "sin drive_docx_file_id/source_drive_file_id"))
            continue

        if not folder_id:
            # AÑADIDO 2026-07-20 (causa raíz real del caso 79E115DB): antes esto
            # descartaba la fila para siempre. Ahora se intenta resolver/crear la
            # carpeta a partir de RUTAS antes de rendirse.
            parent_id = resolver_carpeta_ruta(rutas, row.get("unit_key"), row.get("subfolder_key"), row.get("reserved_id"))
            if not parent_id:
                skipped.append((request_id, "sin drive_folder_id y no se encontró ruta activa en RUTAS"))
                continue
            try:
                folder_id = crear_carpeta_expediente(drive, parent_id, reference)
                folder_url = f"https://drive.google.com/drive/folders/{folder_id}"
                actualizar_folder_id(sheets, header, row["_row_number"], folder_id, folder_url)
                print(f"[{request_id}] drive_folder_id vacío -> carpeta creada ({folder_id}) y guardada en SOLICITUDES.")
            except Exception as exc:  # noqa: BLE001
                errors.append((request_id, f"fallo creando carpeta de expediente: {exc}"))
                print(f"[{request_id}] ERROR creando carpeta: {exc}", file=sys.stderr)
                continue

        try:
            print(f"[{request_id}] descargando {docx_file_id} ...")
            original_bytes = download_file(drive, docx_file_id)

            fecha_hoy = today_es()
            fecha_bytes, changed_fecha = patch_docx_publication_date(original_bytes, fecha_hoy)

            # AÑADIDO 2026-07-13 (pedido explícito de Daniel): además de la fecha,
            # corrige también cualquier referencia documental equivocada en cabecera/
            # pie (p.ej. un DOCX reentregado que conserva la referencia de una
            # plantilla u otro expediente en vez de la reservada de verdad). Se aplica
            # sobre el resultado del parcheo de fecha (encadenado, no en paralelo)
            # para que ambas correcciones convivan en el mismo DOCX final.
            ref_bytes, changed_ref, referencias_incorrectas = patch_docx_reference(fecha_bytes, reference)
            new_bytes = ref_bytes
            changed = changed_fecha or changed_ref

            # IMPORTANTE (corregido 2026-07-13, tras primeras ejecuciones reales en Actions):
            # NO saltar el expediente solo porque este DOCX en concreto no tenga el
            # placeholder de fecha (algunas plantillas, p.ej. Informes de Subsistema, no
            # tienen ese campo en absoluto). El bloqueo real que motivó marcar la fila con
            # una marca estructural puede ser otra cosa (p.ej. que Cowork no pudo generar/
            # subir el PDF por límite de tamaño de sus propias herramientas) — y ESO sí lo
            # puede resolver este Action sin depender de que exista el placeholder. Por eso
            # siempre se continúa hasta generar y subir el PDF; solo se sube el DOCX de
            # vuelta si de verdad se modificó algo (fecha y/o referencia).
            notas_parciales = []
            if changed_fecha:
                notas_parciales.append(f"fecha de publicacion corregida ({fecha_hoy})")
            else:
                notas_parciales.append("sin campo de fecha de publicacion que corregir")
            if changed_ref:
                notas_parciales.append(
                    f"referencia corregida en cabecera/pie ({', '.join(referencias_incorrectas)} -> {reference})"
                )

            if changed:
                print(f"[{request_id}] subiendo DOCX corregido al mismo fileId ({docx_file_id}) ...")
                update_drive_file_content(drive, docx_file_id, new_bytes, DOCX_MIME)
                docx_bytes_for_pdf = new_bytes
                fecha_nota = ", ".join(notas_parciales) + f", DOCX actualizado en el mismo fileId ({docx_file_id}), "
            else:
                print(f"[{request_id}] ni placeholder de fecha ni referencia incorrecta encontrados en este DOCX — no se resube el DOCX, se continua igualmente con la generacion del PDF.")
                docx_bytes_for_pdf = original_bytes
                fecha_nota = "sin campo de fecha de publicacion ni referencia que corregir en este DOCX, "

            with tempfile.TemporaryDirectory() as workdir:
                print(f"[{request_id}] convirtiendo a PDF con LibreOffice ...")
                pdf_bytes = convert_docx_to_pdf(docx_bytes_for_pdf, workdir)

            pdf_filename = f"{reference}.pdf"
            print(f"[{request_id}] subiendo PDF nuevo a la carpeta del expediente ({folder_id}) ...")
            pdf_file_id = upload_new_file(drive, folder_id, pdf_filename, pdf_bytes, PDF_MIME)

            resolved_note = (
                f"RESUELTO_AUTOMATICO_{now_iso()}_via_github_action_fix_docx_publication_date: "
                f"{fecha_nota}PDF generado y subido (fileId {pdf_file_id})."
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
