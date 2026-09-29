#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DOCX → PDF, y **comprobar que el PDF es el bueno**. Una sola puerta.

Por qué existe
--------------
⛔ **Esto no es código nuevo.** Vivía dentro de `fix_docx_publication_date.py`
(`convert_docx_to_pdf` y `pdf_contiene_referencia`), que lleva meses convirtiendo de verdad como
GitHub Action. Se saca aquí para que **el pipeline lo use sin copiarlo** — Daniel, 30/09: *«ni se
te ocurra andar repitiendo código en lugar de reutilizarlo, q si no es imposible luego actualizar
el pipeline pq hay q acordarse de 20 localizaciones distintas»*.

⚠️ Y hasta hoy **no tenían banco**: se probaban corriendo el Action contra documentos reales.

Lo que cambia respecto al original, y por qué
---------------------------------------------
⛔ **Devuelven motivos en vez de lanzar.** El original hacía `raise RuntimeError` y eso está bien
para un Action que procesa un documento; el pipeline recorre decenas y **un fallo no puede tirar
la pasada**.
⛔⛔ **Y `pdf_lleva` distingue `None` de `False`, que el original ya hacía bien y es lo más fácil
de perder**: `False` es *«el PDF NO lleva la referencia»* → hay que regenerar el documento.
`None` es *«no se pudo comprobar»* → hay que **instalar `pdftotext`**. Se arreglan en sitios
distintos, así que aplastar el `None` contra `False` manda a arreglar lo que no es (§3c-24).

Qué hace falta en la máquina
----------------------------
```
apt-get install -y libreoffice poppler-utils
```
⚠️ En el minipc **no los pone nadie**: hoy los instala el runner de GitHub Actions. Está apuntado
en `docs/minipc-especificaciones.md` del panel.

Cómo se prueba
--------------
`python scripts/test_pdf.py` — sin `soffice` ni `pdftotext` delante (el lanzador se inyecta).
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding="utf-8")
    except Exception:  # pragma: no cover
        pass

TIMEOUT_CONVERSION = 180
TIMEOUT_TEXTO = 120


def docx_a_pdf(docx, workdir, correr=None):
    """`(pdf_bytes, motivos)`. `pdf_bytes` es `None` si no se pudo convertir. **Nunca lanza.**"""
    correr = correr or subprocess.run
    if not docx:
        return None, [u"no hay DOCX que convertir"]
    entrada = os.path.join(workdir, "input.docx")
    try:
        with open(entrada, "wb") as f:
            f.write(docx)
    except Exception as e:
        return None, [u"no se pudo escribir el DOCX temporal: %s" % (e,)]

    try:
        r = correr(["soffice", "--headless", "--convert-to", "pdf", "--outdir", workdir,
                    entrada],
                   capture_output=True, text=True, timeout=TIMEOUT_CONVERSION)
    except FileNotFoundError:
        # ⛔ Se dice ASÍ, y no como «falló la conversión»: eso mandaría a mirar el documento en
        #    vez de la máquina. En el minipc es lo primero que va a pasar.
        return None, [u"no encuentro `soffice`: hay que instalar LibreOffice en esta máquina "
                      u"(`apt-get install -y libreoffice`)"]
    except Exception as e:
        return None, [u"LibreOffice no llegó a terminar: %s: %s" % (type(e).__name__, e)]

    if getattr(r, "returncode", 0) != 0:
        return None, [u"LibreOffice falló (código %s): %s"
                      % (r.returncode, ((r.stdout or "") + " " + (r.stderr or "")).strip())]

    salida = os.path.join(workdir, "input.pdf")
    if not os.path.exists(salida):
        # ⚠️ Salir con 0 y no dejar el fichero pasa de verdad con LibreOffice.
        return None, [u"LibreOffice dijo que sí y no dejó ningún PDF en %r" % (workdir,)]
    try:
        with open(salida, "rb") as f:
            return f.read(), []
    except Exception as e:
        return None, [u"el PDF se generó y no se pudo leer: %s" % (e,)]


def pdf_lleva(pdf, referencia, workdir, correr=None):
    """¿El PDF lleva esa referencia dentro? `True` · `False` · **`None` = no se pudo comprobar**.

    ⛔ «Convertir» no es «convertir bien»: un PDF generado del documento equivocado pesa igual y
    tiene la misma pinta. Lo único que lo distingue es abrirlo y buscar la referencia.
    ⛔⛔ El `None` es la mitad que más se pierde. Ver la cabecera.
    """
    correr = correr or subprocess.run
    if not pdf or not str(referencia or "").strip():
        return None
    ruta = os.path.join(workdir, "verify.pdf")
    try:
        with open(ruta, "wb") as f:
            f.write(pdf)
    except Exception:
        return None
    try:
        r = correr(["pdftotext", ruta, "-"], capture_output=True, text=True,
                   timeout=TIMEOUT_TEXTO)
    except Exception:
        return None
    if getattr(r, "returncode", 0) != 0:
        return None
    return str(referencia).strip() in (r.stdout or "")


def medio_pdf(datos):
    """El `media_body` para subir un PDF a Drive. **Sin respaldo, a propósito.**

    ⛔ Si `googleapiclient` no está, esto **lanza**. La tentación era devolver `None` y seguir:
    eso crea en Drive un fichero **vacío con su id**, y quien lo recibe (`publicar`) lo sube a
    Notion tan contento. Un PDF de 0 bytes con buena pinta es peor que no tenerlo.
    ⚠️ Vive aquí y no dentro de `servicios` para que el banco pueda sustituirlo: es la misma
    costura que `correr=` en `modelo` y en las dos funciones de arriba.
    """
    import io as _io

    from googleapiclient.http import MediaIoBaseUpload

    return MediaIoBaseUpload(_io.BytesIO(datos), mimetype="application/pdf", resumable=True)


if __name__ == "__main__":  # pragma: no cover
    print(u"DOCX a PDF. Para probarlo: python scripts/test_pdf.py")
