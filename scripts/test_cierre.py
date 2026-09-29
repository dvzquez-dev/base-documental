#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Banco de `cierre.py`. Sin red, sin credenciales, sin reloj.

⛔ Las filas son **reales**: las banderas de las primeras filas de `SOLICITUDES` (columnas AE:AW),
leídas el 29/09/2026. Incluida la que tiene `closed = TRUE` con todo lo demás en `FALSE`.
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

fallos = []
hechas = [0]


def ok(cond, que):
    hechas[0] += 1
    if not cond:
        fallos.append(que)


def fila(valores, rid="R-1"):
    """Construye una fila a partir de la lista de 19 valores, en el orden de la cabecera."""
    d = dict(zip(C.BANDERAS, valores))
    d["request_id"] = rid
    return d


T, F, V = "TRUE", "FALSE", ""

# 📏 Las cuatro filas reales, copiadas tal cual de AE2:AW8.
REAL_CERRADA_VACIA = fila([T, F, F, F, F, F, F, F, F, F, F, F, F, F, F, F, F, F, T], "R-real-2")
REAL_CAMBIOS = fila([T, T, T, T, T, F, F, T, F, F, F, F, F, F, F, F, F, F, F], "R-real-3")
REAL_PUBLICADA = fila([T, T, T, T, T, T, F, F, T, T, T, T, T, T, T, T, T, T, T], "R-real-4")
REAL_VACIOS = fila([T, T, T, T, V, F, F, T, V, V, V, V, V, V, V, V, V, V, F], "R-real-8")

# ── 1. Los tres estados de una bandera ─────────────────────────────────────────────────────
ok(C.estado("TRUE") == C.SI, "TRUE debería ser SI")
ok(C.estado("FALSE") == C.NO, "FALSE debería ser NO")
ok(C.estado("") == C.SIN_TOCAR, "la celda vacía debería ser SIN_TOCAR, no NO")
ok(C.estado(None) == C.SIN_TOCAR, "None debería ser SIN_TOCAR")
ok(C.estado("  true  ") == C.SI, "no recorta ni ignora la caja")
ok(C.estado(True) == C.SI, "el booleano True debería ser SI")
ok(C.estado(False) == C.NO, "el booleano False debería ser NO")
ok(C.estado("chusta") == C.SIN_TOCAR, "un valor que no se entiende es SIN_TOCAR, no NO")
# ⛔ El vacío y el FALSE tienen que seguir siendo distintos: si se aplastan, un expediente que se
#    quedó a medias no se distingue de uno que se decidió que no.
ok(C.estado("") != C.estado("FALSE"),
   "el vacío y FALSE dan lo mismo: se pierde «nunca se pasó por aquí»")
ok(C.es_si("") is False, "el vacío no está puesto")
ok(C.es_si("FALSE") is False, "FALSE no está puesto")
ok(C.es_si("TRUE") is True, "TRUE sí está puesto")
ok((C.SI, C.NO, C.SIN_TOCAR) == ("si", "no", "sin_tocar"), "los tres estados cambiaron de nombre")

# ── 2. Las 19 banderas, contra lo medido ───────────────────────────────────────────────────
ok(len(C.BANDERAS) == 19, "no son 19 banderas: %d" % len(C.BANDERAS))
ok(C.BANDERAS[0] == "received" and C.BANDERAS[-1] == "closed",
   "el orden de las banderas no empieza en received y acaba en closed")
ok(C.BANDERAS[5:8] == ("approved", "rejected", "changes_requested"),
   "las tres decisiones no están donde las midió la cabecera")
ok(len(C.PUBLICACION) == 8, "las banderas de publicación deberían ser 8: %d" % len(C.PUBLICACION))
# ⚠️ El paso 3 se borró: exigirlo dejaría sin cerrar todo lo aprobado desde la app.
ok("approval_email_sent" not in C.PUBLICACION,
   "se exige el correo de aprobación, que la app sustituyó: nada se cerraría nunca")
ok("reported" not in C.PUBLICACION, "se exige `reported`, que es del paso 3 borrado")
ok(all(b in C.BANDERAS for b in C.PUBLICACION),
   "alguna bandera de publicación no existe en la cabecera medida")

# ── 3. Por dónde va ────────────────────────────────────────────────────────────────────────
ok(C.via(REAL_PUBLICADA) == "aprobado", "no ve que la fila real publicada está aprobada")
ok(C.via(REAL_CAMBIOS) == "cambios", "no ve los cambios pedidos de la fila real")
ok(C.via(REAL_CERRADA_VACIA) is None, "la fila real cerrada-sin-nada no tiene decisión")
ok(C.via(fila([T] * 6 + [T] + [F] * 12)) == "aprobado", "aprobado debería ganar a rechazado")
ok(C.via({}) is None, "una fila vacía no tiene decisión")

# ── 4. Quién puede cerrar ──────────────────────────────────────────────────────────────────
vale, m = C.puede_cerrar(REAL_PUBLICADA)
ok(vale is True, "la fila real publicada entera debería poder cerrarse: %r" % (m,))
ok(m == [], "una fila que puede cerrarse no debería dar motivos")

