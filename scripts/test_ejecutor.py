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
# ⚠️ Tres categorías, no dos: ANOTAR no llama a nadie (el trabajo YA está hecho) pero tampoco
#    se queda quieta — escribe la marca que faltó. Darle un servicio sería invitar a hacerlo dos
#    veces, que es justo lo que viene a impedir.
for a in P.ACCIONES:
    ok(a in E.ATIENDE or a in E.QUIETAS or a == P.ANOTAR,
       "la acción %r no está ni atendida, ni quieta, ni es ANOTAR" % a)
ok(P.ANOTAR not in E.ATIENDE, "ANOTAR tiene un servicio: es la puerta a hacer el trabajo dos veces")
ok(P.ANOTAR not in E.QUIETAS, "ANOTAR no es una acción quieta: escribe la marca que faltó")
ok(set(E.ATIENDE) & set(E.QUIETAS) == set(), "hay acciones a la vez atendidas y quietas")
ok(len(E.ATIENDE) + len(E.QUIETAS) + 1 == len(P.ACCIONES),
   "atendidas + quietas + ANOTAR no suman las acciones del pipeline")

# ⛔ ANOTAR escribe las banderas y NO toca el mundo.
_d = Doble()
_r = E.ejecutar_una(sin(PUBLICADA, closed=F, notion_page_created=F, notion_page_id="1a2b"),
                    _d, aplicar=True)
ok(_r.accion == P.ANOTAR, "no llega a ANOTAR: %r" % _r.accion)
ok(_d.llamadas == [], "¡ANOTAR llamó a un servicio! %r" % (_d.llamadas,))
ok(_r.hecho is True, "ANOTAR debería darse por hecha sin llamar a nadie")
ok(_r.banderas == ("notion_page_created",),
   "ANOTAR no marca la bandera que tenía prueba: %r" % (_r.banderas,))
# En seco tampoco, y dice qué marcaría.
_r = E.ejecutar_una(sin(PUBLICADA, closed=F, notion_page_created=F, notion_page_id="1a2b"),
                    Doble())
ok(_r.seco is True and _r.banderas == ("notion_page_created",),
   "en seco ANOTAR no dice qué marcaría: %r" % (_r.banderas,))
# ⚠️ Las que se quedan quietas son decisiones, no olvidos: cada una lleva su por qué escrito.
ok(all(E.QUIETAS[a].strip() for a in E.QUIETAS), "alguna acción quieta no explica por qué")
ok(P.ESPERAR in E.QUIETAS and P.REVISAR in E.QUIETAS,
   "esperar decisión y revisar a mano tienen que quedarse quietas")
ok(P.ANALIZAR in E.ATIENDE and P.CERRAR in E.ATIENDE, "faltan acciones por atender")
# Las banderas que promete cada acción existen de verdad en la cabecera medida.
for a, (_n, bs) in sorted(E.ATIENDE.items()):
    for b in bs:
        ok(b in C.BANDERAS, "la acción %r promete la bandera %r, que no está en la cabecera" % (a, b))
# ⛔⛔ UNA SOLA: la que `servicios.publicar` hace de verdad. Aquí se exigían SIETE y el
#    adaptador sólo crea la página de Notion — o sea que esta comprobación **fijaba la
#    mentira**: habría escrito «PDF embebido» y «carpeta de Drive creada» sin que pasara nada,
#    y con las siete puestas `cierre` habría dado el expediente por publicado y lo habría
#    cerrado. Un documento sin fichero en Drive, marcado cerrado, que nadie vuelve a mirar.
ok(E.ATIENDE[P.PUBLICAR][1] == ("notion_page_created", "notion_pdf_embedded",
                                "notion_embedding_verified", "drive_folder_created",
                                "drive_primary_file_verified", "drive_summary_created",
                                "domain_permission_verified"),
   "publicar promete más banderas de las que hace: %r" % (E.ATIENDE[P.PUBLICAR][1],))
# ✅ Son las SIETE de `cierre.PUBLICACION` menos el Libro, que lo registra otra acción. Que
#    estén todas no repite el fallo de la 695.ª: entonces se prometían a ciegas y ahora cada
#    una la respalda una llamada que se relee — y las que tienen prueba declarada se filtran.
ok(set(E.ATIENDE[P.PUBLICAR][1]) ==
   set(C.PUBLICACION) - set(["base_database_registered"]),
   "publicar ya no promete justo lo que le toca: %r" % (E.ATIENDE[P.PUBLICAR][1],))
ok(not set(E.ATIENDE[P.PUBLICAR][1]) & set(P.SIN_IMPLEMENTAR),
   "publicar promete alguna de las que NADIE implementa todavía")
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

