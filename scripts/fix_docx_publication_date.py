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
     encuentra nada que corregir).
  2b-bis. AÑADIDO 2026-07-20 (FIX F, bug real confirmado en 79E115DB): la limitación
     de "texto partido en varias runs de Word" mencionada arriba dejó de ser teórica
     — es justo lo que le pasaba a este expediente (el placeholder "XXXX" llevaba un
     resaltado propio, así que Word lo guardó en una run de XML aparte). Ahora, si la
     sustitución simple no encuentra nada pero el texto reconstruido de verdad (unir
     todos los <w:t> de un párrafo, como lo ve Word al renderizar) demuestra que la
     referencia sigue mal, se aplica un segundo intento (_patch_reference_split_runs)
     que localiza el match en ese texto reconstruido y edita solo el contenido de las
     runs afectadas, sin tocar formato ni el resto del documento.
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

# AÑADIDO 2026-07-20 (segundo bug real detectado en el caso 79E115DB, DESPUÉS de
# ampliar REFERENCE_PATTERN arriba): con el patrón ya ampliado, el Action volvió a
# correr, corrigió la fecha, pero la referencia SEGUÍA sin corregirse — confirmado
# descargando el PDF resultante y viendo "Informe_S-XXXX_XX" intacto en cabecera/pie.
# Causa real (confirmada 2026-07-20 abriendo el .docx original de este expediente,
# el que Daniel subió tal cual venía del formulario): el placeholder vive dentro de
# un CUADRO DE TEXTO flotante en el header (<w:drawing>...<wps:txbx><w:txbxContent>),
# duplicado dos veces por el propio Word dentro de <mc:AlternateContent> (una copia
# moderna en <mc:Choice> vía DrawingML, y una copia de compatibilidad en
# <mc:Fallback><w:pict>... vía VML) — patrón MUY común en plantillas corporativas
# con cabeceras de diseño. Además, dentro de ese cuadro de texto, el placeholder
# está partido en variar runs (<w:r><w:t>Informe_S</w:t></w:r>...<w:t>-</w:t>...
# <w:t>XXX</w:t></w:r><w:t>X_XX</w:t>) porque cada fragmento tiene un <w:rPr>
# ligeramente distinto (aunque visualmente sea una sola cadena continua).
#
# Primer intento (fallido, no se llegó a desplegar en producción): un fallback que
# reparseaba el XML de header/footer entero con xml.etree.ElementTree, reconstruía
# el texto por párrafo, y volvía a serializar el árbol completo con ET.tostring().
# Probado contra el .docx real de este expediente: SÍ encontraba y corregía el
# placeholder correctamente a nivel de texto, PERO ET.tostring() renombra TODOS los
# prefijos de namespace del documento (mc, wps, wp, r, v, a... pasan a ns1, ns2,
# ns3...) porque solo se había registrado el prefijo "w" — un cambio innecesariamente
# agresivo para un documento con dibujos/cuadros de texto/VML como este, y con riesgo
# real de romper referencias de relación (r:id/r:embed) o el propio mc:Ignorable en
# lectores más estrictos que LibreOffice. Descartado antes de desplegarlo.
#
# Solución final (la que se despliega abajo, verificada de extremo a extremo: DOCX
# real de este expediente -> parcheado -> convertido a PDF con LibreOffice headless
# en un sandbox de pruebas -> 23 de 24 páginas confirmadas con "Informe_S-2011_26"
# correcto, 0 páginas con el placeholder, portada sin referencia como es de esperar):
# _patch_reference_surgical NO reparsea ni reserializa el XML en ningún momento.
# Usa un regex para localizar CADA <w:t>...</w:t> del archivo (sin tocar sus tags,
# atributos ni nada de alrededor), concatena su contenido para reconstruir el texto
# real tal como lo ve Word al renderizar (igual idea que el intento anterior, pero
# sin pasar por un parser/serializador completo), encuentra ahí las referencias
# incorrectas, y edita ÚNICAMENTE los tramos de texto exactos (por posición, sobre el
# string original) de los <w:t> afectados — el resto del archivo, namespaces
# incluidos, queda byte a byte idéntico al original. Corrige automáticamente TODAS
# las copias del placeholder que haya en el archivo (p.ej. las de mc:Choice y
# mc:Fallback a la vez), sin necesidad de saber de antemano cuántas hay ni dónde.
_T_ELEM_RE = re.compile(r"<w:t(?:\s[^>]*)?>(.*?)</w:t>", re.DOTALL)


