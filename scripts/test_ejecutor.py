#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Banco de `ejecutor.py`. Sin red, sin credenciales, sin reloj.

⛔ El doble APUNTA lo que le piden y el banco comprueba **qué** le llegó, no sólo que se llamara.
Un doble más pobre que el real es como pasan desapercibidos los fallos de verdad: esta misma noche
un doble que devolvía menos de lo que devuelve el backend puso 4 pasadas buenas en rojo.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding="utf-8")
    except Exception:
        pass

import cierre as C
import ejecutor as E
import pipeline as P

fallos = []
hechas = [0]


def ok(cond, que):
    hechas[0] += 1
    if not cond:
        fallos.append(que)


T, F = "TRUE", "FALSE"


def fila(valores, rid="R-1"):
    d = dict(zip(C.BANDERAS, valores))
    d["request_id"] = rid
    return d


def sin(base, **kw):
    d = dict(base)
    d.update(kw)
    return d


# 📏 Filas reales de SOLICITUDES (AE2:AW8).
CERRADA_VACIA = fila([T, F, F, F, F, F, F, F, F, F, F, F, F, F, F, F, F, F, T], "R-real-2")
CAMBIOS = fila([T, T, T, T, T, F, F, T, F, F, F, F, F, F, F, F, F, F, F], "R-real-3")
PUBLICADA = fila([T, T, T, T, T, T, F, F, T, T, T, T, T, T, T, T, T, T, T], "R-real-4")

SIN_ANALIZAR = sin(CAMBIOS, analyzed=F, changes_requested=F)
POR_PUBLICAR = sin(PUBLICADA, closed=F, notion_page_created=F, base_database_registered=F)
SOLO_LIBRO = sin(PUBLICADA, closed=F, base_database_registered=F)
POR_CERRAR = sin(PUBLICADA, closed=F)


class Doble(object):
    """Apunta qué le pidieron y con qué fila. Puede reventar a la orden."""

    def __init__(self, revienta=None):
        self.llamadas = []
        self.revienta = revienta

    def _mete(self, nombre, f):
        self.llamadas.append((nombre, f.get("request_id") if isinstance(f, dict) else None))
        if self.revienta == nombre:
            raise RuntimeError(u"la hoja contestó 503")

    def analizar(self, f):
        self._mete("analizar", f)

    def publicar(self, f):
        self._mete("publicar", f)

    def registrar(self, f):
        self._mete("registrar", f)

    def cerrar(self, f):
        self._mete("cerrar", f)


# ── 1. El mapa de acciones ─────────────────────────────────────────────────────────────────
# ⛔ Toda acción del pipeline tiene que estar O atendida O declarada quieta. Si no, una acción
#    nueva se quedaría sin hacer nada y sin decirlo.
for a in P.ACCIONES:
    ok(a in E.ATIENDE or a in E.QUIETAS, "la acción %r no está ni atendida ni declarada quieta" % a)
ok(set(E.ATIENDE) & set(E.QUIETAS) == set(), "hay acciones a la vez atendidas y quietas")
ok(len(E.ATIENDE) + len(E.QUIETAS) == len(P.ACCIONES),
   "las acciones atendidas y quietas no suman las del pipeline")
# ⚠️ Las que se quedan quietas son decisiones, no olvidos: cada una lleva su por qué escrito.
ok(all(E.QUIETAS[a].strip() for a in E.QUIETAS), "alguna acción quieta no explica por qué")
ok(P.ESPERAR in E.QUIETAS and P.REVISAR in E.QUIETAS,
   "esperar decisión y revisar a mano tienen que quedarse quietas")
ok(P.ANALIZAR in E.ATIENDE and P.CERRAR in E.ATIENDE, "faltan acciones por atender")
# Las banderas que promete cada acción existen de verdad en la cabecera medida.
for a, (_n, bs) in sorted(E.ATIENDE.items()):
    for b in bs:
        ok(b in C.BANDERAS, "la acción %r promete la bandera %r, que no está en la cabecera" % (a, b))
ok(len(E.ATIENDE[P.PUBLICAR][1]) == 7,
   "publicar debería dejar 7 banderas (las 8 de publicación menos el Libro): %d"
   % len(E.ATIENDE[P.PUBLICAR][1]))
ok("base_database_registered" not in E.ATIENDE[P.PUBLICAR][1],
   "publicar promete el registro en el Libro, que es del paso 6")

