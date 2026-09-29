#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Banco de `documento.py`: sacar el TEXTO del fichero para que el paso 2 no analice a ciegas.

⛔ Por qué hace falta: `analisis.prompt_de` le daba al modelo **los metadatos** —título, tipo,
unidad— y ni una línea del documento. Con eso el resumen ejecutivo sale de adivinar por el
título, que es exactamente lo que el revisor no necesita: él ya ve el título.

⚠️ Los DOCX se abren con `zipfile` y los `<w:t>`, igual que `fix_docx_publication_date.py` hace
para parchearlos. No es un lector nuevo de un formato que ya se abre en este repo.
"""
import io
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding="utf-8")
    except Exception:
        pass

import documento as DOC

fallos = []
hechas = [0]


def ok(cond, que):
    hechas[0] += 1
    if not cond:
        fallos.append(que)


def docx(parrafos, extra=None):
    """Un .docx de verdad en memoria: un zip con `word/document.xml`."""
    cuerpo = u"".join(
        u"<w:p>" + u"".join(u'<w:r><w:t xml:space="preserve">%s</w:t></w:r>' % t for t in p)
        + u"</w:p>" for p in parrafos)
    xml = (u'<?xml version="1.0"?><w:document '
           u'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
           u"<w:body>%s</w:body></w:document>" % cuerpo)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", xml.encode("utf-8"))
        for k, v in (extra or {}).items():
            z.writestr(k, v)
    return buf.getvalue()


# ── 1. Un DOCX normal ──────────────────────────────────────────────────────────────────────
D = docx([[u"Memoria Técnica de Aviónica"],
          [u"Este documento describe ", u"la placa de vuelo."],
          [u"Sección 2: ensayos."]])
t, motivos = DOC.texto_de("memoria.docx", D)
ok(motivos == [], u"un docx normal no debería dar motivos: %r" % (motivos,))
ok(u"Memoria Técnica de Aviónica" in (t or ""), u"⛔ no saca el texto: %r" % (t,))
# ⛔ Los `<w:r>` de un mismo párrafo van PEGADOS (Word parte una frase en varios runs por el
#    formato), pero los párrafos van SEPARADOS. Sin eso el documento sale como un churro de una
#    línea y el modelo pierde la estructura, que es la mitad de lo que resume.
ok(u"Este documento describe la placa de vuelo." in (t or ""),
   u"⛔ parte una frase que Word tenía en dos runs: %r" % (t,))
ok(u"vuelo.\nSección 2" in (t or "") or u"vuelo.\n\nSección 2" in (t or ""),
   u"⛔ no separa los párrafos: el documento sale como una sola línea: %r" % (t,))

# ⚠️ Las entidades XML se desescapan: `&amp;` es `&`, y en este equipo hay unidades con `&`.
D2 = docx([[u"Estructuras &amp; Aerodin&#225;mica"]])
t2, _ = DOC.texto_de("x.docx", D2)
ok(u"Estructuras & Aerodin" in (t2 or ""),
   u"⛔ no desescapa las entidades XML: %r" % (t2,))

# ── 2. Lo que NO es un DOCX ────────────────────────────────────────────────────────────────
# ⛔ Un PDF no se lee aquí, y decirlo es lo correcto: devolver basura o texto vacío haría que el
#    modelo resumiera la nada **sin que nadie se enterara**.
t3, m3 = DOC.texto_de("informe.pdf", b"%PDF-1.7\n1 0 obj\n")
ok(t3 is None, u"⛔ devuelve algo para un PDF: el modelo resumiría basura")
ok(m3 and "PDF" in " ".join(m3), u"el motivo no dice que es un PDF: %r" % (m3,))
# ⚠️ Y unos bytes que no son ni zip tampoco revientan.
t4, m4 = DOC.texto_de("x.docx", b"esto no es un zip")
ok(t4 is None and m4, u"⛔ un fichero roto no se dice: %r / %r" % (t4, m4))
ok(DOC.texto_de("x.docx", None) == (None, DOC.texto_de("x.docx", None)[1]),
   u"sin datos no revienta")
ok(DOC.texto_de("x.docx", b"")[0] is None, u"unos bytes vacíos no dan texto")
# ⚠️ Un zip SIN `word/document.xml` no es un docx aunque se llame así.
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w") as z:
    z.writestr("otra/cosa.xml", "<a/>")
t5, m5 = DOC.texto_de("x.docx", buf.getvalue())
ok(t5 is None and m5, u"⛔ un zip sin `word/document.xml` pasa por docx: %r" % (t5,))
# ⛔⛔ Y hay que exigir QUÉ MOTIVO da, no sólo que no haya texto: por los dos caminos sale `None`,
#    así que comprobar el texto deja CIEGA la mutación que da por docx cualquier zip. Los dos
#    motivos mandan a sitios distintos — «no es un zip con word/document.xml» manda a mirar el
#    FICHERO; «está vacío» manda a mirar el DOCUMENTO — y quien lo arregle necesita el bueno.
ok(m5 and DOC.DOCUMENTO in " ".join(m5),
   u"⛔⛔ el motivo no dice que falta %s: manda a mirar el documento cuando el problema es el "
   u"fichero: %r" % (DOC.DOCUMENTO, m5))
ok(m5 and not any("vac" in x.lower() for x in m5),
   u"⛔ dice que el documento está vacío cuando lo que pasa es que no es un docx: %r" % (m5,))
# ⚠️ Y `es_docx` se pregunta directamente, que es donde vive la decisión.
ok(DOC.es_docx("x.docx", buf.getvalue()) is False,
   u"⛔ `es_docx` da por bueno un zip que no lleva %s dentro" % DOC.DOCUMENTO)
ok(DOC.es_docx("x.docx", D) is True, u"⛔ `es_docx` no reconoce un docx de verdad")

# ⚠️ Un docx con párrafos VACÍOS no es texto: resumir eso es resumir nada.
t6, m6 = DOC.texto_de("x.docx", docx([[u"   "], [u""]]))
ok(t6 is None, u"⛔ da por bueno un documento sin una palabra: %r" % (t6,))
ok(m6 and "vac" in " ".join(m6).lower(), u"el motivo no dice que está vacío: %r" % (m6,))

# ── 3. El recorte ──────────────────────────────────────────────────────────────────────────
# ⛔ Un documento de 200 páginas no cabe en el encargo. Se recorta — pero **se dice**, porque un
#    resumen hecho sobre el 5 % de un documento no es el mismo resumen y nadie lo sabría.
LARGO = docx([[u"palabra " * 50] for _ in range(400)])
t7, m7 = DOC.texto_de("x.docx", LARGO, tope=2000)
ok(t7 is not None and len(t7) <= 2000 + 200,
   u"⛔ no recorta: el encargo se iría de tamaño (%r)" % (len(t7 or ""),))
ok(m7 and any("recort" in x.lower() for x in m7),
   u"⛔ recorta y NO lo dice: el resumen saldría de una parte del documento y nadie lo sabría: %r"
   % (m7,))
ok(t7 and t7.startswith(u"palabra"), u"el recorte no empieza por el principio: %r" % (t7[:30],))
# ⚠️ Y uno que cabe no dice que se recortó.
t8, m8 = DOC.texto_de("x.docx", D, tope=100000)
ok(not any("recort" in x.lower() for x in m8),
   u"⛔ dice que recortó un documento que cabía entero: %r" % (m8,))
ok(DOC.TOPE > 1000, u"el tope por defecto es absurdamente pequeño: %r" % (DOC.TOPE,))

print("%d comprobaciones" % hechas[0])
if fallos:
    print("\n%d ROJO(S):" % len(fallos))
    for f_ in fallos:
        print("  - %s" % f_)
    sys.exit(1)
print("verde")
