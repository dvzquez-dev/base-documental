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

ALCANCES = ["https://www.googleapis.com/auth/spreadsheets"]

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


class Servicios(object):
    """Lo que el ejecutor llama. Cada método hace **una** cosa y no decide ninguna.

    ⚠️ Todo lo que toca el mundo entra por el constructor (`sheets`, `notion`), así que el banco
    pasa dobles y **no se abre una conexión**. Sin argumentos, construye los de verdad — y eso
    sólo ocurre cuando alguien lo pide explícitamente.
    """

    def __init__(self, sheets=None, notion=None):
        self._sheets = sheets
        self._notion = notion or http_notion

    @property
    def sheets(self):
        if self._sheets is None:
            self._sheets = cliente_sheets()
        return self._sheets

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
        r = self._notion(NOTION_CREAR, cuerpo) or {}
        pid = str(r.get("id") or "").strip()
        if not pid:
            raise SystemExit("Notion no devolvió el id de la página: no se puede anotar que "
                             "existe, y sin eso la pasada siguiente la crearía otra vez")
        return {"notion_page_id": pid, "notion_page_url": str(r.get("url") or "")}

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
        return {"base_database_row": donde}

    def cerrar(self, fila):
        """Paso 7: no hay nada que hacer **en el mundo** — el cierre es la bandera.

        ⚠️ Está escrito y vacío a propósito: sin el método, el ejecutor diría «`servicios.cerrar`
        no existe» y ningún expediente se cerraría nunca.
        """
        return {}


if __name__ == "__main__":  # pragma: no cover
    print("Las manos del pipeline. Para probarlas: python scripts/test_servicios.py")