# ── 5b. ⛔⛔ Y `SystemExit` NO ES UNA EXCEPCIÓN CUALQUIERA: NO LA CAZA UN `except Exception` ──
# Es el caso REAL, no uno inventado: `servicios.analizar` se niega en voz alta con
# `raise SystemExit(...)` — a propósito, para que una pasada no dé por analizado lo que no lo
# está —, y `SystemExit` cuelga de `BaseException`. Con un `except Exception` **se escapa**, y
# entonces la promesa del docstring de `ejecutar_una` («nunca lanza») es falsa justo en el único
# sitio donde hoy se usa. El modo de fallo es el que ese docstring dice que no puede pasar: la
# pasada **muere en el expediente 3** y los 40 siguientes se quedan sin tocar, con pinta de
# «el pipeline va lento» cuando está parado.
# ⚠️ Y es la misma familia que ya mordió aquí antes: `bajar` prometía «no lanza NUNCA» con un
#    `except Exception` y `cli` lanzaba `SystemExit`.
class Suicida(object):
    """Como el `servicios` de verdad: `analizar` se planta con `SystemExit`."""

    def __init__(self):
        self.llamadas = []

    def analizar(self, f):
        self.llamadas.append("analizar")
        raise SystemExit(u"el an\xe1lisis no se pudo hacer: no encuentro Claude Code")

    def publicar(self, f):
        self.llamadas.append("publicar")

    def registrar(self, f):
        self.llamadas.append("registrar")

    def cerrar(self, f):
        self.llamadas.append("cerrar")


d = Suicida()
try:
    rs = E.pasada([SIN_ANALIZAR, POR_PUBLICAR, POR_CERRAR], d, aplicar=True)
    _escapo = False
except BaseException:
    rs, _escapo = [], True
ok(_escapo is False,
   u"⛔⛔ un `SystemExit` del servicio SE ESCAPA y mata la pasada entera: `except Exception` no "
   u"caza `BaseException`, y `servicios.analizar` lanza exactamente eso")
ok(len(rs) == 3, u"la pasada debería devolver 3 resultados: %d" % len(rs))
ok(rs and rs[0].error is not None, u"el plante no se recoge como error de esa fila")
ok(rs and "SystemExit" in (rs[0].error or ""),
   u"el error no dice de qué tipo fue: %r" % (rs[0].error if rs else None,))
ok(rs and "Claude Code" in (rs[0].error or ""),
   u"se pierde lo que dijo el servicio, que es lo único accionable: %r"
   % (rs[0].error if rs else None,))
ok(rs and rs[0].hecho is False, u"una fila que se plantó no puede contar como hecha")
ok(rs and rs[2].hecho is True,
   u"⛔ el plante de la fila 1 dejó sin tocar la 3: es el daño entero de esta regla")
ok(d.llamadas == ["analizar", "publicar", "cerrar"],
   u"la pasada no siguió tras el plante: %r" % (d.llamadas,))

# ⚠️ Pero un `KeyboardInterrupt` SÍ tiene que subir: si Daniel corta la pasada a mano, tragarse
#    el Ctrl-C la dejaría corriendo y sin forma de pararla. No todo `BaseException` es igual.
class Cortada(object):
    def analizar(self, f):
        raise KeyboardInterrupt()

    def publicar(self, f):
        pass

    def registrar(self, f):
        pass

    def cerrar(self, f):
        pass


try:
    E.pasada([SIN_ANALIZAR], Cortada(), aplicar=True)
    _subio = False
except KeyboardInterrupt:
    _subio = True
ok(_subio is True,
   u"⛔ se traga el Ctrl-C: la pasada seguiría corriendo sin forma de pararla a mano")

# ── ⛔⛔ LA CADENA DE REENTREGAS NO LLEGABA A `siguiente` ─────────────────────────
# `pipeline.siguiente(fila, cadena)` sabe decir «pidió cambios y la reentrega YA llegó» — el fallo
# medido el 29/09, donde **3 de las 4** filas que esperaban un reenvío ya lo habían recibido y el
# pipeline las dejaba esperando **para siempre**. Pero `ejecutar_una` llamaba `P.siguiente(fila)`
# **sin la cadena**, así que `quien_sustituye(fila, None)` devolvía **siempre** `None` y esa rama
# era **INALCANZABLE EN PRODUCCIÓN**: el arreglo estaba escrito, probado por su banco, y muerto en
# el cable de en medio. Lo tumbó un agente al que sólo se le pidió refutar.
# ⚠️ Y no daba ningún síntoma: el pipeline seguía contestando REENVIO, que es una respuesta
#    perfectamente razonable — y falsa.
_ESPERA = {"request_id": "SOL-VIEJA", "reference": "Informe_S-6009_26", "received": T,
           "analyzed": T, "changes_requested": T}
_REENTREGA = {"request_id": "SOL-NUEVA", "reference": "Informe_S-6009_26", "received": T,
              "analyzed": T, "replaces_document": "SOL-VIEJA",
              "replacement_reference": "Informe_S-6009_26", "replacement_reason": "erratas"}

