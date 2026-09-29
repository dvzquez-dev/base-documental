#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Banco de `pipeline.py`: el orden entero del pipeline, probado sin red ni credenciales.

⛔ Las filas base son **reales** (banderas de `SOLICITUDES`, columnas AE:AW, leídas el
29/09/2026). Cada caso cambia UNA bandera sobre ellas, que es lo que hace comparable el resultado.
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
import pipeline as P

fallos = []
hechas = [0]


def ok(cond, que):
    hechas[0] += 1
    if not cond:
        fallos.append(que)


T, F, V = "TRUE", "FALSE", ""


def fila(valores, rid="R-1"):
    d = dict(zip(C.BANDERAS, valores))
    d["request_id"] = rid
    return d


# 📏 Reales, de AE2:AW8.
CERRADA_VACIA = fila([T, F, F, F, F, F, F, F, F, F, F, F, F, F, F, F, F, F, T], "R-real-2")
CAMBIOS = fila([T, T, T, T, T, F, F, T, F, F, F, F, F, F, F, F, F, F, F], "R-real-3")
PUBLICADA = fila([T, T, T, T, T, T, F, F, T, T, T, T, T, T, T, T, T, T, T], "R-real-4")


def sin(base, **kw):
    d = dict(base)
    d.update(kw)
    return d


# ── 1. Las acciones ────────────────────────────────────────────────────────────────────────
ok(len(P.ACCIONES) == 9, "deberían ser 9 acciones: %d" % len(P.ACCIONES))
ok(len(set(P.ACCIONES)) == 9, "hay acciones repetidas en ACCIONES")
# ⛔ Una sola acción necesita modelo. Es el número que justifica todo el reparto, así que se fija.
ok(P.CON_MODELO == (P.ANALIZAR,),
   "las acciones que necesitan modelo ya no son sólo analizar: %r" % (P.CON_MODELO,))
ok(len(P.CON_MODELO) == 1, "debería haber exactamente UNA acción con modelo")
ok(P.ANALIZAR in P.ACCIONES and P.REVISAR in P.ACCIONES, "faltan acciones en la lista")

# ── 1b. ANOTAR: lo que ya está hecho no se rehace ─────────────────────────────────
# ⛔ Si la página de Notion se creó y la bandera no llegó a escribirse — y acaba de medirse que
#    una escritura puede no hacer nada y decir que sí —, republicar crea una SEGUNDA página del
#    mismo documento y nada las marca como duplicadas.
a, por = P.siguiente(sin(PUBLICADA, closed=F, notion_page_created=F,
                         notion_page_id="1a2b3c"))
ok(a == P.ANOTAR, "con la página YA creada debería anotar, no republicar; toca %r" % a)
ok("notion_page_created" in por, "el por qué no dice qué se anota: %r" % por)

# Sin la prueba, sí toca publicar: una bandera sin identificador no prueba nada.
a, _ = P.siguiente(sin(PUBLICADA, closed=F, notion_page_created=F, notion_page_id=""))
ok(a == P.PUBLICAR, "sin identificador debería publicar de verdad; toca %r" % a)

# ⛔⛔ LO QUE HOY NO HACE NADIE. Con la página ya creada y faltando el PDF o Drive, **no se
#    vuelve a publicar** — crearía una segunda página cada pasada — y **tampoco se da por
#    hecho**. Se para y se manda a mirar: es lo único honesto mientras no haya adaptador.
_a_medias = sin(PUBLICADA, closed=F, notion_pdf_embedded=F, drive_folder_created=F)
a, por = P.siguiente(_a_medias)
ok(a == P.REVISAR, "con la página creada y el PDF sin subir debería ir a revisar; toca %r" % a)
ok("no hace nadie" in por, "el por qué no dice que es algo sin implementar: %r" % por)
# ⚠️ Ya no es `notion_pdf_embedded` — eso se implementó el 699.ª —, así que el caso pide la
#    que sigue sin hacer nadie. Lo que se comprueba es que el motivo diga **cuál**, no cuál
#    en concreto: atarlo a una bandera que puede implementarse mañana rompe el banco por una
#    mejora.
ok(any(b in por for b in P.SIN_IMPLEMENTAR),
   "el por qué no dice QUÉ falta, y sin eso no es accionable: %r" % por)