def _xml_unescape(s):
    return (s.replace("&lt;", "<").replace("&gt;", ">")
             .replace("&apos;", "'").replace("&quot;", '"').replace("&amp;", "&"))


def _xml_escape(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _patch_reference_surgical(xml_text, correct_reference):
    """Ver nota larga arriba. Localiza REFERENCE_PATTERN sobre el texto reconstruido
    de TODOS los <w:t> del archivo (whole-file, no por párrafo — más simple y ya
    suficiente: el patrón es lo bastante específico como para que un match espurio
    cruzando dos runs de párrafos distintos sea prácticamente imposible en la
    práctica) y edita solo el contenido de los <w:t> afectados sobre el string
    original, sin reparsear ni reserializar nada. Devuelve (nuevo_texto, cambiado,
    referencias_encontradas). Corrige todas las apariciones que haya (p.ej. las
    copias duplicadas de mc:Choice/mc:Fallback), no solo la primera."""
    t_matches = list(_T_ELEM_RE.finditer(xml_text))
    if not t_matches:
        return xml_text, False, []

    texts = [_xml_unescape(m.group(1)) for m in t_matches]
    full_text = "".join(texts)
    ref_matches = list(REFERENCE_PATTERN.finditer(full_text))
    if not ref_matches:
        return xml_text, False, []

    offsets = []
    pos = 0
    for m, txt in zip(t_matches, texts):
        offsets.append((pos, pos + len(txt), m))
        pos += len(txt)

    edits = []  # (start_en_xml_text, end_en_xml_text, contenido_nuevo_ya_escapado)
    encontradas = set()

    for rm in ref_matches:
        found_text = rm.group(0)
        if found_text == correct_reference:
            continue
        start, end = rm.start(), rm.end()
        affected = [(a, b, m) for (a, b, m) in offsets if b > start and a < end]
        if not affected:
            continue
        encontradas.add(found_text)
        first_a, _, first_m = affected[0]
        last_a, _, last_m = affected[-1]
        first_idx = t_matches.index(first_m)
        last_idx = t_matches.index(last_m)
        prefix = texts[first_idx][: max(0, start - first_a)]
        suffix = texts[last_idx][max(0, end - last_a):]
        if first_m is last_m:
            edits.append((first_m.start(1), first_m.end(1), _xml_escape(prefix + correct_reference + suffix)))
        else:
            edits.append((first_m.start(1), first_m.end(1), _xml_escape(prefix + correct_reference)))
            edits.append((last_m.start(1), last_m.end(1), _xml_escape(suffix)))
            for (_, _, mid_m) in affected[1:-1]:
                edits.append((mid_m.start(1), mid_m.end(1), ""))

    if not edits:
        return xml_text, False, []

    # aplica de atras hacia adelante para no invalidar las posiciones ya calculadas
    edits.sort(key=lambda e: e[0], reverse=True)
    new_text = xml_text
    for start, end, replacement in edits:
        new_text = new_text[:start] + replacement + new_text[end:]

    return new_text, True, sorted(encontradas)


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
# AÑADIDO 2026-07-21 (FIX G — gap estructural real, campo "Revisor/es"): el pipeline
# ya tenía documentado en CONFIG.REVISOR_FIELD_KNOWN_PATTERNS una "lista creciente" de
# patrones para localizar el placeholder de revisor/es en cabecera/pie (p.ej.
# "Revisor/es: ---- "), pensada para ampliarse igual que se hizo con REFERENCE_PATTERN
# más arriba (02_analisis_documento diagnostica un patrón nuevo cuando no reconoce el
# formato de una plantilla, y lo añade a esa lista en CONFIG). Pero nunca se había
# escrito el código que la USA — ni aquí ni en ningún otro script del pipeline. El
# caso 79E115DB fue el primero donde se notó de verdad: el revisor aprobó "con
# anotaciones" pidiendo explícitamente que se rellenara el campo, y no había ningún
# mecanismo automático que lo hiciera — un problema "diseñado en el papel, nunca
# construido", a caballo entre el esquema de SOLICITUDES (faltaban columnas) y este
# script (faltaba la función).
#
# Esta sección añade la pieza que faltaba:
#   - CONFIG_SHEET + leer_config_revisor_patterns(): lee la lista de patrones vigente
#     desde CONFIG (misma tabla key/value/notes que ya usa el resto del pipeline),
#     compilándolos como regex. Si la clave no existe, el valor no parsea como JSON, o
#     la lista sale vacía, cae a REVISOR_PATTERN_FALLBACK (el mismo patrón que ya
#     había en CONFIG a fecha de hoy) para no dejar el Action ciego si la celda se
#     borra por error.
#   - patch_docx_revisor(): mismo estilo que patch_docx_reference — recorre
#     header*.xml/footer*.xml, busca el primer patrón que haga match, y sustituye el
#     match COMPLETO por el texto final ya armado (p.ej. "Revisor/es: Daniel Vázquez
#     Piñeiro"). No reconstruye texto multi-run como _patch_reference_surgical porque
#     el caso real confirmado (79E115DB, word/footer2.xml) tiene el placeholder en una
#     única run de texto — si en el futuro aparece un caso partido en varias runs, se
#     puede extender con la misma técnica ya probada arriba para la referencia.
#   - En SOLICITUDES: dos columnas nuevas, revisor_field_pendiente (TRUE/FALSE) y
#     revisor_field_valor (texto completo de sustitución ya armado — lo arma quien
#     marca la fila, sea el flujo 4bis de Cowork o una edición manual). Una fila entra
#     en "candidatas" (ver main()) si tiene bloqueo estructural conocido O
#     revisor_field_pendiente=TRUE (antes solo lo primero: una fila ya resuelta de
#     fecha/referencia pero con el revisor todavía pendiente nunca se habría vuelto a
#     recoger). Al terminar con éxito, revisor_field_pendiente se limpia a FALSE, igual
#     que last_error se sobrescribe con la nota RESUELTO_AUTOMATICO_....
#
# NOTA 2026-07-21 noche (revertido tras feedback directo de Daniel): esa misma noche
# se intentó, en dos pasadas sucesivas, mover a este script la decisión de "¿el nuevo
# revisor ya está representado con un nombre distinto/incompleto/con errata?" (primero
# con coincidencia exacta de palabras + fusión automática, después añadiendo encima un
# umbral de similitud de difflib para detectar erratas). Daniel recordó que esa
# decisión YA estaba correctamente diseñada — desde el 2026-07-14 — para vivir en
# Cowork, no aquí: ver "04_procesar_respuesta_revisor" v5, Paso 4.d/4.e, donde Cowork
# ya usa JUICIO real (no comparación literal ni un umbral fijo) para decidir si el
# aprobador ya está representado en el campo, combina los nombres, y calcula la
# etiqueta correcta ('Revisor: '/'Revisores: ') ANTES de escribir revisor_field_valor.
# Ambos intentos se revirtieron por completo — patch_docx_revisor() vuelve a ser pura
# sustitución mecánica del match encontrado por revisor_field_valor, sin parsear ni
# combinar nombres aquí. Ver "04_procesar_respuesta_revisor" v6 para el refuerzo
# explícito de este reparto de responsabilidades tras este mismo incidente.
# --------------------------------------------------------------------------------------

CONFIG_SHEET = "CONFIG"

REVISOR_PATTERN_FALLBACK = (r"Revisor(?:/es|es)?:\s*[^<]{0,150}",)


def leer_config_revisor_patterns(sheets):
    """Lee CONFIG (columnas key/value/notes) buscando la fila cuya key sea
    REVISOR_FIELD_KNOWN_PATTERNS, espera un JSON array de strings-regex en su value,
    y devuelve la lista ya compilada. Si no encuentra la clave, el valor no parsea
    como JSON, o la lista sale vacía, cae a REVISOR_PATTERN_FALLBACK para no dejar el
    Action sin capacidad de corregir nada si la celda se borra por error."""
    try:
        resp = sheets.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID, range=f"{CONFIG_SHEET}!A1:B200"
        ).execute()
        values = resp.get("values", [])
        raw_value = None
        for row in values[1:]:
            if row and row[0].strip() == "REVISOR_FIELD_KNOWN_PATTERNS":
                raw_value = row[1] if len(row) > 1 else None
                break
        if raw_value:
            patrones = json.loads(raw_value)
            if isinstance(patrones, list) and patrones:
                return [re.compile(p) for p in patrones]
    except Exception as exc:  # noqa: BLE001 — un CONFIG mal formado no debe tumbar el Action
        print(f"WARN: no se pudo leer REVISOR_FIELD_KNOWN_PATTERNS de CONFIG ({exc}); usando fallback.", file=sys.stderr)
    return [re.compile(p) for p in REVISOR_PATTERN_FALLBACK]