d = Doble()
rs = E.pasada([_ESPERA, _REENTREGA], d, aplicar=False)
ok(rs[0].accion == P.REVISAR,
   u"⛔⛔ la fila que YA recibió su reentrega sigue en %r: la cadena no llega a `siguiente` y "
   u"esa fila espera PARA SIEMPRE algo que ya pasó" % (rs[0].accion,))
ok("SOL-NUEVA" in (rs[0].porque or ""),
   u"el motivo no dice QUIÉN la reentregó, que es lo único accionable: %r" % (rs[0].porque,))
# ⚠️ Y la reentrega NO se marca a sí misma como sustituida: se entierra sola.
ok(rs[1].accion != P.REVISAR or "reentrega YA" not in (rs[1].porque or ""),
   u"⛔ la propia reentrega se da por sustituida: %r" % (rs[1].porque,))
# ⚠️ Y sin cadena que calcular, una pasada normal no cambia de comportamiento.
ok(E.pasada([POR_CERRAR], Doble(), aplicar=False)[0].accion == P.CERRAR,
   u"una fila sin nada de sustitución debería seguir igual")

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
    # ⚠️ El doble acepta la CADENA igual que el real: uno mas pobre que el original habria
    #    reventado con un TypeError en vez de medir lo que este caso mide.
    P.siguiente = lambda f, c=None: ("accion_que_nadie_atiende", u"inventada")
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

# ── Lo que el servicio DEVUELVE llega al Resultado ──────────────────────────────
# ⛔ Es la PRUEBA de que el trabajo se hizo (`notion_page_id`). Sin ella, `evidencias` no puede
#    anotar lo ya hecho y la pasada siguiente crea una SEGUNDA página del mismo documento.
class ConProsa(Doble):
    def publicar(self, f):
        self._mete("publicar", f)
        return {"notion_page_id": "1a2b3c", "notion_page_url": "https://n/x"}


_d = ConProsa()
_r = E.ejecutar_una(POR_PUBLICAR, _d, aplicar=True)
ok(_r.extra == {"notion_page_id": "1a2b3c", "notion_page_url": "https://n/x"},
   "lo que devuelve el servicio no llega al Resultado: %r" % (_r.extra,))
ok(_r.hecho is True, "sigue dándose por hecha")
# Un servicio que no devuelve nada no rompe: `extra` queda vacío.
ok(E.ejecutar_una(POR_CERRAR, Doble(), aplicar=True).extra == {},
   "un servicio que devuelve None debería dejar `extra` vacío")
ok(E.ejecutar_una(POR_CERRAR, Doble()).extra == {}, "en seco tampoco hay extra")

# ── Una bandera con PRUEBA declarada no se pone sin la prueba ──────────
# ⛔⛔ Es la CUARTA vez en este repo que algo se da por hecho sin estarlo. La cura no es mirar
#    cada servicio: es que la marca dependa de la PRUEBA. Si `EV.PRUEBA_DE` dice que
#    `drive_summary_created` se prueba con `drive_summary_file_id` y el servicio no lo devuelve,
#    la bandera NO se escribe — y el expediente se queda a la vista en vez de enterrado.
class _SinPrueba(object):
    def publicar(self, fila):
        return {"notion_page_id": "p-1"}          # ni resumen ni carpeta


_r = E.ejecutar_una(dict(POR_PUBLICAR), _SinPrueba(), aplicar=True)
ok(_r.hecho and not _r.error, u"el caso debería salir hecho: %r" % (_r.error,))
ok("notion_page_created" in _r.banderas,
   u"la bandera CON prueba debería ponerse: %r" % (_r.banderas,))
ok("drive_summary_created" not in _r.banderas,
   u"⛔ marca el resumen como creado sin que el servicio devuelva `drive_summary_file_id`")
ok("notion_pdf_embedded" in _r.banderas,
   u"⚠️ una bandera SIN prueba declarada no se puede filtrar: quitarla cambiaría de tema")

# ⚠️ Y con la prueba en la FILA (de una pasada anterior) sí se pone: la prueba vale venga de
#    donde venga, si no una reanudación dejaría banderas sin poner para siempre.
_r = E.ejecutar_una(dict(POR_PUBLICAR, drive_summary_file_id="F-vieja"),
                    _SinPrueba(), aplicar=True)
ok("drive_summary_created" in _r.banderas,
   u"la prueba ya anotada en la fila debería valer: %r" % (_r.banderas,))

# ⚠️ En SECO no se filtra: la pasada seca enseña lo que se TOCARÍA, y aún no hay servicio que
#    haya devuelto nada. Filtrar ahí dejaría la pasada seca enseñando de menos.
_r = E.ejecutar_una(dict(POR_PUBLICAR), _SinPrueba(), aplicar=False)
ok(_r.seco and "drive_summary_created" in _r.banderas,
   u"la pasada seca debería enseñar TODAS las que tocaría: %r" % (_r.banderas,))

print("%d comprobaciones" % hechas[0])
if fallos:
    print("\n%d ROJO(S):" % len(fallos))
    for f_ in fallos:
        print("  - %s" % f_)
    sys.exit(1)
print("verde")