vale, m = C.puede_cerrar(REAL_CAMBIOS)
ok(vale is False, "una fila con cambios pedidos NO debería poder cerrarse")
ok(m and "esperando" in m[0], "el motivo de los cambios no explica por qué: %r" % (m,))

vale, m = C.puede_cerrar(REAL_CERRADA_VACIA)
ok(vale is False, "la fila real cerrada sin nada NO debería poder cerrarse")
ok(m and "sin decisión" in m[0], "el motivo no dice que falta la decisión: %r" % (m,))

# Un rechazado cierra sin publicar nada: no hay nada que publicar.
rechazada = fila([T, T, T, F, F, F, T, F, F, F, F, F, F, F, F, F, F, F, F])
vale, m = C.puede_cerrar(rechazada)
ok(vale is True, "un rechazado debería poder cerrarse sin publicar: %r" % (m,))

# ⛔ El caso que más duele: aprobado pero a medio publicar.
a_medias = dict(REAL_PUBLICADA)
a_medias["base_database_registered"] = F
vale, m = C.puede_cerrar(a_medias)
ok(vale is False, "un aprobado sin registrar en el Libro NO debería poder cerrarse")
ok(m and "base_database_registered" in m[0],
   "el motivo no dice QUÉ falta, que es lo único accionable: %r" % (m,))

sin_analizar = dict(REAL_PUBLICADA)
sin_analizar["analyzed"] = F
vale, m = C.puede_cerrar(sin_analizar)
ok(vale is False, "un aprobado sin analizar NO debería poder cerrarse")
ok(any("sin analizar" in x for x in m), "no dice que falta el análisis: %r" % (m,))

# El vacío no cuenta como hecho.
con_vacio = dict(REAL_PUBLICADA)
con_vacio["notion_page_created"] = V
vale, m = C.puede_cerrar(con_vacio)
ok(vale is False, "una bandera VACÍA cuenta como hecha: el vacío no es TRUE")

# ── 5. El revisor, sobre las filas reales ──────────────────────────────────────────────────
av = C.revisar([REAL_CERRADA_VACIA, REAL_CAMBIOS, REAL_PUBLICADA, REAL_VACIOS])

# ⛔ La fila 2 real: cerrada con todo lo demás en FALSE. Es el hallazgo entero de esta pieza.
ok(any(n == 2 and "cerrado y no debería" in q for n, _r, q in av),
   "no ve la fila real con closed=TRUE y todo lo demás en FALSE")
ok(any(n == 2 and "sin decisión" in q for n, _r, q in av),
   "el aviso de la fila 2 no dice que el problema es que no hay decisión")
ok(any(n == 2 and "R-real-2" == r for n, r, _q in av),
   "el aviso no lleva el request_id, que es por lo que se busca la fila")

# Las filas 3 y 5 (cambios pedidos, sin cerrar) están bien: no deben dar aviso.
ok(not any(n == 3 for n, _r, _q in av), "marca en rojo la fila con cambios pedidos y sin cerrar")
ok(not any(n == 5 for n, _r, _q in av), "marca en rojo la fila real con celdas vacías y sin cerrar")
# La fila 4 (publicada y cerrada) tampoco.
ok(not any(n == 4 for n, _r, _q in av), "marca en rojo la fila publicada y cerrada, que está bien")

# El otro lado: listo para cerrar y sigue abierto.
abierta = dict(REAL_PUBLICADA)
abierta["closed"] = F
av2 = C.revisar([abierta])
ok(any("listo para cerrar" in q for _n, _r, q in av2),
   "no ve un expediente terminado que nadie cerró")

# Dos decisiones a la vez.
dos = fila([T, T, T, T, T, T, T, F, T, T, T, T, T, T, T, T, T, T, T], "R-dos")
av3 = C.revisar([dos])
ok(any("decisiones a la vez" in q for _n, _r, q in av3),
   "no ve un expediente aprobado Y rechazado al mismo tiempo")
ok(any("approved" in q and "rejected" in q for _n, _r, q in av3),
   "el aviso no dice CUÁLES son las dos decisiones")

# Cerrado sin estar recibido.
sin_recibir = fila([F, T, T, T, T, T, F, F, T, T, T, T, T, T, T, T, T, T, T], "R-sr")
ok(any("ni recibido" in q for _n, _r, q in C.revisar([sin_recibir])),
   "no ve un expediente cerrado que ni se recibió")

ok(C.revisar([]) == [], "una hoja vacía no debería dar avisos")
ok(C.revisar([REAL_PUBLICADA]) == [], "una fila correcta no debería dar ningún aviso")
ok([n for n, _r, _q in av] == sorted(n for n, _r, _q in av),
   "los avisos no salen ordenados por número de fila")