def patch_docx_revisor(docx_bytes, revisor_field_valor, patterns):
    """CORREGIDO 2026-07-21 noche (revertido tras feedback directo de Daniel: en una
    sesión anterior ya se había diseñado — y quedó documentado en
    "04_procesar_respuesta_revisor" v5, Paso 4.d/4.e — que la decisión de "¿es la
    misma persona con una variante/errata de nombre, o alguien distinto?" y el
    cálculo de la etiqueta correcta ('Revisor: ' vs 'Revisores: ') las hace Cowork
    con JUICIO REAL en el momento de procesar la respuesta del revisor, ANTES de
    escribir revisor_field_valor — no este script. Este mismo fix había intentado
    (más temprano en esta sesión) reimplementar esa misma decisión aquí dentro con
    funciones tipo combinar_revisor()/_mismo_revisor() y, después, con un umbral de
    similitud de difflib — ambos intentos duplicaban/contradecían un diseño que ya
    existía y que delega correctamente esa ambigüedad a la IA en el flujo de la
    tarea, en vez de a una heurística fija en Python. Se revierte por completo: este
    script vuelve a ser una sustitución MECÁNICA y determinista, igual que
    patch_docx_reference — busca en CUALQUIER header*.xml/footer*.xml el primer
    patrón (de patterns, en orden) que haga match con el campo de revisor/es
    existente (sea cual sea su contenido: vacío, un nombre, varios nombres, o un
    placeholder de cualquier tipo — no se interpreta, solo se localiza por regex), y
    sustituye el match COMPLETO por revisor_field_valor tal cual llega desde
    SOLICITUDES (el texto final completo, ya con el nombre/lista de nombres
    correctamente combinada y la etiqueta 'Revisor: '/'Revisores: ' ya decidida por
    Cowork en el Paso 4 — ver 04_procesar_respuesta_revisor v5/v6). Idempotente: si
    el texto ya es idéntico a revisor_field_valor, no cuenta como cambio. Devuelve
    (nuevo_docx_bytes, cambiado, patron_usado_o_None). No toca el cuerpo del
    documento ni ningún otro contenido."""
    zin = zipfile.ZipFile(io.BytesIO(docx_bytes), "r")
    changed = False
    matched_pattern = None
    out_buf = io.BytesIO()

    with zipfile.ZipFile(out_buf, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if re.match(r"word/(header|footer)\d*\.xml$", item.filename):
                text = data.decode("utf-8")
                for pat in patterns:
                    m = pat.search(text)
                    if m:
                        actual = m.group(0)
                        if actual.strip() == revisor_field_valor.strip():
                            break
                        text = text[: m.start()] + revisor_field_valor + text[m.end():]
                        changed = True
                        matched_pattern = pat.pattern
                        break
                data = text.encode("utf-8")
            zout.writestr(item, data)

    return out_buf.getvalue(), changed, matched_pattern


def actualizar_revisor_field_pendiente(sheets, header, row_number, pendiente_value):
    """Escribe revisor_field_pendiente (TRUE/FALSE) de una fila concreta. Si la
    columna todavía no existe en SOLICITUDES (despliegue anterior a FIX G), no hace
    nada — evita un ValueError por columna no encontrada en vez de tumbar el Action."""
    if "revisor_field_pendiente" not in header:
        return
    idx = header.index("revisor_field_pendiente")
    sheets.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{SOLICITUDES_SHEET}!{col_letter(idx)}{row_number}",
        valueInputOption="RAW",
        body={"values": [[pendiente_value]]},
    ).execute()


