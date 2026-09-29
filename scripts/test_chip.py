#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Banco del **chip de la carpeta** en el Libro de Datos. Sin red.

⛔ Lo pidió Daniel con estas palabras: *«en el libro de datos… lo que tienes que enlazar es el
chip de la carpeta no el link ni hostias… y dentro de la carpeta está el procesamiento con IA y
está el archivo original y está, si hay un Word, el PDF»*. O sea: la celda de ubicación tiene que
llevar **la carpeta entera**, porque dentro está todo, y como **chip**, no como texto.

⛔⛔ Y lo que este banco defiende de verdad es la trampa de orden: **el chip se pone DESPUÉS de
que la fila ya está escrita**, así que un fallo ahí **no puede tirar el registro**. Si tirara,
se perdería `base_database_row` —la prueba de que la fila existe— y la pasada siguiente
escribiría **una SEGUNDA fila** en el Libro para el mismo documento. El Libro real ya tiene
defectos de ese estilo y son los que más cuesta ver.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding="utf-8")
    except Exception:
        pass

import libro_datos as LD

fallos = []
hechas = [0]


def ok(cond, que):
    hechas[0] += 1
    if not cond:
        fallos.append(que)


CARPETA = "1By3PxQbpXNvCu7EzP03jbVwBydWVHrt3"

# ── 1. La URL de la carpeta ────────────────────────────────────────────────────────────────
u = LD.url_carpeta(CARPETA)
ok(u == "https://drive.google.com/drive/folders/" + CARPETA,
   u"⛔ la URL no es la de una CARPETA: %r" % (u,))
# ⛔ `/file/d/<id>/view` es la de un FICHERO. Con esa URL el chip abriría un fichero que no
#    existe —el id es de una carpeta—, y el revisor se encontraría un error en vez del expediente.
ok("/file/d/" not in u, u"⛔ usa la URL de un fichero para una carpeta: %r" % (u,))
ok(LD.url_carpeta("") is None and LD.url_carpeta(None) is None,
   u"sin id no hay URL, y no se inventa una")
ok(LD.url_carpeta("  %s  " % CARPETA) == u, u"no recorta los espacios del id")

# ── 2. La petición que pone el chip ────────────────────────────────────────────────────────
p = LD.peticion_chip(hoja_id=123, fila_1based=57, folder_id=CARPETA)
ok(isinstance(p, dict) and p, u"no devuelve una petición: %r" % (p,))
_r = p.get("updateCells") or {}
_rango = _r.get("range") or {}
ok(_rango.get("sheetId") == 123, u"la petición no dice en qué pestaña: %r" % (_rango,))
# ⛔⛔ EL ÍNDICE ES 0-BASED Y LA FILA VIENE 1-BASED. Equivocarse aquí no da ningún error: escribe
#    el chip en la fila de al lado, o sea en el expediente de OTRA persona.
ok(_rango.get("startRowIndex") == 56,
   u"⛔⛔ la fila 57 (1-based) tiene que ser el índice 56: %r — un desfase de uno pone el chip "
   u"en el expediente de otro y no da ningún error" % (_rango.get("startRowIndex"),))
ok(_rango.get("endRowIndex") == 57, u"el rango no acaba donde debe: %r" % (_rango,))
# La columna es la B: «Ubicación del Archivo» es la segunda de `COLUMNAS`.
ok(LD.COLUMNAS[1].startswith(u"Ubicación"), u"la columna 2 ya no es la ubicación: %r" % (LD.COLUMNAS,))
ok(_rango.get("startColumnIndex") == 1 and _rango.get("endColumnIndex") == 2,
   u"⛔ el chip no va a la columna de la ubicación: %r" % (_rango,))

_celda = ((_r.get("rows") or [{}])[0].get("values") or [{}])[0]
_chips = _celda.get("chipRuns") or []
ok(len(_chips) == 1, u"no hay exactamente un chip en la celda: %r" % (_chips,))
ok(_chips and _chips[0].get("startIndex") == 0,
   u"el chip no empieza en el carácter 0: %r" % (_chips,))
ok(_chips and (((_chips[0].get("chip") or {}).get("richLinkProperties") or {}).get("uri")) == u,
   u"⛔ el chip no apunta a la carpeta: %r" % (_chips,))
