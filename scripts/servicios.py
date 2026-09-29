#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Las manos: lo único de todo el pipeline que toca el mundo.

Qué es esto
-----------
El resto del pipeline decide y no ejecuta: `pipeline` dice qué toca, `ejecutor` lo aplica contra
un objeto `servicios`, y `hoja`/`sheets_api`/`notion_api` dan forma a lo que se manda. **Aquí está
la implementación de ese objeto**, y es a propósito la pieza más tonta del conjunto: cuanto menos
decida, menos hay que probar contra el mundo.

⛔ **Todo lo que decide algo vive fuera.** Si alguna vez hace falta una condición aquí dentro, va
mal: se saca a un módulo puro y se prueba allí.

Convenciones que NO se inventan aquí
------------------------------------
📏 Medidas del propio repo el 29/09/2026, no elegidas:

- **Google**: la clave de la cuenta de servicio va en **`GDRIVE_SA_KEY`**, en JSON o en base64
  (`check_pipeline_status.py` lo hace así), y se construye con
  `service_account.Credentials.from_service_account_info`.
- **Notion**: este repo **no tiene cliente de Notion en Python** — su sincronización va por Node
  (`scripts/sync-notion.mjs`) con `NOTION_TOKEN`. Así que aquí se habla por HTTP directo, con la
  cabecera `Notion-Version`.
- La hoja es `SOLICITUDES` de `1EL5luW…`, y el Libro de Datos vive en otra
  (`1QoEY…`, pestaña **«Base de Datos»**, con espacios: por eso se entrecomilla).

⚠️ **El token no se imprime nunca**, ni siquiera en un error: `_sin_secretos` recorta cualquier
cosa que se parezca a una credencial antes de que salga por pantalla.