# ── 2. Seco por defecto ────────────────────────────────────────────────────────────────────
# ⛔ Lo más importante del módulo: sin `aplicar` NO se toca nada. SOLICITUDES no tiene deshacer.
d = Doble()
r = E.ejecutar_una(SIN_ANALIZAR, d, n=7)
ok(d.llamadas == [], "¡una pasada SECA llamó al servicio! %r" % (d.llamadas,))
ok(r.seco is True, "la pasada seca no se marca como seca")
ok(r.hecho is False, "una pasada seca no puede darse por hecha")
ok(r.accion == P.ANALIZAR, "la pasada seca no dice qué acción haría")
ok(r.banderas == ("analyzed",), "la pasada seca no dice qué banderas dejaría: %r" % (r.banderas,))
ok(r.n == 7 and r.request_id == "R-real-3", "el resultado no identifica la fila")

d = Doble()
E.pasada([SIN_ANALIZAR, POR_PUBLICAR, POR_CERRAR], d)
ok(d.llamadas == [], "¡una pasada entera SECA tocó el mundo! %r" % (d.llamadas,))

# ── 3. Con `aplicar`, y comprobando QUÉ le llegó al doble ──────────────────────────────────
d = Doble()
r = E.ejecutar_una(SIN_ANALIZAR, d, aplicar=True)
ok(d.llamadas == [("analizar", "R-real-3")],
   "no llama a analizar con la fila correcta: %r" % (d.llamadas,))
ok(r.hecho is True and r.seco is False, "no se marca como hecha")
ok(r.error is None, "una pasada buena no debería traer error")

d = Doble()
E.ejecutar_una(POR_PUBLICAR, d, aplicar=True)
ok([c[0] for c in d.llamadas] == ["publicar"], "no llama a publicar: %r" % (d.llamadas,))

# ⛔ El caso fino: si lo ÚNICO que falta es el Libro, se registra, NO se republica.
d = Doble()
E.ejecutar_una(SOLO_LIBRO, d, aplicar=True)
ok([c[0] for c in d.llamadas] == ["registrar"],
   "republica lo ya publicado en vez de registrar: %r" % (d.llamadas,))

d = Doble()
E.ejecutar_una(POR_CERRAR, d, aplicar=True)
ok([c[0] for c in d.llamadas] == ["cerrar"], "no llama a cerrar: %r" % (d.llamadas,))

# ── 4. Las que NO se tocan, ni con `aplicar` ───────────────────────────────────────────────
# ⛔ La fila real cerrada sin derecho: no se reabre ni aunque se aplique.
for f, que in ((CERRADA_VACIA, "la cerrada sin derecho"), (CAMBIOS, "la de cambios pedidos"),
               (PUBLICADA, "la cerrada en regla"),
               (sin(CAMBIOS, changes_requested=F), "la que espera decisión")):
    d = Doble()
    r = E.ejecutar_una(f, d, aplicar=True)
    ok(d.llamadas == [], "¡se tocó %s! %r" % (que, d.llamadas))
    ok(r.hecho is False and r.seco is False, "%s no debería contar como hecha ni seca" % que)
    ok(r.porque.strip(), "%s no explica por qué se queda quieta" % que)

r = E.ejecutar_una(CERRADA_VACIA, Doble(), aplicar=True)
ok("una persona" in r.porque, "el por qué de la cerrada sin derecho no dice quién lo mira: %r"
   % r.porque)

# ── 5. Un fallo no para la pasada ──────────────────────────────────────────────────────────
d = Doble(revienta="publicar")
rs = E.pasada([SIN_ANALIZAR, POR_PUBLICAR, POR_CERRAR], d, aplicar=True)
ok(len(rs) == 3, "la pasada devuelve %d resultados de 3 filas" % len(rs))
ok(rs[1].error is not None, "el fallo de publicar no se recoge")
ok("503" in rs[1].error, "el error no conserva lo que dijo el mundo: %r" % rs[1].error)
ok("RuntimeError" in rs[1].error, "el error no dice de qué tipo fue: %r" % rs[1].error)
ok(rs[1].hecho is False, "una fila que reventó no puede contar como hecha")
ok(rs[2].hecho is True, "¡el fallo de la fila 2 dejó sin tocar la 3!")
ok([c[0] for c in d.llamadas] == ["analizar", "publicar", "cerrar"],
   "la pasada no siguió tras el fallo: %r" % (d.llamadas,))

