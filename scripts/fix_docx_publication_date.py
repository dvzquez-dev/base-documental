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
#
# CAMBIO 2026-07-14: se añadió "BLOQUEO_PDF" (bug real confirmado: UAWUVW7 tenía
# last_error="BLOQUEO_PDF_..." y esta tupla no lo reconocía, así que este mismo
# Action NUNCA lo tomaba como candidato — se quedaba esperando un GitHub Action que
# jamás lo iba a recoger). Mantener esta tupla sincronizada con la de
# check_pipeline_status.py si en el futuro aparece alguna marca nueva.
STRUCTURAL_BLOCK_MARKERS = ("PENDIENTE_MANUAL_CONFIRMADO", "MANUAL_INTERVENTION", "BLOQUEO_PDF")

PLACEHOLDER = "Fecha de publicación: --/--/----"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PDF_MIME = "application/pdf"

# AÑADIDO 2026-07-13 (pedido explícito de Daniel): patrón para detectar una referencia
# documental con forma "Palabra_S-NNNN_NN" (p.ej. "Informe_S-6009_26") dentro de
# cabeceras/pies, para poder sustituirla por la reference real reservada cuando el
# documento llega con una referencia antigua/de plantilla copiada de otro expediente.
#
# AMPLIADO 2026-07-14 (pedido explícito de Daniel): las plantillas usan un placeholder
# literal con X en vez de dígitos antes de rellenar la referencia real (mismo patrón de
# diseño que "Fecha de publicación: --/--/----" para la fecha) — p.ej.
# "Informe_S-XXXX_XX", "Informe_S-xxxx_xx", o incluso formas mixtas medio sin rellenar
# como "Informe_S-6009_XX". El patrón ahora acepta dígitos O bloques de X/x (en
# cualquier combinación de mayúsculas/minúsculas) en cada tramo, para que el
# placeholder sin rellenar se detecte y corrija igual que una referencia equivocada.
REFERENCE_PATTERN = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]+_S-(?:\d{3,5}|[Xx]{3,5})_(?:\d{2}|[Xx]{2})")

SOLICITUDES_SHEET = "SOLICITUDES"
CONFIG_SHEET = "CONFIG"

# AÑADIDO 2026-07-14 (pedido explícito de Daniel) — campo "Revisor/es" del documento.
# Cowork YA NO edita este campo directamente (mismo límite estructural de tamaño que
# fecha/referencia): en el Paso 4 de "04_procesar_respuesta_revisor" v5 decide el texto
# final (nombre(s) resuelto(s) vía Notion + juicio sobre si ya está presente, y la
# etiqueta correcta "Revisor:"/"Revisores:" según cuántos queden) y lo dejan escrito en
# las columnas revisor_field_pendiente=TRUE / revisor_field_valor de SOLICITUDES. Este
# Action se limita a la parte mecánica: encontrar el campo en el footer y sustituirlo
# por ese texto ya decidido, tal cual.
#
# Detección: como Daniel confirmó que este campo SIEMPRE va en el footer (nunca en el
# cuerpo ni en la cabecera), y puede aparecer como "Revisor:", "Revisor/es:" o
# "Revisores:" indistintamente, se prueba una LISTA de patrones (no uno solo) contra
# cada footer*.xml, en el orden en que aparecen en CONFIG.REVISOR_FIELD_KNOWN_PATTERNS
# (JSON, lista de strings de regex). Si ninguno coincide, no se inventa nada ni se
# bloquea el resto del ciclo: se marca la fila con revisor_field_diagnostico_pendiente
# =TRUE para que Cowork abra el documento, vea cómo aparece de verdad el campo ahí, y
# escriba el patrón/formato observado en revisor_field_patron_sugerido — ese patrón se
# prueba primero en la siguiente corrida de este mismo Action, y si funciona, se añade
# también a la lista permanente en CONFIG para que futuros documentos con el mismo
# formato no vuelvan a necesitar escalar. Si el problema real es que Word partió el
# texto en varias runs de XML (no una simple variante de etiqueta), ningún patrón nuevo
# lo va a arreglar — ese caso cae a MANUAL_INTERVENTION, igual que con fecha/referencia.
DEFAULT_REVISOR_FIELD_PATTERNS = [r"Revisor(?:/es|es)?:\s*[^<]{0,150}"]


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


