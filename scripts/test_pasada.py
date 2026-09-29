#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Banco de `pasada.py`. Sin red, sin credenciales y **sin reloj**: la hora va inyectada.

⛔ El doble apunta lo que le piden y **qué celdas** le llegan, no sólo que se le llamara.
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
import pasada as PA
import pipeline as P

fallos = []
hechas = [0]


def ok(cond, que):
    hechas[0] += 1
    if not cond:
        fallos.append(que)


T, F = "TRUE", "FALSE"
AHORA = "2026-09-29T03:14:00Z"   # fijo: un banco no mira el reloj

# 📏 Cabecera mínima con los nombres reales que la pasada toca.
CAB = (["request_id"] + list(C.BANDERAS) + ["updated_at", "last_error", "retry_count"])


def fila(valores, rid="R-1", extra=None):
    f = [rid] + list(valores) + ["", "", ""]
    if extra:
        for nombre, v in extra.items():
            f[CAB.index(nombre)] = v
    return f


PUB = [T, T, T, T, T, T, F, F, T, T, T, T, T, T, T, T, T, T, T]
POR_CERRAR = PUB[:-1] + [F]
SIN_ANALIZAR = [T, F, F, F, F, F, F, F, F, F, F, F, F, F, F, F, F, F, F]
CAMBIOS = [T, T, T, T, T, F, F, T, F, F, F, F, F, F, F, F, F, F, F]


class Doble(object):
    def __init__(self, revienta=None, miente=False):
        self.llamadas = []
        self.escritas = None
        self.revienta = revienta
        self.miente = miente

    def _m(self, n):
        self.llamadas.append(n)
        if self.revienta == n:
            raise RuntimeError(u"la hoja contestó 503")

    def analizar(self, f):
        self._m("analizar")

    def publicar(self, f):
        self._m("publicar")

    def registrar(self, f):
        self._m("registrar")

    def cerrar(self, f):
        self._m("cerrar")

    def escribir(self, celdas):
        self._m("escribir")
        self.escritas = list(celdas)

    def releer(self, claves):
        """⚠️ El doble RELEE, como el real. Un doble más pobre que el mundo no se nota hasta
        que alguien mira el valor — y esta noche ya puso 4 pasadas buenas en rojo.
        `self.miente` deja simular el fallo medido: la escritura dice que sí y no escribe."""
        self._m("releer")
        if self.miente:
            return {}
        return dict(self.escritas or [])


# ── 1. En seco no se escribe NADA, pero SÍ se calcula qué se escribiría ────────────────────
d = Doble()
rs, celdas, avisos = PA.correr([CAB, fila(POR_CERRAR)], d, ahora=AHORA)
ok(d.llamadas == [], "¡la pasada seca tocó el mundo! %r" % (d.llamadas,))
ok(d.escritas is None, "la pasada seca escribió en la hoja")
# ⛔ LA PASADA SECA TIENE QUE ENSEÑAR QUÉ ESCRIBIRÍA. Aquí ponía `celdas == []`, que era
#    escribir en el banco lo que el código hacía en vez de lo que tenía que hacer — y de paso
#    dejaba ciega la guarda `if aplicar and celdas`, porque en seco nunca había celdas.
ok(len(celdas) == 2, "la pasada seca no enseña las celdas que escribiría: %r" % (celdas,))
ok(dict(celdas).get("%s2" % PA.H.letra_columna(CAB.index("closed") + 1)) == "TRUE",
   "la pasada seca no dice que pondría closed=TRUE: %r" % (celdas,))
ok(len(rs) == 1 and rs[0].seco is True, "la fila no se marca como seca")
ok(rs[0].accion == P.CERRAR, "la pasada seca no dice qué acción haría")

