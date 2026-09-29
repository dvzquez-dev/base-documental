#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Lo que hay que pedirle a Drive, construido. Sin tocar la red.

De dónde sale esta semántica
----------------------------
📏 **No está inventada: está copiada del código que ya lo hace**, en este mismo repo
(`fix_docx_publication_date.py`, 29/09/2026). Los conectores de Drive de esta sesión están sin
credencial, así que la fuente es el código, que es mejor fuente que una suposición:

- Cada expediente tiene **su propia carpeta**, y se llama **como la referencia**
  (`Informe_S-2011_26`). Confirmado además leyendo `SOLICITUDES`: `drive_folder_id` es distinto
  en cada fila.
- Esa carpeta cuelga de la **carpeta-ruta del subsistema**, que sale de `RUTAS` emparejando
  `unit_key` + `subfolder_key` y **el rango que contiene el `reserved_id`** — nunca por el dígito.
- `supportsAllDrives=True`, porque el destino puede estar en una unidad compartida.

⛔ **Y lo que NO se toca**: `drive_folder_created`. Su propio código lo dice — *«esa la decide
`05_publicar_aprobado` cuando el resto de la publicación esté completa»*. Crear la carpeta **no**
es publicar; confundirlo marca como publicado un expediente al que le falta todo lo demás.

Cómo se prueba
--------------
`python scripts/test_drive_api.py` — sin red ni credenciales.
"""
import sys

for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding="utf-8")
    except Exception:  # pragma: no cover
        pass

import libro_datos as LD

MIME_CARPETA = "application/vnd.google-apps.folder"
URL_CARPETA = "https://drive.google.com/drive/folders/%s"


def carpeta_ruta(rutas, unit_key, subfolder_key, reserved_id):
    """El `drive_folder_id` de la ruta (la carpeta PADRE), o `None`.

    ⛔ Se empareja **por el rango**, no por la segunda cifra: `uct/actas` va de 6301 a 6499 y el
    común de Aviónica de 2001 a 2199 — **dos rutas ocupan dos dígitos cada una**, así que deducir
    la subcarpeta del dígito fallaría justo en las actas, que son lo más frecuente.
    ⚠️ Y sólo valen las rutas **activas**: `propulsion/informes_tecnicos` está a `FALSE` y apunta
    a la carpeta del curso pasado. Archivar ahí sería archivar en el año que no es, sin error.
    """
    try:
        rid = int(reserved_id)
    except (TypeError, ValueError):
        return None
    for r in (rutas or []):
        if r.get("unit_key") != unit_key or r.get("subfolder_key") != subfolder_key:
            continue
        if str(r.get("active", "")).strip().upper() != "TRUE":
            continue
        try:
            ini, fin = int(r.get("range_start")), int(r.get("range_end"))
        except (TypeError, ValueError):
            continue
        if ini <= rid <= fin:
            return (r.get("drive_folder_id") or "").strip() or None
    return None


def cuerpo_carpeta(referencia, padre):
    """`(cuerpo, motivos)` para crear la carpeta del expediente.

    ⛔ El nombre tiene que ser **la referencia canónica**. Una carpeta con otro nombre no la
    encuentra quien la busque por el documento, y el pipeline no vuelve a mirarla: quedaría un
    documento archivado en un sitio que nadie relaciona con él.
    """
    motivos = []
    ref = str(referencia or "").strip()
    if not LD.es_canonica(ref):
        motivos.append(u"la referencia %r no es canónica: la carpeta se llamaría de una forma "
                       u"que nadie va a buscar" % ref)
    padre = str(padre or "").strip()
    if not padre:
        motivos.append(u"sin carpeta-ruta: la del expediente colgaría de la raíz de Drive, "
                       u"fuera del árbol del subsistema")
    if motivos:
        return None, motivos
    return {"name": ref, "mimeType": MIME_CARPETA, "parents": [padre]}, []


def url_de(folder_id):
    """La URL que se guarda en `drive_folder_url`, o `None`."""
    fid = str(folder_id or "").strip()
    return (URL_CARPETA % fid) if fid else None


if __name__ == "__main__":  # pragma: no cover
    print("Lo que se le pide a Drive. Para probarlo: python scripts/test_drive_api.py")