def actualizar_columnas(sheets, header, row_number, valores: dict):
    """Igual que actualizar_last_error_y_updated_at pero para un conjunto arbitrario
    de columnas de SOLICITUDES (dict columna->valor), en una sola llamada batchUpdate.
    Columnas que no existan en header se ignoran silenciosamente (para que este script
    no reviente si Daniel todavía no ha añadido alguna columna nueva a la Sheet)."""
    data = []
    for col_name, value in valores.items():
        if col_name not in header:
            print(f"AVISO: la columna '{col_name}' no existe en SOLICITUDES, se omite esa escritura.", file=sys.stderr)
            continue
        idx = header.index(col_name)
        data.append({
            "range": f"{SOLICITUDES_SHEET}!{col_letter(idx)}{row_number}",
            "values": [[value]],
        })
    if not data:
        return
    sheets.spreadsheets().values().batchUpdate(
        spreadsheetId=SPREADSHEET_ID,
        body={"valueInputOption": "RAW", "data": data},
    ).execute()


# --------------------------------------------------------------------------------------
# CONFIG — lectura/escritura genérica key/value, mismo estilo que check_pipeline_status.py
# (deliberadamente duplicado aquí en vez de importado: dos Actions independientes).
# --------------------------------------------------------------------------------------

def read_config(sheets):
    resp = sheets.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID, range=f"{CONFIG_SHEET}!A1:Z").execute()
    values = resp.get("values", [])
    if not values:
        return {}
    header = [h.strip() for h in values[0]]
    try:
        key_col = header.index("key")
    except ValueError:
        key_col = 0
    try:
        value_col = header.index("value")
    except ValueError:
        value_col = 1
    config = {}
    for row in values[1:]:
        key = row[key_col] if key_col < len(row) else ""
        value = row[value_col] if value_col < len(row) else ""
        if key:
            config[key] = value
    return config


def upsert_config_value(sheets, key, value):
    """Escribe o actualiza una fila key/value en CONFIG. Si la key ya existe,
    actualiza solo su celda 'value'; si no, añade una fila nueva al final."""
    resp = sheets.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID, range=f"{CONFIG_SHEET}!A1:Z").execute()
    values = resp.get("values", [])
    if not values:
        raise RuntimeError("CONFIG está vacío, no se puede escribir.")
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
    for i, row in enumerate(values[1:], start=2):
        cell_key = row[key_col] if key_col < len(row) else ""
        if str(cell_key).strip() == key:
            row_idx = i
            break

    if row_idx is not None:
        rng = f"{CONFIG_SHEET}!{col_letter(value_col)}{row_idx}"
        sheets.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID, range=rng, valueInputOption="RAW", body={"values": [[value]]},
        ).execute()
    else:
        new_row = [""] * (max(key_col, value_col) + 1)
        new_row[key_col] = key
        new_row[value_col] = value
        sheets.spreadsheets().values().append(
            spreadsheetId=SPREADSHEET_ID, range=f"{CONFIG_SHEET}!A1",
            valueInputOption="RAW", insertDataOption="INSERT_ROWS", body={"values": [new_row]},
        ).execute()


def get_revisor_field_patterns(config):
    """Lee CONFIG.REVISOR_FIELD_KNOWN_PATTERNS (JSON, lista de strings de regex).
    Si falta, está vacía o no es JSON válido, cae a DEFAULT_REVISOR_FIELD_PATTERNS
    (nunca se queda sin ningún patrón que probar)."""
    raw = config.get("REVISOR_FIELD_KNOWN_PATTERNS")
    if not raw:
        return list(DEFAULT_REVISOR_FIELD_PATTERNS)
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list) and all(isinstance(p, str) for p in parsed) and parsed:
            return parsed
    except json.JSONDecodeError:
        pass
    return list(DEFAULT_REVISOR_FIELD_PATTERNS)


