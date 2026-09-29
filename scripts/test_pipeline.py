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
import sustitucion as SU

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
# ⚠️ 10 desde el 30/09: entra `PDF` (generar el PDF desde el DOCX antes de publicar).
ok(len(P.ACCIONES) == 10, "deberían ser 10 acciones: %d" % len(P.ACCIONES))
# ⛔ Los duplicados se miran CONTRA EL PROPIO RECUENTO, no contra el número de arriba: con
#    los dos atados al mismo literal, esto era la misma afirmación escrita dos veces.
ok(len(set(P.ACCIONES)) == len(P.ACCIONES),
   "hay acciones repetidas en ACCIONES: %r" % (P.ACCIONES,))
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
ok("a medias" in por, "el por qué no dice por qué se para: %r" % por)
# ⚠️ Ya no es `notion_pdf_embedded` — eso se implementó el 699.ª —, así que el caso pide la
#    que sigue sin hacer nadie. Lo que se comprueba es que el motivo diga **cuál**, no cuál
#    en concreto: atarlo a una bandera que puede implementarse mañana rompe el banco por una
#    mejora.
ok(any(b in por for b in C.PUBLICACION),
   "el por qué no dice QUÉ falta, y sin eso no es accionable: %r" % por)
ok(a != P.PUBLICAR, "¡republica y crearía una segunda página!")
# ⛔⛔ Y ya NO depende de que la bandera que falta esté «sin implementar». Mientras esa lista
#    tuvo cosas dentro, el guardia sólo miraba ESAS: el día que se vaciara, una página ya
#    creada con cualquier otra bandera a medias habría vuelto a PUBLICAR — y `publicar` crea
#    la página, o sea una SEGUNDA página del mismo documento cada pasada. La lista se vacía
#    hoy (→ 701.ª), así que el guardia pregunta lo que de verdad importa: **¿ya hay página?**
ok(P.SIN_IMPLEMENTAR == (), "ya no queda ninguna bandera sin implementar: %r"
   % (P.SIN_IMPLEMENTAR,))
_a_medias2 = sin(PUBLICADA, closed=F, base_database_registered=F,
                 domain_permission_verified=F)
_a2, _p2 = P.siguiente(_a_medias2)
ok(_a2 == P.REVISAR,
   "⛔ con la página creada y UNA bandera cualquiera a medias vuelve a %r: crearía una "
   "SEGUNDA página de Notion del mismo documento" % (_a2,))
ok("domain_permission_verified" in _p2, "el motivo no dice cuál falta: %r" % (_p2,))
ok("drive_primary_file_verified" not in P.SIN_IMPLEMENTAR,
   "⛔ archivar y VERIFICAR el fichero ya se hace: se relee la carpeta")
ok("domain_permission_verified" not in P.SIN_IMPLEMENTAR,
   "⛔ …y compartir con el dominio también, releyendo el permiso")
ok("notion_pdf_embedded" not in P.SIN_IMPLEMENTAR,
   "⛔ subir el fichero YA está implementado: dejarlo aquí pararía expedientes que se pueden "
   "terminar")
ok("notion_embedding_verified" not in P.SIN_IMPLEMENTAR,
   "⛔ verificar el embebido YA se hace: `publicar` relee la página y busca el bloque")
ok(all(b.startswith("drive_") or b.startswith("domain_") for b in P.SIN_IMPLEMENTAR),
   "⛔ lo que queda sin implementar es TODO de Drive: %r" % (P.SIN_IMPLEMENTAR,))
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

# ── ⛔⛔ EL PDF VA ANTES DE PUBLICAR ─────────────────────────────────────────
# `publicar` sube `drive_primary_file_id` — el PDF — y si no lo hay **cae al DOCX original**.
# Notion lo acepta y crea un bloque de fichero **que no se puede leer en la página**: quien abra
# el documento ve un adjunto para descargar, que es justo lo que la página existe para evitar.
# ⚠️ Ese respaldo tenía su motivo escrito — *«quedarse sin documento esperando un fichero que
#    NADIE VA A GENERAR es peor que un adjunto sin previsualización»* — y ese motivo **caduca
#    hoy**: desde que existe `pdf.docx_a_pdf`, sí hay quien lo genere. El respaldo se queda (por
#    si LibreOffice falla), pero deja de ser la vía normal.
_DOCX = sin(PUBLICADA, closed=F, notion_page_created=F, base_database_registered=F,
            source_filename="memoria.docx", drive_primary_file_id="")