# ── 2. Con aplicar: se hace, y SE ESCRIBE lo que se hizo ───────────────────────────────────
# ⛔ Éste es el cable que faltaba: sin él, el trabajo se hace y la hoja sigue diciendo que está
#    por hacer, así que la pasada siguiente lo repite — y republicar es como se duplican páginas.
d = Doble()
rs, celdas, avisos = PA.correr([CAB, fila(POR_CERRAR)], d, aplicar=True, ahora=AHORA)
ok("cerrar" in d.llamadas, "no llama a cerrar: %r" % (d.llamadas,))
ok("escribir" in d.llamadas, "¡se hizo el trabajo y NO se escribió en la hoja!")
ok(d.escritas is not None, "no llegó nada al escritor")
escritas = dict(d.escritas or [])
col_closed = PA.H.letra_columna(CAB.index("closed") + 1)
ok(escritas.get("%s2" % col_closed) == "TRUE",
   "no escribe closed=TRUE en la celda de la fila 2: %r" % (d.escritas,))
col_upd = PA.H.letra_columna(CAB.index("updated_at") + 1)
ok(escritas.get("%s2" % col_upd) == AHORA,
   "no escribe updated_at con la hora INYECTADA: %r" % (d.escritas,))
ok(avisos == [], "una pasada limpia no debería dar avisos: %r" % (avisos,))
ok(len(celdas) == 2, "deberían ser 2 celdas (closed + updated_at): %r" % (celdas,))

# Publicar deja las 7 banderas de publicación, no la del Libro.
d = Doble()
_rs, celdas, _av = PA.correr(
    [CAB, fila(PUB[:8] + [F] * 8 + [T, T, F])], d, aplicar=True, ahora=AHORA)
puestas = [c for c, v in celdas if v == "TRUE"]
# ⛔ UNA, no siete: `servicios.publicar` sólo crea la página de Notion. Prometer las siete
#    escribiría «PDF embebido» y «Drive verificado» sin que pasara nada, y `cierre` cerraría el
#    expediente. Prometer de menos lo deja abierto y a la vista; de más lo entierra.
ok(len(puestas) == 5, "publicar debería dejar 5 banderas y deja %d" % len(puestas))
col_libro = PA.H.letra_columna(CAB.index("base_database_registered") + 1)
ok(("%s2" % col_libro) not in dict(celdas),
   "publicar escribe el registro del Libro, que es del paso 6")

# ── 3. Lo que se queda quieto no escribe NADA, ni updated_at ───────────────────────────────
# ⚠️ Tocar la fila para decir que no pasó nada hace que «última modificación» deje de significar
#    «última vez que pasó algo».
for valores, que in ((CAMBIOS, "la de cambios pedidos"), (PUB, "la cerrada en regla")):
    d = Doble()
    _rs, celdas, _av = PA.correr([CAB, fila(valores)], d, aplicar=True, ahora=AHORA)
    ok(celdas == [], "%s escribe algo y no debería: %r" % (que, celdas))
    ok("escribir" not in d.llamadas, "%s llama al escritor sin nada que escribir" % que)

# ── 3b. Lo escrito se RELEE y se contrasta ───────────────────────────────────
d = Doble()
_rs, _c, avisos = PA.correr([CAB, fila(POR_CERRAR)], d, aplicar=True, ahora=AHORA)
ok("releer" in d.llamadas, u"¡escribe y NO relee para comprobarlo! %r" % (d.llamadas,))
ok(d.llamadas.index("escribir") < d.llamadas.index("releer"),
   u"relee ANTES de escribir, que no comprueba nada: %r" % (d.llamadas,))
ok(avisos == [], u"si lo escrito cuadra no debería haber avisos: %r" % (avisos,))

# ⛔ EL FALLO MEDIDO EN ESTE PROYECTO: la escritura dice que sí y la celda sigue vacía.
d = Doble(miente=True)
_rs, _c, avisos = PA.correr([CAB, fila(POR_CERRAR)], d, aplicar=True, ahora=AHORA)
ok(avisos, u"¡una escritura que no escribió pasa sin avisar!")
ok(any("NO quedaron como se pidió" in a for a in avisos),
   u"el aviso no dice que la hoja no refleja lo hecho: %r" % (avisos,))

# Sin `releer` se dice: escribir sin comprobar es el agujero que esto viene a tapar.
class SinReleer(object):
    def cerrar(self, f):
        pass

    def escribir(self, celdas):
        pass

_rs, _c, avisos = PA.correr([CAB, fila(POR_CERRAR)], SinReleer(), aplicar=True, ahora=AHORA)
ok(any("releer" in a for a in avisos), u"no avisa de que falta `releer`: %r" % (avisos,))
ok(any("silencioso" in a for a in avisos),
   u"el aviso no dice por qué importa: %r" % (avisos,))