Cómo se prueba
--------------
`python scripts/test_servicios.py` — con el transporte doblado. **No abre una sola conexión**:
un banco que hable con el mundo hace el daño que dice vigilar.
"""
import base64
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding="utf-8")
    except Exception:  # pragma: no cover
        pass

import anexos as AX
import drive_api as DA
import hoja as H
import libro_datos as LD
import notion_api as NA
import publicar_notion as PN
import sheets_api as SA

# 📏 Medidos del repo y de las hojas reales.
HOJA_SOLICITUDES = "1EL5luWUYD5_3onxaDUSHmexzzQZEkPNLW1Y4QzzRg20"
PESTANA_SOLICITUDES = "SOLICITUDES"
RANGO_SOLICITUDES = "SOLICITUDES!A1:BZ"
HOJA_LIBRO = "1QoEY_5PYYidKlT2RNX_5m5Jq7-h-xfU_z6cZQ6pFSwE"
PESTANA_LIBRO = "Base de Datos"
# ⛔⛔ **2025-09-03, no 2022-06-28.** `notion_api.cuerpo_pagina` manda
#    `parent = {"type": "data_source_id", …}`, que es la forma de las bases **multi-fuente**
#    y **no existe** en `2022-06-28`, donde el padre es `database_id`. Con las dos en
#    desacuerdo, el primer documento que se publique se va con un **400** — y no había dónde
#    notarlo antes, porque el cuerpo se construye en un módulo y la cabecera se pone aquí.
#    Lo ata un caso en `test_servicios.py`, que lee **las dos** cosas a la vez.
# ⚠️ `scripts/sync-notion.mjs` se queda en `2022-06-28` **a propósito**: consulta
#    `/v1/databases/{id}/query`, que es de esa época. Dos clientes, dos trabajos.
# ⬜ **Lo único del pipeline que NO está medido contra la API viva.** Se comprueba con el
#    primer `--aplicar` de verdad, o antes con:
#      curl -s -X POST https://api.notion.com/v1/pages -H "Notion-Version: 2025-09-03" \n#           -H "Authorization: Bearer $NOTION_TOKEN" -H "Content-Type: application/json" \n#           -d '{"parent":{"type":"data_source_id","data_source_id":"<ID>"},"properties":{}}'
NOTION_VERSION = "2025-09-03"
NOTION_CREAR = "https://api.notion.com/v1/pages"
NOTION_HIJOS = "https://api.notion.com/v1/blocks/%s/children"
NOTION_FUENTE = "https://api.notion.com/v1/data_sources/%s"
NOTION_BASE = "https://api.notion.com/v1/databases/%s"

# ⛔ La base «Documentos internos». **No es un secreto**: está escrita a la vista en
#    `scripts/sync-notion.mjs` desde antes de todo esto, y es un identificador, no una credencial.
#    De aquí se DEDUCE la fuente de datos, para no obligar a nadie a ir a buscar un secreto más —
#    y para pedirlo haría falta el token, que GitHub **no devuelve nunca**: sacarlo obligaba a
#    **rotar una credencial** para leer un id que no lo es.
NOTION_BASE_DOCS = "11eb0e3a469c80b9969ff0d0e88e2f36"

# ⚠️ Drive entero, no `readonly`: hay que CREAR la carpeta del expediente. Es el mismo
#    alcance que ya piden `publish_temp_pdfs.py` y `fix_docx_publication_date.py`.
ALCANCES = ["https://www.googleapis.com/auth/drive",
            "https://www.googleapis.com/auth/spreadsheets"]
PESTANA_RUTAS = "RUTAS"

# Lo que se tacha si asoma en un mensaje de error.
_SECRETO = re.compile(r"(secret|token|private_key|Bearer\s+\S+|ya29\.\S+|ntn_\S+|secret_\S+)",
                      re.I)


def sin_secretos(texto):
    """El texto con cualquier cosa con pinta de credencial tachada.

    ⛔ Se aplica a **todo** lo que sale por pantalla desde aquí, incluidos los errores. Un token
    en un traza de error acaba en el registro de una acción de GitHub, que es público para quien
    tenga acceso al repo — y un secreto que se ha visto una vez hay que rotarlo.
    """
    return _SECRETO.sub(u"███", str(texto if texto is not None else ""))


def credenciales_google():
    """Las credenciales de la cuenta de servicio, o `SystemExit` con un motivo legible.

    ⚠️ Acepta JSON y base64 porque el repo ya lo hace así en `check_pipeline_status.py`: el
    secreto de GitHub a veces viaja codificado. Cambiar el nombre de la variable partiría en dos
    la configuración que ya existe.
    """
    crudo = os.environ.get("GDRIVE_SA_KEY", "").strip()
    if not crudo:
        raise SystemExit("falta la variable de entorno GDRIVE_SA_KEY: sin ella no se puede "
                         "leer ni escribir nada, y no se ha hecho NADA")
    try:
        info = json.loads(crudo)
    except ValueError:
        try:
            info = json.loads(base64.b64decode(crudo))
        except Exception as e:                                          # noqa: BLE001
            raise SystemExit("GDRIVE_SA_KEY no es ni JSON ni base64 de un JSON: %s"
                             % sin_secretos(e))
    from google.oauth2 import service_account                            # noqa: PLC0415
    return service_account.Credentials.from_service_account_info(info, scopes=ALCANCES)


def cliente_sheets(credenciales=None):
    """El cliente de Sheets. Se separa para poder doblarlo entero en el banco."""
    from googleapiclient.discovery import build                          # noqa: PLC0415
    return build("sheets", "v4", credentials=credenciales or credenciales_google())


def _token_notion():
    tok = os.environ.get("NOTION_TOKEN", "").strip()
    if not tok:
        raise SystemExit("falta la variable de entorno NOTION_TOKEN: no se puede publicar")
    return tok


def http_notion(url, cuerpo, token=None):
    """POST a Notion. La única función de este fichero que abre una conexión a Notion.

    Se deja sola y sin lógica para que el banco la sustituya de una pieza.
    """
    import urllib.request                                                # noqa: PLC0415
    datos = json.dumps(cuerpo).encode("utf-8")
    req = urllib.request.Request(
        url, data=datos, method="POST",
        headers={"Authorization": "Bearer %s" % (token or _token_notion()),
                 "Content-Type": "application/json",
                 "Notion-Version": NOTION_VERSION})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def http_notion_patch(url, cuerpo, token=None):
    """PATCH a Notion. Aparte del POST **porque no es lo mismo**: «append block children» es un
    PATCH, y mandarlo por POST contesta **405** — los anexos se quedarían fuera de la página.
    """
    import urllib.request                                                # noqa: PLC0415
    datos = json.dumps(cuerpo).encode("utf-8")
    req = urllib.request.Request(
        url, data=datos, method="PATCH",
        headers={"Authorization": "Bearer %s" % (token or _token_notion()),
                 "Content-Type": "application/json",
                 "Notion-Version": NOTION_VERSION})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def http_subir(url, datos, nombre, token=None):
    """Manda el fichero a la URL que dio Notion, en `multipart/form-data`.

    📏 **Medido ejecutándolo el 29/09/2026**: contesta HTTP 200 con `status: uploaded`. El
    campo se llama `file`; con otro nombre, Notion acepta la petición y **no guarda nada**.
    """
    import urllib.request                                                # noqa: PLC0415
    frontera = "----solaris%d" % len(datos)
    sep = ("\r\n").encode()
    cuerpo = (b"--" + frontera.encode() + sep
              + ('Content-Disposition: form-data; name="file"; filename="%s"'
                 % nombre).encode("utf-8") + sep
              + b"Content-Type: application/octet-stream" + sep + sep
              + datos + sep + b"--" + frontera.encode() + b"--" + sep)
    req = urllib.request.Request(
        url, data=cuerpo, method="POST",
        headers={"Authorization": "Bearer %s" % (token or _token_notion()),
                 "Content-Type": "multipart/form-data; boundary=%s" % frontera,
                 "Notion-Version": NOTION_VERSION})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode("utf-8"))


def http_notion_get(url, token=None):
    """GET a Notion. Aparte del POST porque releer y escribir no son la misma operación."""
    import urllib.request                                                # noqa: PLC0415
    req = urllib.request.Request(
        url, method="GET",
        headers={"Authorization": "Bearer %s" % (token or _token_notion()),
                 "Notion-Version": NOTION_VERSION})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def medio_en_memoria(datos, tipo):
    """El envoltorio que Drive pide para subir bytes. Import perezoso a propósito."""
    from googleapiclient.http import MediaInMemoryUpload                  # noqa: PLC0415
    return MediaInMemoryUpload(datos, mimetype=tipo)


class Servicios(object):
    """Lo que el ejecutor llama. Cada método hace **una** cosa y no decide ninguna.

    ⚠️ Todo lo que toca el mundo entra por el constructor (`sheets`, `notion`), así que el banco
    pasa dobles y **no se abre una conexión**. Sin argumentos, construye los de verdad — y eso
    sólo ocurre cuando alguien lo pide explícitamente.
    """

    def __init__(self, sheets=None, notion=None, drive=None, subir=None, notion_get=None,
                 medio=None, notion_patch=None):
        self._sheets = sheets
        self._notion = notion or http_notion
        self._drive = drive
        # El envio del fichero en multipart: aparte del POST de JSON, porque es otra forma de
        # peticion y el banco necesita doblarla sola.
        self._subir = subir or http_subir
        # ⚠️ Inyectable como los demás: si no, el banco acabaría pidiendo `NOTION_TOKEN` y
        #    hablando con Notion de verdad — justo lo que un banco no puede hacer.
        self._notion_get = notion_get or http_notion_get
        self._notion_patch = notion_patch or http_notion_patch
        # ⚠️ El envoltorio de subida de Drive, inyectable por lo mismo: `MediaInMemoryUpload`
        #    vive en `googleapiclient`, que el banco NO tiene instalado (y no debe: el paso de
        #    bancos del workflow corre ANTES del `pip install`).
        self._medio = medio or medio_en_memoria
        # Las opciones de «Etiquetas», leídas UNA vez: una pasada de 40 expedientes no puede
        # pedir el esquema 40 veces. `None` = todavía no se ha mirado; `[]` = se miró y no hay.
        self._opc_etq = None
        # La fuente de datos, deducida una vez por pasada.
        self._fuente = None

    @property
    def sheets(self):
        if self._sheets is None:
            self._sheets = cliente_sheets()
        return self._sheets

    @property
    def drive(self):
        if self._drive is None:
            from googleapiclient.discovery import build                  # noqa: PLC0415
            self._drive = build("drive", "v3", credentials=credenciales_google())
        return self._drive

    # ── leer ────────────────────────────────────────────────────────────────────────────────
    def leer(self):
        """Los valores crudos de `SOLICITUDES`, cabecera incluida."""
        r = (self.sheets.spreadsheets().values()
             .get(spreadsheetId=HOJA_SOLICITUDES, range=RANGO_SOLICITUDES).execute())
        return r.get("values", [])

    def leer_libro(self):
        """Las filas del Libro de Datos, **sin** la cabecera (es lo que espera `libro_datos`)."""
        rango = u"%s!A1:C" % SA.nombre_pestana(PESTANA_LIBRO)
        r = (self.sheets.spreadsheets().values()
             .get(spreadsheetId=HOJA_LIBRO, range=rango).execute())
        return (r.get("values", []) or [])[1:]

    def leer_rutas(self):
        """Las filas de `RUTAS` como diccionarios. La carpeta de destino sale de aquí."""
        r = (self.sheets.spreadsheets().values()
             .get(spreadsheetId=HOJA_SOLICITUDES, range=u"%s!A1:H" % PESTANA_RUTAS).execute())
        filas, _dup = H.a_registros(r.get("values", []))
        return filas

    def releer(self, claves):
        """`{A1: valor}` para las celdas que se acaban de escribir.

        ⛔ Es la mitad de la verificación: en este proyecto está medido que una escritura puede
        no hacer nada y decir que sí.
        """
        if not claves:
            return {}
        rangos = [SA.rango(PESTANA_SOLICITUDES, c) for c in claves]
        rangos = [r for r in rangos if r]
        if not rangos:
            return {}
        r = (self.sheets.spreadsheets().values()
             .batchGet(spreadsheetId=HOJA_SOLICITUDES, ranges=rangos).execute())
        fuera = {}
        for clave, bloque in zip(claves, r.get("valueRanges", [])):
            vals = bloque.get("values") or [[]]
            fuera[str(clave).strip()] = (vals[0] or [u""])[0]
        return fuera

    # ── escribir ────────────────────────────────────────────────────────────────────────────
    def escribir(self, celdas):
        """Escribe `[(A1, valor)]` en `SOLICITUDES`. Lanza si el cuerpo no se puede construir."""
        cuerpo, motivos = SA.cuerpo_batch(PESTANA_SOLICITUDES, celdas)
        if motivos:
            raise SystemExit("no se escribe nada: " + " | ".join(motivos))
        (self.sheets.spreadsheets().values()
         .batchUpdate(spreadsheetId=HOJA_SOLICITUDES, body=cuerpo).execute())

    # ── los pasos ───────────────────────────────────────────────────────────────────────────
    def analizar(self, fila):
        """Paso 2. **No implementado aquí a propósito**: es la única llamada a un modelo.

        ⛔ Se niega en voz alta en vez de devolver sin hacer nada. Un paso que calla y no hace
        deja la bandera puesta y el expediente dado por analizado **sin análisis**.
        """
        raise SystemExit("`analizar` es el paso del modelo y no vive en el adaptador: hoy lo "
                         "sigue haciendo Cowork. Esta pasada NO debe marcarlo como hecho")

    def fuente_de_datos(self):
        """El `data_source_id` donde se publica. De la variable, o **deducido de la base**.

        ⛔ `NOTION_DATA_SOURCE_ID` sigue mandando si está puesta — es la salida de emergencia
        para el día que la base tenga dos fuentes o haya que publicar en otra. Pero **no hace
        falta**: el id de la base ya vive a la vista en el repo y la fuente sale de él.
        ⚠️ Con **varias** fuentes no se adivina: publicar en la que no es parte la base en dos
        y eso no se deshace. Se para y se pide que se diga cuál.
        """
        a_mano = str(os.environ.get("NOTION_DATA_SOURCE_ID", "")).strip()
        if a_mano:
            return a_mano
        if self._fuente:
            return self._fuente
        base = str(os.environ.get("NOTION_BASE_DOCS", "") or NOTION_BASE_DOCS).strip()
        r = self._notion_get(NOTION_BASE % base) or {}
        fuentes = [f for f in (r.get("data_sources") or [])
                   if str((f or {}).get("id") or "").strip()]
        if not fuentes:
            raise SystemExit(
                "Notion no devolvió ninguna fuente de datos para la base %s (%r): sin ella no se "
                "sabe dónde crear la página. Si la base es otra, ponla en `NOTION_BASE_DOCS`; si "
                "la API no entiende `data_sources`, hace falta `NOTION_DATA_SOURCE_ID`"
                % (base, r.get("code") or r.get("object")))
        if len(fuentes) > 1:
            raise SystemExit(
                "la base %s tiene %d fuentes de datos (%s): publicar en la que no es parte la "
                "base en dos y no se deshace. Di cuál en `NOTION_DATA_SOURCE_ID`"
                % (base, len(fuentes), ", ".join(str(f.get("name")) for f in fuentes)))
        self._fuente = str(fuentes[0].get("id")).strip()
        return self._fuente

    def opciones_etiquetas(self, fuente=None):
        """Los nombres de las opciones que **ya tiene** «Etiquetas» en Notion. Lista, o `[]`.

        ⛔ Sin esto, `notion_api.casar_etiquetas` no puede reusar nada y cada `Python` crea una
        opción **al lado** de `python`. Medido: **7 de 48** etiquetas del modelo duplicaban una
        existente sólo por la caja o una tilde, y la propiedad ya tiene **183 opciones**.
        ⚠️ Si no se puede leer, devuelve `[]` y **no para la publicación**: publicar creando
        alguna opción de más es recuperable; no publicar deja el documento fuera del índice.
        """
        if self._opc_etq is not None:
            return self._opc_etq
        ds = str(fuente or os.environ.get("NOTION_DATA_SOURCE_ID", "")).strip()
        if not ds:
            return []
        try:
            esquema = self._notion_get(NOTION_FUENTE % ds) or {}
            prop = ((esquema.get("properties") or {}).get("Etiquetas") or {})
            opciones = ((prop.get("multi_select") or {}).get("options") or [])
            self._opc_etq = [str(o.get("name") or "").strip() for o in opciones
                             if str(o.get("name") or "").strip()]
        except Exception:
            self._opc_etq = []
        return self._opc_etq

    def publicar(self, fila):
        """Paso 5: crea la página en Notion y **devuelve su id** para que quede anotado.

        ⛔ Devolver el id no es comodidad: es lo que permite que, si la escritura de la bandera
        falla, la pasada siguiente **anote** en vez de crear una segunda página.
        ⚠️ El fichero adjunto (subida + embebido) **no** va aquí todavía: se dice y no se finge.
        """
        props, motivos = PN.propiedades(fila)
        if motivos:
            raise SystemExit("no se publica: " + " | ".join(motivos))
        _fuente = (str(fila.get("notion_data_source_id") or "").strip()
                   or self.fuente_de_datos())
        # ⛔ Con las opciones que YA hay: sin ellas, `casar_etiquetas` no puede reusar nada y
        #    cada `Python` crea una opción al lado de `python`.
        cuerpo, avisos = NA.cuerpo_pagina(
            _fuente, props, opciones_etiquetas=self.opciones_etiquetas(_fuente))
        if cuerpo is None:
            raise SystemExit("no se publica: " + " | ".join(avisos))
        # ⛔ La CARPETA primero, y sólo si no la hay ya. Crearla dos veces deja dos carpetas
        #    con el mismo nombre y nadie sabe cuál es la buena.
        #    ⚠️ Y NO se toca `drive_folder_created`: su propio código dice que esa bandera la
        #    decide el paso final «cuando el resto de la publicación esté completa». Aquí sólo se
        #    devuelve el id, que es un dato cierto: la carpeta existe.
        extra = {}
        if not str(fila.get("drive_folder_id") or "").strip():
            padre = DA.carpeta_ruta(self.leer_rutas(), fila.get("unit_key"),
                                    fila.get("subfolder_key"), fila.get("reserved_id"))
            cuerpo_c, motivos_c = DA.cuerpo_carpeta(fila.get("reference"), padre)
            if cuerpo_c is None:
                raise SystemExit("no se crea la carpeta: " + " | ".join(motivos_c))
            creada = self.drive.files().create(body=cuerpo_c, fields="id",
                                               supportsAllDrives=True).execute()
            fid = str((creada or {}).get("id") or "").strip()
            if not fid:
                raise SystemExit("Drive no devolvió el id de la carpeta: sin él no queda "
                                 "constancia y la pasada siguiente crearía otra")
            extra["drive_folder_id"] = fid
            extra["drive_folder_url"] = DA.url_de(fid)

        # ⛔ EL FICHERO, ANTES DE CREAR LA PÁGINA. Si se crea primero y la subida falla, queda
        #    una página **sin documento** y marcada como creada: el caso que nadie vuelve a mirar.
        subida = self._subir_fichero(fila)
        if subida:
            cuerpo["children"] = [{"object": "block", "type": "file",
                                   "file": {"type": "file_upload",
                                            "file_upload": {"id": subida}}}]

        r = self._notion(NOTION_CREAR, cuerpo) or {}
        pid = str(r.get("id") or "").strip()
        if not pid:
            raise SystemExit("Notion no devolvió el id de la página: no se puede anotar que "
                             "existe, y sin eso la pasada siguiente la crearía otra vez")
        # ⛔ Y el fichero se ARCHIVA en la carpeta del expediente. Hasta aquí seguía en la
        #    bandeja del formulario: la página de Notion apuntaba a algo que no estaba archivado.
        _carpeta = extra.get("drive_folder_id") or str(fila.get("drive_folder_id") or "").strip()
        if str(fila.get("source_drive_file_id") or "").strip() and _carpeta:
            _movido = self.mover_a_carpeta(fila, _carpeta)
            extra.update(_movido)
            # ⚠️ El id sale de LO QUE SE MOVIÓ, no de «el principal»: si el adjunto era un DOCX
            #    se anota en `drive_docx_file_id`, y buscarlo sólo por la otra clave dejaba la
            #    verificación mirando un `None` y plantando el expediente entero.
            _id_movido = (_movido.get("drive_primary_file_id")
                          or _movido.get("drive_docx_file_id"))
            # ⛔ Y se RELEE que esté dentro: `update` puede contestar bien y dejarlo donde estaba.
            if not self.verificar_en_carpeta(_id_movido, _carpeta):
                raise SystemExit("el fichero no consta en la carpeta del expediente tras "
                                 "moverlo: no se da por archivado")
            self.permiso_dominio(_id_movido)
        # ⛔ El resumen ejecutivo va FUERA de esa rama: un expediente sin fichero que mover
        #    tiene resumen igual, y colgarlo de ahí lo dejaba sin archivar sin decir nada.
        if _carpeta and not str(fila.get("drive_summary_file_id") or "").strip():
            extra.update(self.crear_resumen(fila, _carpeta))
        # ⛔ Y los ANEXOS, a la misma carpeta. Publicar sin ellos no da ningún error: el
        #    documento queda archivado y cerrado sin los ficheros que lo acompañan.
        if _carpeta:
            extra.update(self.copiar_anexos(fila, _carpeta))
        # ⛔ Y se ENLAZAN en la página. Copiarlos a Drive no es enlazarlos: un anexo archivado
        #    que la página no menciona no existe para quien lee el documento en Notion.
        #    ⚠️ Se enlazan **todos** los que consten, no sólo los copiados en esta pasada: si la
        #       anterior copió y se cortó antes de enlazar, esos se habrían quedado fuera.
        _anexos, _ = AX.finales(dict(fila, **extra))
        if _anexos:
            self.enlazar_anexos(pid, _anexos)

        extra["notion_page_id"] = pid
        extra["notion_page_url"] = str(r.get("url") or "")
        # ⛔ Y se RELEE: que la subida dijera `uploaded` no prueba que el bloque haya quedado en
        #    la página. Si no está, se dice — la página ya existe, así que no se puede deshacer,
        #    pero sí impedir que se marque como embebida.
        if subida and not self.verificar_embebido(pid, subida):
            raise SystemExit("la página %s se creó pero el fichero NO está dentro: queda "
                             "creada y hay que mirarla, no darla por publicada" % pid)
        return extra

    def _subir_fichero(self, fila):
        """Baja el fichero de Drive y lo sube a Notion. Devuelve el id de la subida, o `None`.

        ⚠️ `None` significa **no había fichero que subir**, y entonces la página se crea sin él.
        Si había y algo falla, **se lanza**: una página sin documento marcada como publicada es
        peor que no tenerla.
        ⛔ El tamaño se mira ANTES de descargar: bajarse 40 MB para descubrir que no caben es
        tiempo y memoria tirados, y el error llegaría con el fichero ya en RAM.
        """
        # ⛔⛔ EL PDF, NO EL DOCX. Casi todos los expedientes llegan en DOCX y el pipeline
        #    **genera un PDF**; ese PDF vive en `drive_primary_file_id`, y
        #    `source_drive_file_id` es el adjunto del formulario. Comprobado con la fila 12,
        #    cuyas notas dicen que el PDF bueno es `13A2NAK…` — justo lo que trae esa columna.
        #    ⚠️ Subir el DOCX **no da error**: Notion lo acepta y crea un bloque de fichero
        #       **que no se puede leer en la página**. Quien abra el documento vería un adjunto
        #       para descargar, que es justo lo que la página existe para evitar.
        #    ⚠️ Y si no hay PDF generado se sube el original: quedarse sin documento esperando
        #       un fichero que nadie va a generar es peor que un adjunto sin previsualización.
        fid = (str(fila.get("drive_primary_file_id") or "").strip()
               or str(fila.get("source_drive_file_id") or "").strip())
        if not fid:
            return None
        meta = self.drive.files().get(fileId=fid, fields="name,size",
                                      supportsAllDrives=True).execute() or {}
        if not NA.cabe(meta.get("size")):
            raise SystemExit("el fichero pesa %r y el tope de la subida directa son 20 MiB: "
                             "no se publica a medias" % (meta.get("size"),))
        nombre = str(meta.get("name") or fila.get("source_filename") or "documento.pdf")
        cuerpo, motivos = NA.cuerpo_subida(nombre)
        if cuerpo is None:
            raise SystemExit("no se sube el fichero: " + " | ".join(motivos))
        hueco = self._notion(NA.NOTION_SUBIDAS, cuerpo) or {}
        url = str(hueco.get("upload_url") or "").strip()
        sid = str(hueco.get("id") or "").strip()
        if not (url and sid):
            raise SystemExit("Notion no dio hueco de subida (id o upload_url): no se crea una "
                             "página sin el documento dentro")
        datos = self.drive.files().get_media(fileId=fid, supportsAllDrives=True).execute()
        r = self._subir(url, datos if isinstance(datos, bytes) else bytes(datos or b""),
                        nombre) or {}
        if str(r.get("status") or "").lower() != "uploaded":
            raise SystemExit("la subida no terminó (%r): la página quedaría sin documento"
                             % (r.get("status"),))
        return sid

    def verificar_embebido(self, pagina_id, subida_id):
        """¿El fichero está **de verdad** dentro de la página? Relee los bloques y lo busca.

        ⛔ EXISTE PORQUE «SUBIR» NO ES «VERIFICAR», que es la misma distinción que tumbó
        `drive_primary_file_verified`: que la subida diga `uploaded` prueba que el fichero llegó
        a Notion, **no** que haya quedado colgado de la página. Y en este proyecto ya está medido
        que una escritura puede no hacer nada y decir que sí.
        ⚠️ Se relee **la página**, no la subida: preguntarle a la subida por sí misma es la
        comprobación que no puede fallar.
        """
        pid = str(pagina_id or "").strip()
        if not pid:
            return False
        r = self._notion_get(NOTION_HIJOS % pid) or {}
        for b in (r.get("results") or []):
            f = (b.get("file") or {})
            if str((f.get("file_upload") or {}).get("id") or "") == str(subida_id):
                return True
        return False

    def enlazar_anexos(self, pagina_id, ids_copiados):
        """Engancha los anexos a la página como marcadores y **relee** que hayan quedado.

        ⛔ Copiarlos a Drive no es enlazarlos: un anexo archivado que la página no menciona **no
        existe** para quien lee el documento en Notion, que es donde el equipo lo lee.
        ⚠️ Un solo parche con todos: siete peticiones para siete anexos es siete veces la
        probabilidad de quedarse a medias, y a medias no hay forma de saber por dónde iba.
        """
        pid = str(pagina_id or "").strip()
        bloques = AX.bloques(ids_copiados)
        if not pid or not bloques:
            return False
        self._notion_patch(NOTION_HIJOS % pid, {"children": bloques})
        # ⛔ Y se RELEE: que el parche conteste bien no prueba que los bloques hayan quedado —
        #    la misma distinción que ya tumbó «subir es embeber» y «mover es verificar».
        r = self._notion_get(NOTION_HIJOS % pid) or {}
        puestas = set()
        for b in (r.get("results") or []):
            u = str((b.get("bookmark") or {}).get("url") or "").strip()
            if u:
                puestas.add(u)
        faltan = [b["bookmark"]["url"] for b in bloques
                  if b["bookmark"]["url"] not in puestas]
        if faltan:
            raise SystemExit("la página %s no muestra %d anexo(s) tras enlazarlos: quedan "
                             "archivados en Drive y sin mencionar donde se leen" % (pid, len(faltan)))
        return True

    def mover_a_carpeta(self, fila, carpeta_id):
        """Mueve el fichero de origen a la carpeta del expediente. Devuelve su id.

        ⛔ **Mover, no copiar.** Copiar deja dos ficheros iguales en Drive — el de la bandeja de
        entrada del formulario y el archivado — y a partir de ahí nadie sabe cuál es el bueno ni
        cuál se corrige. El pipeline real ya trata la sustitución como un envío NUEVO enlazado al
        original; duplicar aquí rompería esa cuenta.
        ⚠️ `addParents`/`removeParents` en la MISMA llamada: en dos, un corte en medio deja el
        fichero colgando de las dos carpetas o de ninguna.
        """
        fid = str(fila.get("source_drive_file_id") or "").strip()
        destino = str(carpeta_id or "").strip()
        if not (fid and destino):
            raise SystemExit("no se mueve el fichero: falta el de origen (%r) o la carpeta (%r)"
                             % (fid, destino))
        meta = self.drive.files().get(fileId=fid, fields="parents,mimeType",
                                      supportsAllDrives=True).execute() or {}
        padres = ",".join(meta.get("parents") or [])
        self.drive.files().update(fileId=fid, addParents=destino, removeParents=padres,
                                  fields="id,parents", supportsAllDrives=True).execute()
        # ⛔⛔ `drive_primary_file_id` significa **el PDF**, no «lo que se haya movido».
        #    Comprobado con la fila 12: sus notas dicen que el PDF bueno es `13A2NAK…`, justo
        #    lo que trae esa columna. Y lo que se mueve es el adjunto del formulario, que en
        #    casi todos los expedientes reales es un **DOCX**. Escribir ahí el DOCX no da
        #    ningún error y deja la columna significando **dos cosas según quién la escribió**,
        #    que es la peor clase de dato: el que parece bueno.
        #    ⚠️ Un `mimeType` que no se entiende **no** se da por PDF: fallaría hacia mentir.
        #    ⬜ Generar el PDF a partir del DOCX **no se hace todavía**: la conversión de Drive
        #       deja un documento de Google intermedio, y dónde vive eso es decisión de Daniel.
        if str(meta.get("mimeType") or "").strip().lower() == "application/pdf":
            return {"drive_primary_file_id": fid}
        return {"drive_docx_file_id": fid}

    def verificar_en_carpeta(self, fichero_id, carpeta_id):
        """¿El fichero está **de verdad** dentro de esa carpeta? Se relee de Drive.

        ⛔ Mover no es verificar, igual que subir no era embeber. Y en este proyecto está medido
        que una escritura puede no hacer nada y decir que sí: `update` puede contestar bien y
        dejar el fichero donde estaba.
        """
        fid, cid = str(fichero_id or "").strip(), str(carpeta_id or "").strip()
        if not (fid and cid):
            return False
        meta = self.drive.files().get(fileId=fid, fields="parents",
                                      supportsAllDrives=True).execute() or {}
        return cid in (meta.get("parents") or [])

    def permiso_dominio(self, fichero_id, dominio=None):
        """Comparte el fichero con el dominio del equipo y **relee** que el permiso está.

        ⚠️ El dominio sale del entorno: cablearlo aquí lo dejaría escrito en un repo que se
        publica, y cambiarlo obligaría a tocar código.
        """
        fid = str(fichero_id or "").strip()
        dom = str(dominio or os.environ.get("DOMINIO_EQUIPO", "")).strip()
        if not (fid and dom):
            raise SystemExit("no se comparte: falta el fichero (%r) o `DOMINIO_EQUIPO` (%r)"
                             % (fid, dom))
        self.drive.permissions().create(
            fileId=fid, supportsAllDrives=True, sendNotificationEmail=False,
            body={"type": "domain", "role": "reader", "domain": dom}).execute()
        r = self.drive.permissions().list(fileId=fid, fields="permissions(type,domain,role)",
                                          supportsAllDrives=True).execute() or {}
        for pm in (r.get("permissions") or []):
            if pm.get("type") == "domain" and pm.get("domain") == dom:
                return True
        raise SystemExit("el permiso de dominio no consta tras crearlo: el equipo no podría "
                         "abrir el documento y la página diría que sí")

    def copiar_anexos(self, fila, carpeta_id):
        """Copia a la carpeta del expediente los anexos que falten. `{}` si no hay nada que hacer.

        ⛔ **Copiar, no mover.** El origen es el adjunto del formulario, que es de quien lo
        subió: moverlo se lo quita de su Drive. El documento principal sí se mueve —es el
        expediente—; un anexo se copia, y por eso hay dos listas de ids y no una.
        ⚠️ Y los ya copiados **no se vuelven a copiar**: cada pasada dejaría siete duplicados
        más en la carpeta, y en Drive nadie los va a borrar.
        """
        destino = str(carpeta_id or "").strip()
        ids, _ = AX.origen(fila)
        if not ids or not destino or not AX.faltan(fila):
            return {}
        copiados = []
        for fid in ids:
            r = self.drive.files().copy(
                fileId=fid, body={"parents": [destino]}, fields="id",
                supportsAllDrives=True).execute() or {}
            cid = str(r.get("id") or "").strip()
            if not cid:
                raise SystemExit("Drive no devolvió el id de la copia del anexo %s: sin él no "
                                 "queda constancia y la pasada siguiente lo copiaría otra vez"
                                 % fid)
            copiados.append(cid)
        return AX.cambios(copiados)

    def crear_resumen(self, fila, carpeta_id):
        """Escribe el resumen ejecutivo como fichero de texto dentro de la carpeta.

        ⛔ El resumen **ya existe**: lo genera el paso 2 y viaja en `executive_summary`. Aquí no
        se inventa nada — se archiva lo que hay. Si no hay resumen, **no se crea un fichero
        vacío**: un documento con un resumen en blanco es peor que uno sin resumen, porque el que
        lo abra cree que ya está mirado.
        """
        texto = str(fila.get("executive_summary") or "").strip()
        destino = str(carpeta_id or "").strip()
        if not texto or not destino:
            return {}
        ref = str(fila.get("reference") or "documento").strip()
        r = self.drive.files().create(
            body={"name": u"%s — resumen.txt" % ref, "parents": [destino]},
            media_body=self._medio(texto.encode("utf-8"), "text/plain"),
            fields="id", supportsAllDrives=True).execute() or {}
        sid = str(r.get("id") or "").strip()
        if not sid:
            raise SystemExit("Drive no devolvió el id del resumen: sin él no queda constancia y "
                             "la pasada siguiente crearía otro")
        return {"drive_summary_file_id": sid}

    def registrar(self, fila):
        """Paso 6: añade la fila al Libro de Datos y devuelve dónde quedó."""
        celda, motivos = LD.fila(fila)
        if motivos:
            raise SystemExit("no se registra en el Libro: " + " | ".join(motivos))
        rango = u"%s!A:C" % SA.nombre_pestana(PESTANA_LIBRO)
        r = (self.sheets.spreadsheets().values()
             .append(spreadsheetId=HOJA_LIBRO, range=rango,
                     valueInputOption="USER_ENTERED",
                     body={"values": [celda]}).execute())
        donde = ((r.get("updates") or {}).get("updatedRange") or "")
        n = SA.fila_de_rango(donde)
        if n is None:
            raise SystemExit("el Libro no dijo en qué fila quedó (%r): sin eso no queda prueba "
                             "de que se escribió, y la pasada siguiente lo registraría otra vez"
                             % donde)
        # ⛔ UN NÚMERO, que es lo que llevan las filas reales de `SOLICITUDES` (169, 171, 172),
        #    no el rango A1 que devuelve `append`. Medido el 29/09.
        return {"base_database_row": n}

    def cerrar(self, fila):
        """Paso 7: no hay nada que hacer **en el mundo** — el cierre es la bandera.

        ⚠️ Está escrito y vacío a propósito: sin el método, el ejecutor diría «`servicios.cerrar`
        no existe» y ningún expediente se cerraría nunca.
        """
        return {}


if __name__ == "__main__":  # pragma: no cover
    print("Las manos del pipeline. Para probarlas: python scripts/test_servicios.py")
