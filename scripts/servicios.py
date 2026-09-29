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
NOTION_VERSION = "2022-06-28"
NOTION_CREAR = "https://api.notion.com/v1/pages"

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


class Servicios(object):
    """Lo que el ejecutor llama. Cada método hace **una** cosa y no decide ninguna.

    ⚠️ Todo lo que toca el mundo entra por el constructor (`sheets`, `notion`), así que el banco
    pasa dobles y **no se abre una conexión**. Sin argumentos, construye los de verdad — y eso
    sólo ocurre cuando alguien lo pide explícitamente.
    """

    def __init__(self, sheets=None, notion=None, drive=None, subir=None):
        self._sheets = sheets
        self._notion = notion or http_notion
        self._drive = drive
        # El envio del fichero en multipart: aparte del POST de JSON, porque es otra forma de
        # peticion y el banco necesita doblarla sola.
        self._subir = subir or http_subir

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

    def publicar(self, fila):
        """Paso 5: crea la página en Notion y **devuelve su id** para que quede anotado.

        ⛔ Devolver el id no es comodidad: es lo que permite que, si la escritura de la bandera
        falla, la pasada siguiente **anote** en vez de crear una segunda página.
        ⚠️ El fichero adjunto (subida + embebido) **no** va aquí todavía: se dice y no se finge.
        """
        props, motivos = PN.propiedades(fila)
        if motivos:
            raise SystemExit("no se publica: " + " | ".join(motivos))
        cuerpo, avisos = NA.cuerpo_pagina(fila.get("notion_data_source_id") or
                                          os.environ.get("NOTION_DATA_SOURCE_ID", ""),
                                          props)
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
        extra["notion_page_id"] = pid
        extra["notion_page_url"] = str(r.get("url") or "")
        return extra

    def _subir_fichero(self, fila):
        """Baja el fichero de Drive y lo sube a Notion. Devuelve el id de la subida, o `None`.

        ⚠️ `None` significa **no había fichero que subir**, y entonces la página se crea sin él.
        Si había y algo falla, **se lanza**: una página sin documento marcada como publicada es
        peor que no tenerla.
        ⛔ El tamaño se mira ANTES de descargar: bajarse 40 MB para descubrir que no caben es
        tiempo y memoria tirados, y el error llegaría con el fichero ya en RAM.
        """
        fid = str(fila.get("source_drive_file_id") or "").strip()
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