# ⚠️ Y en SECO no se relee: no hay nada escrito que comprobar.
d = Doble()
PA.correr([CAB, fila(POR_CERRAR)], d, ahora=AHORA)
ok("releer" not in d.llamadas, u"relee en una pasada seca, donde no se escribió nada")


# ── 4. El error se guarda EN LA FILA ───────────────────────────────────────────────────────
d = Doble(revienta="cerrar")
rs, celdas, _av = PA.correr([CAB, fila(POR_CERRAR)], d, aplicar=True, ahora=AHORA)
esc = dict(celdas)
col_err = PA.H.letra_columna(CAB.index("last_error") + 1)
col_int = PA.H.letra_columna(CAB.index("retry_count") + 1)
ok("503" in (esc.get("%s2" % col_err) or ""),
   "el error no se guarda en la fila: %r" % (celdas,))
ok(esc.get("%s2" % col_int) == 1, "retry_count no sube a 1: %r" % (esc.get("%s2" % col_int),))
ok(("%s2" % col_closed) not in esc, "¡marca closed=TRUE aunque la acción reventó!")

# Y sube desde lo que ya había, no desde cero.
d = Doble(revienta="cerrar")
_rs, celdas, _av = PA.correr([CAB, fila(POR_CERRAR, extra={"retry_count": "4"})],
                             d, aplicar=True, ahora=AHORA)
ok(dict(celdas).get("%s2" % col_int) == 5, "retry_count no sube desde 4: %r" % (dict(celdas),))

# Un retry_count ilegible vale 0 y no revienta.
d = Doble(revienta="cerrar")
_rs, celdas, _av = PA.correr([CAB, fila(POR_CERRAR, extra={"retry_count": "chusta"})],
                             d, aplicar=True, ahora=AHORA)
ok(dict(celdas).get("%s2" % col_int) == 1, "un retry_count ilegible debería contar como 0")

# ⛔ Al salir bien se LIMPIA el error viejo: si no, una fila que falló el martes y funcionó el
#    miércoles se queda con el error del martes y alguien arregla un problema que ya no existe.
d = Doble()
_rs, celdas, _av = PA.correr([CAB, fila(POR_CERRAR, extra={"last_error": "lo de ayer"})],
                             d, aplicar=True, ahora=AHORA)
ok(dict(celdas).get("%s2" % col_err) == "", "no limpia el error viejo al salir bien: %r" % (celdas,))
# Y si no había error, no se escribe la columna para nada.
d = Doble()
_rs, celdas, _av = PA.correr([CAB, fila(POR_CERRAR)], d, aplicar=True, ahora=AHORA)
ok(("%s2" % col_err) not in dict(celdas), "escribe last_error sin haber error previo")

# ── 5. La columna duplicada avisa y no se escribe ──────────────────────────────────────────
CAB_DUP = list(CAB) + ["closed"]
d = Doble()
rs, celdas, avisos = PA.correr([CAB_DUP, fila(POR_CERRAR) + [""]], d, aplicar=True, ahora=AHORA)
ok(any("closed" in a and "veces" in a for a in avisos),
   "no avisa de la columna duplicada de la cabecera: %r" % (avisos,))
ok(celdas == [], "escribe pese a la columna duplicada: %r" % (celdas,))
ok("cerrar" in d.llamadas, "no debería dejar de HACER el trabajo por no poder anotarlo")
ok(any("fila 2" in a for a in avisos), "el aviso no dice en qué fila se quedó sin anotar")

# ── 6. Sin escritor: se dice, y se dice que se repetirá ────────────────────────────────────
class SinEscritor(object):
    def cerrar(self, f):
        pass

rs, celdas, avisos = PA.correr([CAB, fila(POR_CERRAR)], SinEscritor(), aplicar=True, ahora=AHORA)
ok(any("escribir" in a for a in avisos), "no avisa de que falta el escritor: %r" % (avisos,))
ok(any("repetir" in a for a in avisos),
   "el aviso no dice la consecuencia (que la próxima pasada lo repite): %r" % (avisos,))