a, por = P.siguiente(_DOCX)
ok(a == P.PDF, u"⛔⛔ con un DOCX y sin PDF debería GENERARLO antes de publicar; toca %r" % a)
ok("PDF" in por or "pdf" in por, u"el por qué no nombra el PDF: %r" % por)

# ⚠️ Con el PDF ya hecho, sigue el camino de siempre.
a, _ = P.siguiente(sin(_DOCX, drive_primary_file_id="1PDF"))
ok(a == P.PUBLICAR, u"⛔ con el PDF ya generado debería publicar, no regenerarlo; toca %r" % a)

# ⛔ Y si el original YA es un PDF no hay nada que convertir: pedirlo dejaría el expediente
#    dando vueltas en un paso imposible.
a, _ = P.siguiente(sin(_DOCX, source_filename="informe.pdf"))
ok(a == P.PUBLICAR, u"⛔ con un original que YA es PDF no hay nada que generar; toca %r" % a)

# ⚠️ Sin saber cómo se llama el fichero no se adivina: se publica como siempre. Fallar hacia
#    «generar» dejaría a LibreOffice intentando convertir cualquier cosa.
a, _ = P.siguiente(sin(_DOCX, source_filename=""))
ok(a == P.PUBLICAR, u"sin nombre de fichero no se pide una conversión a ciegas; toca %r" % a)

# ⛔⛔ Y NO se pide el PDF de algo sin aprobar: el orden manda. Una fila sin decisión espera,
#    aunque sea un DOCX — generar el PDF de algo que puede acabar rechazado es trabajo tirado, y
#    peor: deja un fichero en la carpeta de un expediente que nadie aprobó.
a, _ = P.siguiente(sin(_DOCX, approved=F))
ok(a != P.PDF, u"⛔⛔ genera el PDF de un expediente SIN aprobar: toca %r" % a)

# ⚠️ Y la acción existe en la lista: una acción que se devuelve y no está en `ACCIONES` se cae
#    del reparto sin que nadie lo note.
ok(P.PDF in P.ACCIONES, u"⛔ `PDF` no está en `ACCIONES`: el reparto lo perdería en silencio")

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

# ── EL CIERRE LO DECIDE `puede_cerrar`, NO UNA COPIA DE SU CRITERIO ──────
# ⛔⛔ `cierre.puede_cerrar` ganó una razón para NO cerrar — el campo «Revisor/es» del documento
#    sin rellenar, que Cowork respeta y que ninguna bandera ve— y `siguiente` **siguió diciendo
#    CERRAR**, porque tenía su propio criterio escrito al lado («si no falta ninguna bandera,
#    cerrar»). Es la avería de «una regla escrita y cumplida en DOS de sus TRES caminos»: la
#    regla nueva vale en el revisor de la hoja y **no** en el que manda a ejecutar.
#    📏 Y no es hipotético: corrido contra `SOLICITUDES` de verdad el 29/09, de 17 filas la
#    Única que llegaba a una acción que escribe era la 18 — y la acción era CERRAR.
_PTE = sin(PUBLICADA, closed=F)
_PTE["revisor_field_pendiente"] = "TRUE"
_a, _p = P.siguiente(_PTE)
ok(_a != P.CERRAR,
   u"⛔ cierra un expediente que `puede_cerrar` se niega a cerrar: el criterio está copiado")
