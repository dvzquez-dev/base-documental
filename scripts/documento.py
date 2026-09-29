#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""El TEXTO del documento, para que el paso 2 no analice a ciegas.

Por qué existe
--------------
⛔ `analisis.prompt_de` le daba al modelo **los metadatos** —título, tipo, unidad, autor— y **ni
una línea del documento**. Con eso el resumen ejecutivo sale de adivinar por el título, que es
exactamente lo que el revisor no necesita: el título ya lo ve él. Un resumen así se lee bien y no
dice nada, que es el peor modo de fallo de este paso.

⚠️ **No es un lector nuevo de un formato que este repo ya abre**:
`fix_docx_publication_date.py` ya entra en los `.docx` con `zipfile` y parchea sus XML. Aquí se
usa el mismo camino —`word/document.xml`, los `<w:t>`, desescapar las entidades— para la
operación contraria: sacar el texto en vez de meterlo.

Lo que NO hace, y lo dice
-------------------------
⛔ **Los PDF no se leen aquí.** Extraer texto de un PDF necesita una dependencia y hoy no la hay.
Devolver `""` o basura haría que el modelo **resumiera la nada sin que nadie se enterara**, así
que se dice con todas las letras y el paso se planta.
⚠️ Y casi todos los expedientes reales llegan en **DOCX**, así que esto cubre el caso normal.

Cómo se prueba
--------------
`python scripts/test_documento.py` — sin red, con `.docx` de verdad construidos en memoria.
"""
import io
import os
import re
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding="utf-8")
    except Exception:  # pragma: no cover
        pass

# ⛔ El tope del texto que viaja en el encargo. Un documento de 200 páginas no cabe, y mandarlo
#    entero no falla: **el modelo lo trunca por su cuenta y no lo dice**. Aquí se recorta y se
#    deja constancia, que es la diferencia entre un resumen parcial sabido y uno silencioso.
TOPE = 40000

DOCUMENTO = "word/document.xml"
_TEXTO = re.compile(r"<w:t(?:\s[^>]*)?>(.*?)</w:t>", re.S)
_PARRAFO = re.compile(r"</w:p>")


def _xml_unescape(s):
    """Las cinco entidades de XML más las numéricas. Mismo criterio que el parcheador."""
    s = (s.replace("&lt;", "<").replace("&gt;", ">")
          .replace("&apos;", "'").replace("&quot;", '"'))
    s = re.sub(r"&#(\d+);", lambda m: unichr_(int(m.group(1))), s)
    s = re.sub(r"&#x([0-9a-fA-F]+);", lambda m: unichr_(int(m.group(1), 16)), s)
    # ⚠️ `&amp;` va **el último**: antes convertiría `&amp;lt;` en `<`.
    return s.replace("&amp;", "&")


def unichr_(n):
    try:
        return chr(n)
    except Exception:  # pragma: no cover
        return u""


def es_docx(nombre, datos):
    """¿Esto es un `.docx` que se puede abrir? Mira **dentro**, no la extensión."""
    if not datos:
        return False
    try:
        with zipfile.ZipFile(io.BytesIO(datos), "r") as z:
            return DOCUMENTO in z.namelist()
    except Exception:
        return False


def texto_docx(datos):
    """El texto de un `.docx`, con un salto de línea por párrafo. `None` si no se puede.

    ⛔ Los `<w:r>` de un mismo párrafo van **pegados** —Word parte una frase en varios runs por
    el formato— y los párrafos van **separados**. Sin lo segundo el documento sale como un churro
    de una línea y el modelo pierde la estructura, que es la mitad de lo que hay que resumir.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(datos), "r") as z:
            xml = z.read(DOCUMENTO).decode("utf-8", "replace")
    except Exception:
        return None
    # Se marca el fin de párrafo ANTES de recoger los `<w:t>`, que es lo que conserva la
    # estructura sin tener que parsear el XML entero.
    xml = _PARRAFO.sub(u"</w:p>\n<w:t>\u0000</w:t>", xml)
    trozos = [_xml_unescape(m.group(1)) for m in _TEXTO.finditer(xml)]
    crudo = u"".join(trozos).replace(u"\u0000", u"\n")
    lineas = [l.rstrip() for l in crudo.split(u"\n")]
    return u"\n".join(l for l in lineas if l.strip())


def texto_de(nombre, datos, tope=None):
    """`(texto, motivos)` del documento. `texto` es `None` cuando no hay nada que analizar.

    Los motivos **no son todos fatales**: el del recorte acompaña a un texto bueno. Lo que dice
    que no se puede analizar es que `texto` venga `None`.
    """
    tope = TOPE if tope is None else tope
    motivos = []
    n = str(nombre or "").strip().lower()

    if not datos:
        return None, [u"no hay fichero que leer"]

    if not es_docx(nombre, datos):
        if n.endswith(".pdf") or (isinstance(datos, bytes) and datos[:4] == b"%PDF"):
            return None, [u"el fichero es un PDF y aquí sólo se lee DOCX: sin una dependencia "
                          u"para extraer su texto, analizarlo sería resumir a ciegas"]
        return None, [u"no se puede abrir como DOCX (%r): no es un zip con %s dentro"
                      % (nombre, DOCUMENTO)]

    texto = texto_docx(datos)
    if not texto or not texto.strip():
        return None, [u"el documento está vacío: no tiene ni una palabra que resumir"]

    if len(texto) > tope:
        texto = texto[:tope]
        # ⛔ Se DICE. Un resumen hecho sobre una parte del documento no es el mismo resumen, y
        #    callarlo lo deja pasando por completo.
        motivos.append(u"el documento se ha recortado a %d caracteres para que quepa en el "
                       u"encargo: el resumen sale de esa parte, no del documento entero" % tope)
    return texto, motivos


if __name__ == "__main__":  # pragma: no cover
    print(u"El texto del documento. Para probarlo: python scripts/test_documento.py")