ok(a != P.PUBLICAR, "¡republica y crearía una segunda página!")
ok(len(P.SIN_IMPLEMENTAR) == 5, "las banderas sin implementar deberían ser 5: %d"
   % len(P.SIN_IMPLEMENTAR))
ok("notion_pdf_embedded" not in P.SIN_IMPLEMENTAR,
   "⛔ subir el fichero YA está implementado: dejarlo aquí pararía expedientes que se pueden "
   "terminar")
ok("notion_embedding_verified" in P.SIN_IMPLEMENTAR,
   "⛔ …pero VERIFICAR el embebido no: subir no es verificar, y exige releer la página")
ok("notion_page_created" not in P.SIN_IMPLEMENTAR,
   "crear la página SÍ está implementado: meterlo aquí pararía todo desde el primer documento")

# Y anotar va ANTES que registrar el Libro, aunque falten los dos.
a, _ = P.siguiente(sin(PUBLICADA, closed=F, base_database_registered=F,
                       base_database_row="14"))
ok(a == P.ANOTAR, "con la fila del Libro ya escrita debería anotar; toca %r" % a)

# ── 2. El orden, caso por caso ─────────────────────────────────────────────────────────────
a, por = P.siguiente(sin(CAMBIOS, analyzed=F, changes_requested=F))
ok(a == P.ANALIZAR, "recibida y sin analizar debería tocar analizar, toca %r" % a)
ok("sin analizar" in por, "el por qué de analizar no lo explica: %r" % por)

a, _ = P.siguiente(sin(CAMBIOS, changes_requested=F))
ok(a == P.ESPERAR, "analizada y sin decisión debería esperar, toca %r" % a)

a, por = P.siguiente(CAMBIOS)
ok(a == P.REENVIO, "con cambios pedidos debería esperar el reenvío, toca %r" % a)
ok("reenv" in por, "el por qué del reenvío no lo explica: %r" % por)

a, _ = P.siguiente(sin(CAMBIOS, changes_requested=F, rejected=T))
ok(a == P.CERRAR, "una rechazada debería cerrarse sin publicar, toca %r" % a)

a, por = P.siguiente(sin(PUBLICADA, closed=F, notion_page_created=F,
                         base_database_registered=F))
ok(a == P.PUBLICAR, "aprobada y sin publicar debería publicar, toca %r" % a)
ok("notion_page_created" in por, "el por qué no dice QUÉ falta: %r" % por)

# ⛔ El caso fino: si lo ÚNICO que falta es el Libro, toca registrar, no re-publicar. Publicar de
#    nuevo lo que ya está publicado es como se crean las páginas duplicadas.
a, por = P.siguiente(sin(PUBLICADA, closed=F, base_database_registered=F))
ok(a == P.REGISTRAR, "si sólo falta el Libro debería registrar, no republicar; toca %r" % a)
ok("Libro" in por, "el por qué de registrar no lo explica: %r" % por)

a, _ = P.siguiente(sin(PUBLICADA, closed=F))
ok(a == P.CERRAR, "publicada entera y sin cerrar debería cerrar, toca %r" % a)

a, por = P.siguiente(PUBLICADA)
ok(a == P.NADA, "una cerrada en regla no debería tocar nada, toca %r" % a)
ok("en regla" in por, "el por qué de no hacer nada no lo explica: %r" % por)