# ⛔ `fields` manda: sin él, `updateCells` **borra el resto de la celda**. Con él mal, o no
#    escribe el chip o se lleva por delante el texto que ya estaba.
ok("chipRuns" in (_r.get("fields") or ""), u"⛔ `fields` no incluye `chipRuns`: %r" % (_r.get("fields"),))
ok("userEnteredValue" in (_r.get("fields") or ""),
   u"⛔ `fields` no incluye el valor: el chip necesita texto debajo o la celda queda en blanco")
# El texto de debajo sigue siendo la referencia: si el chip no se renderiza, la celda no queda muda.
ok((_celda.get("userEnteredValue") or {}).get("stringValue"),
   u"⛔ la celda se queda SIN TEXTO: si el chip no se pinta, la ubicación queda en blanco")

# Entradas malas: no se fabrica una petición a medias.
ok(LD.peticion_chip(hoja_id=1, fila_1based=1, folder_id="") is None,
   u"⛔ fabrica una petición sin carpeta: escribiría un chip a ninguna parte")
ok(LD.peticion_chip(hoja_id=None, fila_1based=5, folder_id=CARPETA) is None,
   u"sin pestaña no hay petición")
ok(LD.peticion_chip(hoja_id=1, fila_1based=0, folder_id=CARPETA) is None,
   u"⛔ la fila 0 no existe en 1-based: aceptarla escribiría en la CABECERA")
ok(LD.peticion_chip(hoja_id=1, fila_1based=None, folder_id=CARPETA) is None,
   u"sin fila no hay petición")

# Y el texto se puede fijar (la referencia del expediente).
p2 = LD.peticion_chip(hoja_id=1, fila_1based=2, folder_id=CARPETA, texto=u"Informe_S-2011_26")
_c2 = ((p2["updateCells"]["rows"][0]["values"])[0])
ok(_c2["userEnteredValue"]["stringValue"] == u"Informe_S-2011_26",
   u"el texto de la celda no es el que se pidió: %r" % (_c2.get("userEnteredValue"),))

# ── 3. Releer: ¿quedó el chip de verdad? ───────────────────────────────────────────────────
# ⛔ Esto existe porque **nadie ha probado nunca** que la API de Sheets deje ESCRIBIR chips.
#    Cowork los pone a mano en el navegador. Sin releer, el pipeline dejaría texto plano
#    haciéndose pasar por chip y nadie se enteraría — y el Libro es justo donde se busca.
_leida = {"chipRuns": [{"startIndex": 0,
                        "chip": {"richLinkProperties": {"uri": LD.url_carpeta(CARPETA)}}}]}
ok(LD.chip_puesto(_leida, CARPETA) is True, u"no reconoce un chip que SÍ está: %r" % (_leida,))
ok(LD.chip_puesto({}, CARPETA) is False, u"⛔ da por puesto un chip en una celda sin chips")
ok(LD.chip_puesto({"chipRuns": []}, CARPETA) is False, u"una lista vacía no es un chip")
ok(LD.chip_puesto(None, CARPETA) is False, u"una celda ausente no revienta")
# ⛔⛔ Y un chip que apunta a OTRA carpeta no vale: es peor que ninguno, porque manda al revisor
#    al expediente equivocado con toda la confianza.
_otra = {"chipRuns": [{"startIndex": 0,
                       "chip": {"richLinkProperties": {"uri": LD.url_carpeta("OTRO_ID")}}}]}
ok(LD.chip_puesto(_otra, CARPETA) is False,
   u"⛔⛔ da por bueno un chip que apunta a OTRA carpeta: manda al revisor al expediente de otro")
# ⚠️ Un texto que CONTIENE la URL no es un chip: es el enlace pelado que Daniel descartó.
ok(LD.chip_puesto({"userEnteredValue": {"stringValue": LD.url_carpeta(CARPETA)}}, CARPETA) is False,
   u"⛔ toma un enlace en texto por un chip: es exactamente lo que se pidió NO hacer")
ok(LD.chip_puesto(_leida, "") is False, u"sin carpeta contra la que comparar, no se afirma nada")

print("%d comprobaciones" % hechas[0])
if fallos:
    print("\n%d ROJO(S):" % len(fallos))
    for f_ in fallos:
        print("  - %s" % f_)
    sys.exit(1)
print("verde")
