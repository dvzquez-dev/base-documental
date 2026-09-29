#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Banco de `pdf.py`: convertir el DOCX a PDF y **comprobar que el PDF es el bueno**.

⛔ Las dos funciones NO son nuevas: vivían dentro de `fix_docx_publication_date.py`, que lleva
meses convirtiendo de verdad. Se sacan a una puerta única para que el pipeline las use **sin
copiarlas** — Daniel: *«ni se te ocurra andar repitiendo código en lugar de reutilizarlo, q si no
es imposible luego actualizar el pipeline pq hay q acordarse de 20 localizaciones distintas»*.
Y el banco existe porque hasta hoy **no tenían ninguno**: se probaban corriendo el Action.

⚠️ Sin `soffice` ni `pdftotext` delante: el lanzador se inyecta.
"""
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding="utf-8")
    except Exception:
        pass

import pdf as P

fallos = []
hechas = [0]


def ok(cond, que):
    hechas[0] += 1
    if not cond:
        fallos.append(que)


class Hijo(object):
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def correr_que(resultado, escribe=None):
    """Lanzador de mentira. `escribe` = (nombre, bytes) que deja en el `outdir`, como soffice."""
    visto = {}

    def correr(cmd, **kw):
        visto["cmd"] = list(cmd)
        visto["kw"] = dict(kw)
        if escribe:
            # soffice deja el PDF en `--outdir`.
            d = cmd[cmd.index("--outdir") + 1] if "--outdir" in cmd else tempfile.gettempdir()
            with open(os.path.join(d, escribe[0]), "wb") as f:
                f.write(escribe[1])
        if isinstance(resultado, Exception):
            raise resultado
        return resultado

    return correr, visto


# ── 1. La conversión ───────────────────────────────────────────────────────────────────────
tmp = tempfile.mkdtemp()
c, v = correr_que(Hijo(0), escribe=("input.pdf", b"%PDF-1.7 convertido"))
datos, motivos = P.docx_a_pdf(b"PK\x03\x04 docx de mentira", tmp, correr=c)
ok(datos == b"%PDF-1.7 convertido", u"⛔ no devuelve el PDF convertido: %r" % (datos,))
ok(motivos == [], u"una conversión buena no da motivos: %r" % (motivos,))
ok(v["cmd"][0] == "soffice" and "--headless" in v["cmd"],
   u"⛔ no llama a LibreOffice headless: %r" % (v["cmd"],))
ok("--convert-to" in v["cmd"] and v["cmd"][v["cmd"].index("--convert-to") + 1] == "pdf",
   u"no pide PDF: %r" % (v["cmd"],))
ok(v["kw"].get("timeout"), u"⛔ sin tope de tiempo: LibreOffice colgado para el pipeline entero")

# ⛔ Si LibreOffice falla, NO se devuelve un PDF a medias: se dice, con lo que dijo él.
c, _ = correr_que(Hijo(1, "", "no se pudo cargar el filtro"))
d2, m2 = P.docx_a_pdf(b"x", tempfile.mkdtemp(), correr=c)
ok(d2 is None, u"⛔ devuelve algo con LibreOffice en rojo: %r" % (d2,))
ok(m2 and "filtro" in " ".join(m2), u"se pierde lo que dijo LibreOffice: %r" % (m2,))

# ⛔ Y si no está instalado, se dice ASÍ — no como «falló la conversión», que manda a mirar el
#    documento en vez de la máquina. En el minipc esto es lo primero que va a pasar.
c, _ = correr_que(FileNotFoundError("soffice"))
d3, m3 = P.docx_a_pdf(b"x", tempfile.mkdtemp(), correr=c)
ok(d3 is None and m3, u"sin soffice no revienta")
ok(m3 and "LibreOffice" in " ".join(m3) and "instal" in " ".join(m3).lower(),
   u"⛔ el motivo no dice que falta INSTALARLO: manda a mirar el documento: %r" % (m3,))

# ⚠️ Y si soffice sale con 0 pero no deja el fichero, tampoco se inventa nada.
c, _ = correr_que(Hijo(0))
d4, m4 = P.docx_a_pdf(b"x", tempfile.mkdtemp(), correr=c)
ok(d4 is None and m4, u"⛔ soffice dijo que sí y no hay PDF, y no se canta: %r" % (m4,))
# ⛔⛔ Y hay que exigir QUÉ MOTIVO: por los dos caminos sale `None`, así que mirar sólo el `None`
#    deja CIEGA la comprobación de que el fichero existe. «No dejó ningún PDF» manda a mirar
#    LibreOffice; «se generó y no se pudo leer» manda a mirar el disco. Son dos averías.
ok(m4 and "no dejó" in " ".join(m4),
   u"⛔⛔ el motivo no dice que LibreOffice no dejó el fichero: manda a mirar el disco cuando el "
   u"problema es la conversión: %r" % (m4,))
ok(m4 and "no se pudo leer" not in " ".join(m4),
   u"⛔ dice que el PDF se generó cuando no se generó: %r" % (m4,))
ok(P.docx_a_pdf(b"", tmp, correr=c)[0] is None, u"sin docx no hay PDF")

# ── 2. La verificación ─────────────────────────────────────────────────────────────────────
# ⛔ «Convertir» no es «convertir bien»: el PDF se abre y se busca la referencia dentro. Un PDF
#    generado del documento equivocado pesa igual y tiene la misma pinta.
c, _ = correr_que(Hijo(0, u"Informe_S-2011_26\nMemoria técnica"))
ok(P.pdf_lleva(b"%PDF", "Informe_S-2011_26", tempfile.mkdtemp(), correr=c) is True,
   u"⛔ no reconoce la referencia dentro del PDF")
c, _ = correr_que(Hijo(0, u"otra cosa"))
ok(P.pdf_lleva(b"%PDF", "Informe_S-2011_26", tempfile.mkdtemp(), correr=c) is False,
   u"⛔ da por bueno un PDF que NO lleva la referencia")
# ⛔⛔ Y «no se pudo comprobar» es `None`, NO `False`: son dos cosas distintas y se arreglan
#    distinto. `False` manda a regenerar el documento; `None` manda a instalar `pdftotext`.
#    Aplastarlo contra `False` es el «no lo sé leído como un dato» de §3c-24.
c, _ = correr_que(FileNotFoundError("pdftotext"))
ok(P.pdf_lleva(b"%PDF", "R", tempfile.mkdtemp(), correr=c) is None,
   u"⛔⛔ sin `pdftotext` contesta False en vez de None: «no lo sé» no es «no está»")
c, _ = correr_que(Hijo(1, "", "roto"))
ok(P.pdf_lleva(b"%PDF", "R", tempfile.mkdtemp(), correr=c) is None,
   u"un pdftotext que falla es «no lo sé», no «no está»")
c, _ = correr_que(subprocess.TimeoutExpired(["pdftotext"], 1))
ok(P.pdf_lleva(b"%PDF", "R", tempfile.mkdtemp(), correr=c) is None,
   u"un pdftotext que se cuelga es «no lo sé»")
ok(P.pdf_lleva(b"%PDF", "", tempfile.mkdtemp(), correr=correr_que(Hijo(0, "x"))[0]) is None,
   u"⛔ sin referencia contra la que comparar no se afirma nada")
ok(P.pdf_lleva(b"", "R", tempfile.mkdtemp(), correr=correr_que(Hijo(0, "R"))[0]) is None,
   u"sin PDF no se afirma nada")

print("%d comprobaciones" % hechas[0])
if fallos:
    print("\n%d ROJO(S):" % len(fallos))
    for f_ in fallos:
        print("  - %s" % f_)
    sys.exit(1)
print("verde")