def add_revisor_field_pattern_if_new(sheets, config, pattern):
    """Añade `pattern` a la lista permanente de CONFIG.REVISOR_FIELD_KNOWN_PATTERNS si
    todavía no está (dedup exacto de string). Así, un patrón que Cowork diagnosticó para
    un documento concreto queda disponible automáticamente para el resto sin escalar de
    nuevo. No falla el ciclo si esto no se puede escribir (falta de permiso Editor en la
    Sheet, etc.) — solo lo avisa por stderr."""
    patterns = get_revisor_field_patterns(config)
    if pattern in patterns:
        return
    patterns.append(pattern)
    try:
        upsert_config_value(sheets, "REVISOR_FIELD_KNOWN_PATTERNS", json.dumps(patterns, ensure_ascii=False))
        print(f"CONFIG.REVISOR_FIELD_KNOWN_PATTERNS ampliado con el nuevo patrón: {pattern!r}")
    except Exception as exc:
        print(f"AVISO: no se pudo persistir el nuevo patrón en CONFIG: {exc}", file=sys.stderr)


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
    """AÑADIDO 2026-07-13, AMPLIADO 2026-07-14. Busca en CUALQUIER header*.xml/footer*.xml
    del documento texto con forma de referencia documental (REFERENCE_PATTERN) que no
    coincida con correct_reference, y lo sustituye. Devuelve (nuevo_docx_bytes, cambiado,
    referencias_incorrectas_encontradas). No toca el cuerpo del documento ni ningún
    otro contenido. Detección por patrón, no por lista cerrada: si la cabecera no
    sigue ese formato exacto, o el texto está partido en varias runs de XML por
    ediciones previas de Word, simplemente no encontrará nada que corregir (mismo
    tipo de limitación ya conocida y aceptada para el placeholder de fecha). Desde
    2026-07-14 también detecta y corrige el placeholder de plantilla sin rellenar
    (p.ej. "Informe_S-XXXX_XX"), no solo referencias reales equivocadas."""
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