# NOTA 2026-07-21 noche: las columnas SOLICITUDES.revisor_posible_duplicado_pendiente
# y revisor_posible_duplicado_detalle (añadidas en Sheets esa misma noche, columnas
# DK/DL) quedaron SIN USO tras revertir este fix a sustitución mecánica pura — no se
# borraron de la Sheet (evitar más cirugía de columnas la misma noche que ya tiene el
# problema de duplicados CV/CW vs DG/DH sin resolver), pero este script no las escribe
# ni las lee. Si en el futuro se decide reutilizarlas para otra cosa, están libres.


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
    """AÑADIDO 2026-07-13, REESCRITO 2026-07-20 (FIX F, verificado de extremo a
    extremo contra el .docx real de 79E115DB + conversión con LibreOffice headless).
    Busca en CUALQUIER header*.xml/footer*.xml del documento texto con forma de
    referencia documental (REFERENCE_PATTERN) que no coincida con correct_reference,
    y lo sustituye — incluidas las apariciones partidas en varias runs de Word (ver
    _patch_reference_surgical arriba) y las copias duplicadas que Word suele generar
    en cabeceras con cuadros de texto (mc:Choice + mc:Fallback). Devuelve
    (nuevo_docx_bytes, cambiado, referencias_incorrectas_encontradas). No toca el
    cuerpo del documento ni ningún otro contenido."""
    zin = zipfile.ZipFile(io.BytesIO(docx_bytes), "r")
    changed = False
    encontradas = set()
    out_buf = io.BytesIO()

    with zipfile.ZipFile(out_buf, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if re.match(r"word/(header|footer)\d*\.xml$", item.filename):
                text = data.decode("utf-8")
                new_text, file_changed, found = _patch_reference_surgical(text, correct_reference)
                if file_changed:
                    data = new_text.encode("utf-8")
                    changed = True
                    encontradas.update(found)
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

    # AÑADIDO 2026-07-21 (FIX G): se lee una sola vez, se usa para patch_docx_revisor
    # en cada candidata que tenga revisor_field_pendiente=TRUE (ver más abajo).
    revisor_patterns = leer_config_revisor_patterns(sheets)

    # AMPLIADO 2026-07-21 (FIX G): antes solo entraban filas con marca de bloqueo
    # estructural en last_error. Eso dejaba fuera para siempre una fila ya resuelta de
    # fecha/referencia (last_error reescrito a RESUELTO_AUTOMATICO_...) pero con el
    # campo Revisor/es todavía pendiente de rellenar — nunca se habría vuelto a
    # recoger. Ahora también entra cualquier fila con revisor_field_pendiente=TRUE,
    # independientemente de lo que diga last_error.
    candidatas = [
        r for r in filas
        if es_true(r.get("approved"))
        and not es_true(r.get("closed"))
        and (
            tiene_marca_bloqueo_estructural(r.get("last_error", ""))
            or es_true(r.get("revisor_field_pendiente"))
        )
    ]

    if not candidatas:
        print("No hay expedientes aprobados-no-cerrados con bloqueo estructural conocido ni con revisor pendiente. Nada que hacer.")
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

            # AÑADIDO 2026-07-21 (FIX G): igual que la referencia, se aplica encadenado
            # sobre el resultado anterior (no en paralelo), y solo si esta fila viene
            # marcada como revisor_field_pendiente=TRUE con un revisor_field_valor no
            # vacío ya armado (p.ej. "Revisor/es: Daniel Vázquez Piñeiro").
            revisor_pendiente = es_true(row.get("revisor_field_pendiente"))
            revisor_valor = (row.get("revisor_field_valor") or "").strip()
            changed_revisor = False
            if revisor_pendiente and revisor_valor:
                revisor_bytes, changed_revisor, revisor_patron_usado = patch_docx_revisor(
                    ref_bytes, revisor_valor, revisor_patterns
                )
            else:
                revisor_bytes = ref_bytes
                revisor_patron_usado = None

            new_bytes = revisor_bytes
            changed = changed_fecha or changed_ref or changed_revisor

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
            # AÑADIDO 2026-07-21 (FIX G): registra el resultado del parcheo de revisor
            # en las tres situaciones posibles — no aplicaba, aplicó con éxito, o
            # estaba pendiente pero ningún patrón conocido hizo match (caso que sí
            # necesita revisión manual, a diferencia de "sin campo que corregir").
            if revisor_pendiente and revisor_valor:
                if changed_revisor:
                    notas_parciales.append(
                        f"campo Revisor/es corregido en cabecera/pie (patron '{revisor_patron_usado}' -> \"{revisor_valor}\")"
                    )
                else:
                    notas_parciales.append(
                        "revisor_field_pendiente=TRUE pero ningun patron de CONFIG.REVISOR_FIELD_KNOWN_PATTERNS "
                        "hizo match en cabecera/pie de este DOCX (revision manual necesaria, posible plantilla nueva)"
                    )

            if changed:
                print(f"[{request_id}] subiendo DOCX corregido al mismo fileId ({docx_file_id}) ...")
                update_drive_file_content(drive, docx_file_id, new_bytes, DOCX_MIME)
                docx_bytes_for_pdf = new_bytes
                fecha_nota = ", ".join(notas_parciales) + f", DOCX actualizado en el mismo fileId ({docx_file_id}), "
            else:
                print(f"[{request_id}] ni placeholder de fecha ni referencia incorrecta encontrados en este DOCX — no se resube el DOCX, se continua igualmente con la generacion del PDF.")
                docx_bytes_for_pdf = original_bytes
                if notas_parciales:
                    fecha_nota = ", ".join(notas_parciales) + ", "
                else:
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

            # AÑADIDO 2026-07-21 (FIX G): si el revisor SÍ estaba pendiente y SÍ se
            # corrigió, se limpia el flag para que esta fila no se vuelva a recoger en
            # la siguiente corrida solo por este motivo. Si estaba pendiente pero no
            # se encontró ningún patrón (revision manual necesaria), se deja el flag
            # en TRUE a propósito — así la fila sigue apareciendo como candidata en
            # cada corrida hasta que alguien lo resuelva a mano o amplíe CONFIG.
            if revisor_pendiente and revisor_valor and changed_revisor:
                actualizar_revisor_field_pendiente(sheets, header, row["_row_number"], "FALSE")

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