# ⛔ El orden sólo se puede comprobar con avisos en filas DISTINTAS cuyo motivo ordene al revés.
#    Con todos los avisos en la misma fila, ordenar por fila y por motivo da lo mismo y la
#    comprobación de arriba sale ciega: lo dijo una mutación, no una relectura.
#    Aquí la fila 2 dice «está listo para cerrar» y la 3 «cerrado y no debería»: por motivo, la 3
#    iría primero.
_lista = dict(REAL_PUBLICADA); _lista["closed"] = F
av4 = C.revisar([_lista, REAL_CERRADA_VACIA])
ok([n for n, _r, _q in av4] == [2, 3],
   "los avisos se ordenan por motivo y no por fila: %r" % ([(n, q[:28]) for n, _r, q in av4],))
ok(len(av4) >= 2, "debería haber avisos en las dos filas: %r" % (av4,))

# ── EL CAMPO «Revisor/es» BLOQUEA EL CIERRE ─────────────────────
# ⛔⛔ Esto no es una idea: salió de correr el pipeline contra `SOLICITUDES` de verdad (29/09).
#    De las 17 filas, **una sola** llegaba a una acción que escribe — la 18, `79E115DB` —, y la
#    acción era CERRAR. Y esa fila es justo la que Cowork **se niega a cerrar**, con el motivo
#    escrito en la propia hoja: *«revisor_field_pendiente=TRUE (…) Es el unico item que bloquea el
#    cierre del expediente; Cowork NO cierra hasta que el revisor este relleno»*. O sea que la
#    Única fila sobre la que este código habría actuado hoy, la habría cerrado **mal**.
_REVISOR_OK = dict(REAL_PUBLICADA)
_REVISOR_PTE = dict(REAL_PUBLICADA, revisor_field_pendiente="TRUE")
ok(C.puede_cerrar(_REVISOR_OK)[0] is True, u"sin nada pendiente debería poder cerrarse")
_vale, _mot = C.puede_cerrar(_REVISOR_PTE)
ok(_vale is False, u"⛔ cierra con el campo «Revisor/es» pendiente: el documento queda publicado "
                  u"con un «Revisor/es: ----» dentro y ya no lo mira nadie")
ok(any("Revisor" in m for m in _mot), u"el motivo no dice cuál es el campo: %r" % (_mot,))

# ⛔ Y el criterio es «un SÍ», NO «no vacío» — y eso lo decidió QUIÉN SE PONE ROJO, no el gusto:
#    esa columna lleva **marcas de tiempo** en 8 filas reales, y **cuatro de ellas ya están
#    cerradas**. Con «no vacío bloquea», esas cuatro pasarían a «cerrada y no debería» — cuatro
#    rojos sobre expedientes que Cowork cerró a propósito. Con «un SÍ», el único afectado es el
#    que lo está de verdad.
_CON_FECHA = dict(REAL_PUBLICADA, revisor_field_pendiente="2026-07-08T09:08:38+02:00")
ok(C.puede_cerrar(_CON_FECHA)[0] is True,
   u"⛔ una MARCA DE TIEMPO en esa columna bloquea el cierre: 4 filas ya cerradas se pondrían "
   u"en contradicción, y Cowork las cerró a propósito")
ok(C.puede_cerrar(dict(REAL_PUBLICADA, revisor_field_pendiente=""))[0] is True,
   u"la columna vacía no debería bloquear nada")
ok(C.puede_cerrar(dict(REAL_PUBLICADA, revisor_field_pendiente="chusta"))[0] is True,
   u"un valor que no se entiende no es un SÍ: bloquearía por no saber leer")

# ⚠️ Y sólo en la vía APROBADO: un rechazado no se publica, así que no tiene campo «Revisor/es»
#    que rellenar, y bloquearlo por eso lo dejaría abierto para siempre.
_RECHAZADO = fila([T, T, T, T, T, F, T, F, F, F, F, F, F, F, F, F, F, F, F], "R-rechazado")
ok(C.puede_cerrar(dict(_RECHAZADO, revisor_field_pendiente="TRUE"))[0] is True,
   u"⛔ un RECHAZADO no se puede cerrar nunca: no hay «Revisor/es» que rellenar en algo que no "
   u"se publica")

# Y el revisor de la hoja lo canta.
_avisos = C.revisar([dict(_REVISOR_PTE, closed="FALSE")])
ok(_avisos == [], u"⚠️ una fila ABIERTA con el revisor pendiente está en regla, y no debe cantar "
                 u"como «lista para cerrar»: %r" % (_avisos,))
ok(C.revisar([_REVISOR_PTE]), u"⛔ cerrada Y con el revisor pendiente debería cantar")
# ⚠️ Y sin la guarda, esa misma fila abierta sale como «lista para cerrar» — que es justo lo
#    que hacía con la fila 18 de verdad.
ok(C.revisar([dict(_REVISOR_OK, closed="FALSE")]),
   u"sin nada pendiente, una publicada y abierta SÍ debería cantar como lista para cerrar")

print("%d comprobaciones" % hechas[0])
if fallos:
    print("\n%d ROJO(S):" % len(fallos))
    for f_ in fallos:
        print("  - %s" % f_)
    sys.exit(1)
print("verde")