# ── 3. Lo que se manda a mirar a mano ──────────────────────────────────────────────────────
# ⛔ La fila real cerrada sin derecho: NO se reabre sola. Un pipeline que deshace decisiones
#    ajenas calladamente es peor que uno que se para.
a, por = P.siguiente(CERRADA_VACIA)
ok(a == P.REVISAR, "la fila real cerrada sin derecho debería ir a revisar, toca %r" % a)
ok("no debería" in por, "el por qué no dice que el cierre no se sostiene: %r" % por)
ok(a != P.ANALIZAR, "reabre por su cuenta una fila que alguien cerró")

a, por = P.siguiente(sin(CAMBIOS, received=F))
ok(a == P.REVISAR, "una fila sin recibir debería ir a revisar, toca %r" % a)
ok("recibida" in por, "el por qué no dice que no consta recibida: %r" % por)

a, por = P.siguiente(sin(PUBLICADA, closed=F, rejected=T))
ok(a == P.REVISAR, "aprobada Y rechazada debería ir a revisar, toca %r" % a)
ok("2 decisiones" in por, "el por qué no dice que hay dos decisiones: %r" % por)

# ⚠️ Nunca lanza: una fila rara se manda a mirar, no rompe la pasada entera.
for raro in (None, [], "chusta", 42):
    a, _ = P.siguiente(raro)
    ok(a == P.REVISAR, "una fila %r debería ir a revisar sin lanzar" % type(raro).__name__)
a, _ = P.siguiente({})
ok(a == P.REVISAR, "un registro vacío debería ir a revisar (ni siquiera consta recibido)")

# ── 4. El reparto ──────────────────────────────────────────────────────────────────────────
r = P.reparto([CERRADA_VACIA, CAMBIOS, PUBLICADA])
ok(sorted(r) == sorted(P.ACCIONES), "el reparto no trae TODAS las acciones como claves")
# ⚠️ Las vacías también: si «publicar» desaparece cuando no hay nada, se lee como que la fase no
#    existe, y la diferencia entre CERO y NO LO SÉ es justo la que hay que ver.
ok(r[P.PUBLICAR] == [], "sin nada que publicar la clave debería estar y vacía")
ok(len(r[P.REVISAR]) == 1 and r[P.REVISAR][0][1] == "R-real-2",
   "el reparto no pone la fila real problemática en revisar: %r" % (r[P.REVISAR],))
ok(len(r[P.REENVIO]) == 1, "la de cambios pedidos debería estar en esperar_reenvio")
ok(len(r[P.NADA]) == 1, "la cerrada en regla debería estar en nada")
ok(r[P.REVISAR][0][0] == 2, "la fila del reparto no cuenta desde la cabecera")
ok(sum(len(v) for v in r.values()) == 3, "el reparto pierde o duplica filas")
ok(P.reparto([])[P.CERRAR] == [], "un reparto vacío debería traer las claves igualmente")

# Una fila que no es un registro no revienta el reparto y sale identificada.
r2 = P.reparto([None, PUBLICADA])
ok(len(r2[P.REVISAR]) == 1 and r2[P.REVISAR][0][1] == "(sin request_id)",
   "una fila que no es registro no sale marcada en el reparto: %r" % (r2[P.REVISAR],))

# ── 5. Cuánto cuesta inferencia ────────────────────────────────────────────────────────────
sin_analizar = sin(CAMBIOS, analyzed=F, changes_requested=F)
ok(P.cuantas_con_modelo([CERRADA_VACIA, CAMBIOS, PUBLICADA]) == 0,
   "ninguna de estas tres necesita modelo")
ok(P.cuantas_con_modelo([sin_analizar, sin_analizar, PUBLICADA]) == 2,
   "deberían ser 2 las que necesitan modelo")
ok(P.cuantas_con_modelo([]) == 0, "una lista vacía no necesita modelo")

print("%d comprobaciones" % hechas[0])
if fallos:
    print("\n%d ROJO(S):" % len(fallos))
    for f_ in fallos:
        print("  - %s" % f_)
    sys.exit(1)
print("verde")