ok(_a == P.REVISAR, u"debería mandarlo a mirar, no dejarlo quieto: toca %r" % (_a,))
ok("Revisor" in _p, u"el motivo no dice QUÉ falta, y sin eso no es accionable: %r" % (_p,))
# ⚠️ Y sin nada pendiente sigue cerrando: la guarda no puede parar el camino bueno.
ok(P.siguiente(sin(PUBLICADA, closed=F))[0] == P.CERRAR,
   u"una publicada entera y sin pendientes debería cerrarse")

# ── UNA FILA YA REENTREGADA NO ESPERA UN REENVÍO QUE YA LLEGÓ ──────
# ⛔⛔ Medido el 29/09 contra `SOLICITUDES`: de las **cuatro** filas en `esperar_reenvio`,
#    **TRES ya habían recibido su reentrega** — las filas 7, 8 y 13, reentregadas por la 8, la 9
#    y la 16. Sin la cadena, el pipeline las deja esperando **para siempre** algo que ya pasó, y
#    un expediente que espera para siempre es exactamente uno que nadie vuelve a mirar.
_ORIG = sin(CAMBIOS, closed=F)
_ORIG["request_id"] = "SOL-ORIG"
_ORIG["reference"] = "Informe_S-6009_26"
_REENT = {"request_id": "SOL-NUEVA", "reference": "Informe_S-6009_26",
          "replaces_document": "SOL-ORIG", "replacement_reference": "Informe_S-6009_26",
          "replacement_reason": "cambios en el formato"}

ok(P.siguiente(_ORIG)[0] == P.REENVIO, u"sin reentrega, sigue esperando (es lo correcto)")
_a, _p = P.siguiente(_ORIG, SU.sustituidas([_ORIG, _REENT]))
ok(_a != P.REENVIO,
   u"⛔ sigue esperando un reenvío que YA llegó: el expediente se queda ahí para siempre")
ok(_a == P.REVISAR, u"debería mandarlo a mirar: toca %r" % (_a,))
ok("SOL-NUEVA" in _p, u"el motivo no dice QUIÉN lo reentregó, que es lo único accionable: %r"
   % (_p,))

# ⚠️ Y el reparto lo calcula él solo: pedirle al que llama que pase las claves es pedirle que
#    se acuerde, y el que no se acuerde tendrá el fallo de vuelta.
_rep = P.reparto([_ORIG, _REENT])
ok(_rep[P.REENVIO] == [],
   u"⛔ `reparto` no sigue la cadena y deja la fila esperando: %r" % (_rep[P.REENVIO],))
ok([x[1] for x in _rep[P.REVISAR]][:1] == ["SOL-ORIG"],
   u"la original debería salir a revisar: %r" % (_rep[P.REVISAR],))
# ⚠️ La reentrega de este caso va también a revisar, pero por otra cosa — no trae
#    `received`. Es ruido del fixture, no del enrutado; por eso se mira POR NOMBRE y no
#    por cuántas hay: contar habría atado el caso a un detalle que no es el tema.

# ⚠️ Sin cadena, nada cambia: las claves vacías no pueden alterar una sola fila.
ok(P.siguiente(_ORIG, {})[0] == P.REENVIO, u"con claves vacías debería seguir esperando")
ok(P.siguiente(_ORIG, None)[0] == P.REENVIO, u"con claves None también")

# ⛔⛔ AQUÍ HUBO UNA REGLA —«la referencia escrita tiene que ser la asignada, si no a
#    revisar»— Y SE RETIRA CON SU MOTIVO. La escribí con una frase de Daniel y él la corrigió
#    en el momento: *«si lo detecta siempre, que se lo corrija; no hay fallo»*. Y era peor que
#    innecesaria: **bloqueaba justo las sustituciones**, que es lo que sí quiere que funcione
#    — una reentrega trae **a propósito** la referencia ya usada, y esa regla la mandaba a
#    revisar. Lo que hace falta está en la ficha 715.ª: reusar el `reserved_id` de la
#    referencia que se sustituye.

print("%d comprobaciones" % hechas[0])
if fallos:
    print("\n%d ROJO(S):" % len(fallos))
    for f_ in fallos:
        print("  - %s" % f_)
    sys.exit(1)
print("verde")