# Un servicio que no existe se dice, no se traga.
class Manco(object):
    def analizar(self, f):
        pass

r = E.ejecutar_una(POR_CERRAR, Manco(), aplicar=True)
ok(r.error is not None and "cerrar" in r.error,
   "un servicio que falta debería decirse: %r" % r.error)
ok(r.hecho is False, "sin servicio no se puede dar por hecha")

# Una fila que no es un registro va a revisar y no revienta.
r = E.ejecutar_una(None, Doble(), aplicar=True)
ok(r.accion == P.REVISAR and r.error is None, "una fila rara debería ir a revisar sin error")
ok(r.request_id == "(sin request_id)", "una fila rara debería salir identificada como tal")

# ── 6. El resumen ──────────────────────────────────────────────────────────────────────────
d = Doble(revienta="publicar")
rs = E.pasada([SIN_ANALIZAR, POR_PUBLICAR, POR_CERRAR, CAMBIOS, CERRADA_VACIA], d, aplicar=True)
h, s, q, e = E.resumen(rs)
ok((h, s, q, e) == (2, 0, 2, 1), "el resumen no cuadra: %r" % ((h, s, q, e),))
ok(h + s + q + e == len(rs), "los cuatro del resumen no suman el total")

rs = E.pasada([SIN_ANALIZAR, POR_PUBLICAR, CAMBIOS], Doble())
h, s, q, e = E.resumen(rs)
ok((h, s, q, e) == (0, 2, 1, 0), "el resumen de una pasada seca no cuadra: %r" % ((h, s, q, e),))
ok(E.resumen([]) == (0, 0, 0, 0), "el resumen de nada debería ser todo ceros")

# ⚠️ Un resultado por fila, también por las que no hacen nada.
ok(len(E.pasada([CAMBIOS, PUBLICADA], Doble())) == 2,
   "la pasada se salta las filas que no hacen nada")

# ⛔ Y también por las que NO SON un registro. Sin este caso, una pasada podía filtrarlas
#    calladamente y el banco seguía verde: el recuento cuadraba porque la fila rara no llegaba a
#    contarse. Una fila que desaparece del informe es exactamente la que nadie va a mirar.
rs = E.pasada([CAMBIOS, None, PUBLICADA], Doble(), aplicar=True)
ok(len(rs) == 3, "la pasada se salta la fila que no es un registro: %d de 3" % len(rs))
ok(rs[1].accion == P.REVISAR, "la fila rara de en medio no sale marcada para revisar")
ok(rs[1].n == 3, "la fila rara no conserva su número de fila: %r" % rs[1].n)
ok([r.n for r in rs] == [2, 3, 4], "las filas pierden su numeración al saltarse una")

# ⛔ El guardia de «acción sin quién la atienda» sólo se alcanza si `siguiente` devuelve algo
#    fuera de la lista — un literal mal escrito, por ejemplo. Sin este caso el guardia era
#    inalcanzable **desde el banco** y su mutación salía ciega.
#    ⚠️ El parcheo se deshace en un `finally`: un monkeypatch que se escapa deja rojos ajenos.
_orig_siguiente = P.siguiente
try:
    P.siguiente = lambda f: ("accion_que_nadie_atiende", u"inventada")
    r = E.ejecutar_una(POR_CERRAR, Doble(), aplicar=True)
    ok(r.error is not None, "una acción que nadie atiende pasa callando")
    ok(r.error and "accion_que_nadie_atiende" in r.error,
       "el error no dice CUÁL es la acción huérfana: %r" % r.error)
    ok(r.hecho is False and r.seco is False, "una acción huérfana no puede contar como hecha")
    d_h = Doble()
    E.ejecutar_una(POR_CERRAR, d_h, aplicar=True)
    ok(d_h.llamadas == [], "¡una acción huérfana llegó a tocar el mundo! %r" % (d_h.llamadas,))
finally:
    P.siguiente = _orig_siguiente
ok(P.siguiente is _orig_siguiente, "el monkeypatch no se deshizo")
ok(E.ejecutar_una(POR_CERRAR, Doble()).accion == P.CERRAR,
   "tras deshacer el parcheo, `siguiente` no vuelve a funcionar")

print("%d comprobaciones" % hechas[0])
if fallos:
    print("\n%d ROJO(S):" % len(fallos))
    for f_ in fallos:
        print("  - %s" % f_)
    sys.exit(1)
print("verde")