# Si el escritor revienta, se dice y no se traga.
d = Doble(revienta="escribir")
_rs, _c, avisos = PA.correr([CAB, fila(POR_CERRAR)], d, aplicar=True, ahora=AHORA)
ok(any("503" in a for a in avisos), "un fallo al escribir se traga: %r" % (avisos,))

# ── 7. Sin hora inyectada no se inventa una ────────────────────────────────────────────────
d = Doble()
_rs, celdas, _av = PA.correr([CAB, fila(POR_CERRAR)], d, aplicar=True)
ok(("%s2" % col_upd) not in dict(celdas),
   "sin hora inyectada se escribe updated_at igualmente: %r" % (celdas,))
ok(len(celdas) == 1, "sin hora debería escribirse sólo la bandera: %r" % (celdas,))

# ── 8. Hojas degeneradas ───────────────────────────────────────────────────────────────────
for valores, que in (([], "vacía"), ([CAB], "sólo cabecera"), (None, "None")):
    rs, celdas, avisos = PA.correr(valores, Doble(), aplicar=True, ahora=AHORA)
    ok(rs == [] and celdas == [], "una hoja %s debería dar cero de todo" % que)

# ── 9. El informe, que también se refuta ───────────────────────────────────────────────────
d = Doble(revienta="cerrar")
rs, celdas, avisos = PA.correr([CAB, fila(POR_CERRAR), fila(CAMBIOS, "R-2")],
                               d, aplicar=True, ahora=AHORA)
txt = PA.informe(rs, celdas, avisos, aplicar=True)
ok("PASADA APLICADA" in txt, "el informe no dice que se aplicó: %r" % txt[:60])
ok("ERROR" in txt and "503" in txt, "el informe no enseña el error: %r" % txt)
ok("R-1" in txt, "el informe no identifica la fila por su request_id")

txt_seco = PA.informe(*PA.correr([CAB, fila(POR_CERRAR)], Doble(), ahora=AHORA), aplicar=False)
# ⛔ Un informe que se lee igual haya escrito o no es la forma de que alguien crea que ya está.
ok("SECO" in txt_seco, "el informe en seco no lo dice: %r" % txt_seco[:60])
ok("no se ha escrito nada" in txt_seco, "el informe en seco no dice que no escribió")
ok("HAR" in txt_seco, "el informe en seco no dice qué haría")
# ⚠️ Y el recuento de celdas se lee en condicional, no en pasado.
ok("se escribirían" in txt_seco, "el informe en seco dice «escritas»: %r" % txt_seco)
ok("escritas" in txt and "se escribirían" not in txt,
   "el informe aplicado no dice «escritas»: %r" % txt)
ok("PASADA APLICADA" not in txt_seco, "el informe en seco se lee como aplicado")
ok(txt_seco != txt, "el informe seco y el aplicado son el mismo texto")

# ── La PRUEBA que devuelve el servicio se escribe en su columna ───────────────────
# ⛔ Sin esto el `notion_page_id` se queda en memoria: `evidencias` nunca lo ve y la pasada
#    siguiente vuelve a publicar. La capacidad estaría escrita entera y muerta en el cable.
class ConId(Doble):
    def publicar(self, f):
        self._m("publicar")
        return {"notion_page_id": "1a2b3c"}


CAB_ID = CAB + ["notion_page_id"]
_pub = fila(PUB[:8] + [F] * 8 + [T, T, F]) + [""]
d = ConId()
_rs, celdas, _av = PA.correr([CAB_ID, _pub], d, aplicar=True, ahora=AHORA)
_col = PA.H.letra_columna(CAB_ID.index("notion_page_id") + 1)
ok(dict(celdas).get("%s2" % _col) == "1a2b3c",
   "el id que devolvió Notion no se escribe en su columna: %r" % (celdas,))
# Y en seco también se ve lo que se escribiría, sin escribirlo.
d = ConId()
_rs, celdas, _av = PA.correr([CAB_ID, _pub], d, ahora=AHORA)
ok("escribir" not in d.llamadas, "¡la pasada seca escribió!")

print("%d comprobaciones" % hechas[0])
if fallos:
    print("\n%d ROJO(S):" % len(fallos))
    for f_ in fallos:
        print("  - %s" % f_)
    sys.exit(1)
print("verde")