def patch_docx_revisor_field(docx_bytes, patterns, nuevo_valor):
    """AÑADIDO 2026-07-14. Busca en CUALQUIER footer*.xml (confirmado por Daniel: este
    campo SIEMPRE va en el footer) el campo "Revisor/es" en cualquiera de sus 3 formas
    ("Revisor:", "Revisor/es:", "Revisores:"), probando `patterns` en orden hasta que
    uno haga match, y sustituye el fragmento encontrado COMPLETO (etiqueta + valor
    actual) por `nuevo_valor` tal cual — ya viene decidido de antemano (etiqueta
    singular/plural correcta + nombre(s)) por Cowork en 04_procesar_respuesta_revisor,
    este Action no decide nada, solo escribe. Devuelve (nuevo_docx_bytes, cambiado,
    patron_usado). Solo se sustituye la PRIMERA aparición encontrada (count=1): este
    campo debería aparecer una sola vez por documento; si aparece más de una, es una
    señal a investigar manualmente, no algo que este script deba intentar adivinar.

    Igual que con fecha/referencia: si el texto está partido en varias runs de XML por
    ediciones manuales previas de Word, ningún patrón de estos lo va a encontrar —
    limitación conocida y aceptada, no un fallo de esta función."""
    zin = zipfile.ZipFile(io.BytesIO(docx_bytes), "r")
    changed = False
    patron_usado = None
    out_buf = io.BytesIO()

    compiled = []
    for p in patterns:
        try:
            compiled.append((p, re.compile(p)))
        except re.error as exc:
            print(f"AVISO: patrón de Revisor/es inválido, se omite ({p!r}): {exc}", file=sys.stderr)

    with zipfile.ZipFile(out_buf, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if not changed and re.match(r"word/footer\d*\.xml$", item.filename):
                text = data.decode("utf-8")
                for patron_str, patron_re in compiled:
                    new_text, n = patron_re.subn(nuevo_valor, text, count=1)
                    if n > 0:
                        text = new_text
                        data = text.encode("utf-8")
                        changed = True
                        patron_usado = patron_str
                        break
            zout.writestr(item, data)

    return out_buf.getvalue(), changed, patron_usado


def generar_y_subir_pdf(drive, docx_bytes, folder_id, reference):
    """Convierte docx_bytes a PDF con LibreOffice headless y lo sube como archivo NUEVO
    a folder_id (nunca sobrescribe un PDF existente por fileId — mismo criterio que ya
    usaba main() para el flujo de fecha/referencia). Devuelve el fileId del PDF nuevo.
    Factorizado 2026-07-14 para reutilizarlo también en el flujo del campo Revisor/es."""
    with tempfile.TemporaryDirectory() as workdir:
        pdf_bytes = convert_docx_to_pdf(docx_bytes, workdir)
    pdf_filename = f"{reference}.pdf"
    return upload_new_file(drive, folder_id, pdf_filename, pdf_bytes, PDF_MIME)


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

    print("\n--- Resumen (fecha/referencia) ---")
    print(f"Corregidos: {fixed}")
    print(f"Omitidos: {skipped}")
    print(f"Errores: {errors}")

    # ------------------------------------------------------------------------------
    # AÑADIDO 2026-07-14 — campo "Revisor/es": procesa por separado las filas donde
    # Cowork dejó revisor_field_pendiente=TRUE, independientemente de si también
    # tenían un bloqueo estructural de fecha/referencia (puede ser cualquier
    # expediente recién aprobado, no solo los ya diagnosticados arriba).
    # ------------------------------------------------------------------------------
    config = read_config(sheets)
    patrones_base = get_revisor_field_patterns(config)

    revisor_candidatas = [
        r for r in filas
        if es_true(r.get("revisor_field_pendiente")) and not es_true(r.get("closed"))
    ]

    revisor_fixed = []
    revisor_escalados = []
    revisor_errors = []

    for row in revisor_candidatas:
        request_id = row.get("request_id")
        if not request_id:
            continue

        docx_file_id = row.get("drive_docx_file_id") or row.get("source_drive_file_id")
        folder_id = row.get("drive_folder_id")
        reference = row.get("reference") or request_id
        nuevo_valor = row.get("revisor_field_valor")

        if not docx_file_id or not folder_id or not nuevo_valor:
            revisor_errors.append((request_id, "sin drive_docx_file_id/drive_folder_id/revisor_field_valor"))
            continue

        # Si Cowork ya diagnosticó un patrón concreto para esta fila (escalado en un
        # ciclo anterior), se prueba PRIMERO ese, antes que la lista general — es más
        # específico y ya sabemos que describe este documento en concreto.
        patron_sugerido = row.get("revisor_field_patron_sugerido")
        patrones_a_probar = ([patron_sugerido] if patron_sugerido else []) + patrones_base

        try:
            print(f"[{request_id}] (Revisor/es) descargando {docx_file_id} ...")
            original_bytes = download_file(drive, docx_file_id)

            new_bytes, changed, patron_usado = patch_docx_revisor_field(original_bytes, patrones_a_probar, nuevo_valor)

            if not changed:
                # Ningún patrón conocido coincidió: escalar a Cowork para diagnóstico,
                # sin bloquear el resto del ciclo ni marcar el expediente como error.
                actualizar_columnas(sheets, header, row["_row_number"], {
                    "revisor_field_diagnostico_pendiente": "TRUE",
                    "last_error": (
                        "REVISOR_FIELD_PATRON_NO_ENCONTRADO: ningún patrón conocido de "
                        "CONFIG.REVISOR_FIELD_KNOWN_PATTERNS (ni el patrón sugerido, si había) "
                        "coincide en ningún footer de este DOCX. Pendiente de diagnóstico por Cowork."
                    ),
                    "updated_at": now_iso(),
                })
                revisor_escalados.append(request_id)
                print(f"[{request_id}] (Revisor/es) ningún patrón coincidió, escalado a diagnóstico.")
                continue

            print(f"[{request_id}] (Revisor/es) patrón usado: {patron_usado!r}; subiendo DOCX corregido ...")
            update_drive_file_content(drive, docx_file_id, new_bytes, DOCX_MIME)

            # Si el patrón que funcionó vino del diagnóstico de Cowork (no estaba ya en
            # la lista permanente), se añade a CONFIG para que futuros documentos con el
            # mismo formato no necesiten volver a escalar.
            if patron_usado not in patrones_base:
                add_revisor_field_pattern_if_new(sheets, config, patron_usado)
                patrones_base = get_revisor_field_patterns(config)

            print(f"[{request_id}] (Revisor/es) regenerando PDF ...")
            pdf_file_id = generar_y_subir_pdf(drive, new_bytes, folder_id, reference)

            resolved_note = (
                f"RESUELTO_AUTOMATICO_{now_iso()}_via_github_action_fix_docx_publication_date_revisor_field: "
                f"campo Revisor/es actualizado ({nuevo_valor}), PDF regenerado y subido (fileId {pdf_file_id})."
            )
            actualizar_columnas(sheets, header, row["_row_number"], {
                "revisor_field_pendiente": "FALSE",
                "revisor_field_diagnostico_pendiente": "FALSE",
                "revisor_field_patron_sugerido": "",
                "last_error": resolved_note,
                "updated_at": now_iso(),
            })
            revisor_fixed.append((request_id, pdf_file_id))
            print(f"[{request_id}] (Revisor/es) OK.")

        except Exception as exc:  # noqa: BLE001
            revisor_errors.append((request_id, str(exc)))
            print(f"[{request_id}] (Revisor/es) ERROR: {exc}", file=sys.stderr)

    print("\n--- Resumen (campo Revisor/es) ---")
    print(f"Corregidos: {revisor_fixed}")
    print(f"Escalados a diagnóstico: {revisor_escalados}")
    print(f"Errores: {revisor_errors}")

    if errors or revisor_errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
