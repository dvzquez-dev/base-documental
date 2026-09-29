#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Banco de `evidencias.py`. Sin red, sin credenciales, sin reloj.

⛔ Lo que protege: que **una bandera sin su identificador NO cuente como hecha**. Aflojar ahí sería
peor que el problema original — se daría por publicado un documento que no lo está, y nadie
volvería a mirarlo.
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
import evidencias as EV

fallos = []
hechas = [0]


def ok(cond, que):
    hechas[0] += 1
    if not cond:
        fallos.append(que)


T, F = "TRUE", "FALSE"


def fila(**kw):
    d = dict((b, F) for b in C.BANDERAS)
    d["request_id"] = "R-1"
    d.update(kw)
    return d


# ── 1. El mapa, contra la cabecera medida ──────────────────────────────────────────────────
# ⛔ TRES, no cinco. `drive_folder_created` y `drive_primary_file_verified` se cayeron el
#    697.ª: el código de Cowork dice que la primera la decide el paso final «cuando el resto de
#    la publicación esté completa», y la segunda afirma «verificado» cuando el id sólo prueba
#    «existe». Anotarlas al ver el id marcaría como publicado lo que no lo está.
ok(EV.PRUEBA_DE == {"notion_page_created": "notion_page_id",
                    "drive_summary_created": "drive_summary_file_id",
                    "base_database_registered": "base_database_row"},
   "PRUEBA_DE ya no es el mapa medido")
ok("drive_folder_created" not in EV.PRUEBA_DE,
   "⛔ `drive_folder_created` NO se anota por tener carpeta: su bandera significa que la "
   "publicación entera está completa")
ok("drive_primary_file_verified" not in EV.PRUEBA_DE,
   "⛔ …ni `drive_primary_file_verified` por tener el fichero: «existe» no es «verificado»")
ok(EV.ya_hecho(fila(drive_folder_id="abc")) == [],
   "⛔ tener la carpeta NO basta para anotar que la publicación está hecha")
# ⛔ Cada bandera del mapa tiene que existir de verdad, o se estaría mirando un nombre que nadie
#    escribe y la protección no saltaría nunca.
for bandera in sorted(EV.PRUEBA_DE):
    ok(bandera in C.BANDERAS,
       "la bandera %r del mapa no existe en la cabecera: no saltaría nunca" % bandera)
# Y todas las del mapa son de publicación: anotar algo que no lo es sería otra cosa.
for bandera in sorted(EV.PRUEBA_DE):
    ok(bandera in C.PUBLICACION,
       "%r no es una bandera de publicación: no debería anotarse por evidencia" % bandera)

# ── 2. Con prueba se anota ─────────────────────────────────────────────────────────────────
ok(EV.ya_hecho(fila(notion_page_id="1a2b3c")) == ["notion_page_created"],
   "no ve que la página ya existe: %r" % EV.ya_hecho(fila(notion_page_id="1a2b3c")))
ok(EV.ya_hecho(fila(base_database_row="14")) == ["base_database_registered"],
   "no ve que la fila del Libro ya está escrita")
ok(EV.ya_hecho(fila(base_database_row=14)) == ["base_database_registered"],
   "un entero debería contar como prueba")
# ⛔ El `0` NO es prueba, y ahora es una decisión escrita y no la coerción de un `or`: no existe
#    la fila 0 de una hoja ni un identificador `0`, y darlo por bueno marcaría como hecho algo que
#    no lo está — peor que rehacerlo.
ok(EV.ya_hecho(fila(base_database_row=0)) == [], "un 0 no debería contar como prueba")
ok(EV.hay_prueba(0) is False and EV.hay_prueba(0.0) is False, "el 0 no es prueba")
ok(EV.hay_prueba(14) is True and EV.hay_prueba("14") is True, "un 14 sí es prueba")
ok(EV.hay_prueba(True) is False and EV.hay_prueba(False) is False,
   "un booleano no es un identificador: `True` no prueba nada")
ok(EV.hay_prueba(None) is False and EV.hay_prueba("") is False and EV.hay_prueba("  ") is False,
   "vacío y None no son prueba")

# Varias a la vez, y en el orden de la cabecera (no en el que Python itere el diccionario).
d = fila(notion_page_id="p", drive_summary_file_id="s", base_database_row="14")
# ⛔ El orden es el de la CABECERA, no el del diccionario — que está escrito en alfabético justo
#    para que esto se pueda comprobar. Con los dos órdenes iguales, la garantía era inobservable y
#    su mutación salía ciega.
ok(EV.ya_hecho(d) == ["notion_page_created", "drive_summary_created", "base_database_registered"],
   "no salen en el orden de la cabecera: %r" % EV.ya_hecho(d))
ok(list(EV.PRUEBA_DE) != [b for b in C.BANDERAS if b in EV.PRUEBA_DE],
   "el diccionario está en el orden de la cabecera: así la garantía de orden no se puede medir")

# ── 3. Sin prueba NO se anota ──────────────────────────────────────────────────────────────
# ⛔ Esto es lo que no se puede aflojar: daría por publicado lo que no lo está.
for vacio in ("", "   ", None):
    ok(EV.ya_hecho(fila(notion_page_id=vacio)) == [],
       "¡un identificador %r cuenta como prueba!" % (vacio,))
ok(EV.ya_hecho(fila()) == [], "sin ningún identificador no debería anotarse nada")

# Una bandera YA puesta no se vuelve a anotar.
ok(EV.ya_hecho(fila(notion_page_created=T, notion_page_id="1a2b")) == [],
   "vuelve a anotar una bandera que ya estaba puesta")
# ⚠️ Y una bandera puesta SIN identificador no se toca: borrarla «para rehacer» sería decidir por
#    nuestra cuenta que algo no se hizo, y eso lo mira una persona.
ok(EV.ya_hecho(fila(notion_page_created=T)) == [],
   "toca una bandera puesta sin identificador")

# Una columna que no es de las cinco no cuenta, aunque tenga valor.
ok(EV.ya_hecho(fila(notion_page_url="https://...")) == [],
   "la URL no es la prueba: la prueba es el id")
ok(EV.ya_hecho(fila(approval_thread_id="19f2")) == [],
   "un id que no está en el mapa no debería anotar nada")

# Entradas raras no revientan.
for raro in (None, [], "chusta", 42, {}):
    ok(EV.ya_hecho(raro) == [], "una fila %r debería dar lista vacía" % type(raro).__name__)

# ── 4. Los motivos ─────────────────────────────────────────────────────────────────────────
m = EV.motivos(fila(notion_page_id="1a2b3c"))
ok(len(m) == 1, "debería haber un motivo: %r" % (m,))
ok("notion_page_created" in m[0] and "notion_page_id" in m[0],
   "el motivo no dice la bandera y su prueba: %r" % (m,))
ok("1a2b3c" in m[0], "el motivo no enseña el identificador, que es lo comprobable: %r" % (m,))
ok("anotarlo" in m[0], "el motivo no dice qué fue lo que falló: %r" % (m,))
ok(EV.motivos(fila()) == [], "sin nada que anotar no debería haber motivos")
ok(EV.motivos(None) == [], "None no debería reventar")

# ── `con_prueba`: de lo prometido, lo que se sostiene ────────────────
_TODAS = ("notion_page_created", "notion_pdf_embedded", "drive_summary_created")
ok(EV.con_prueba(_TODAS, {}, {"notion_page_id": "p-1"}) ==
   ("notion_page_created", "notion_pdf_embedded"),
   u"⛔ marca el resumen sin que nadie devuelva `drive_summary_file_id`")
ok(EV.con_prueba(_TODAS, {}, {"notion_page_id": "p-1", "drive_summary_file_id": "F-1"}) == _TODAS,
   u"con las dos pruebas deberían pasar las tres")
# La prueba vale venga del servicio o de la fila: si no, una reanudación dejaría la bandera
# sin poner para siempre.
ok("drive_summary_created" in EV.con_prueba(_TODAS, {"drive_summary_file_id": "F-vieja"}, {}),
   u"la prueba ya anotada en la fila debería valer")
# ⚠️ Una bandera SIN prueba declarada pasa tal cual: inventarle una sería cambiar de tema.
ok(EV.con_prueba(("notion_pdf_embedded",), {}, {}) == ("notion_pdf_embedded",),
   u"filtra una bandera que no tiene prueba declarada: se quedaría sin poder marcar nada")
ok(EV.con_prueba(_TODAS, {}, {}) == ("notion_pdf_embedded",),
   u"sin ninguna prueba sólo debería pasar la que no la declara: %r"
   % (EV.con_prueba(_TODAS, {}, {}),))
# El orden es el que vino, no el del diccionario: lo que se enseña va en el orden de `ATIENDE`.
ok(EV.con_prueba(("drive_summary_created", "notion_page_created"), {},
                 {"drive_summary_file_id": "F", "notion_page_id": "p"}) ==
   ("drive_summary_created", "notion_page_created"), u"no respeta el orden que vino")
ok(isinstance(EV.con_prueba(_TODAS, {}, {}), tuple), u"debería devolver una tupla")
# ⛔ Un 0 NO es prueba, aquí también: no existe la fila 0 de una hoja.
ok(EV.con_prueba(("base_database_registered",), {}, {"base_database_row": 0}) == (),
   u"⛔ un `base_database_row` de 0 cuela como prueba")
ok(EV.con_prueba(("base_database_registered",), {}, {"base_database_row": 18}) ==
   ("base_database_registered",), u"la fila 18 SÍ es prueba")
# Entradas raras no revientan.
ok(EV.con_prueba((), {}, {}) == () and EV.con_prueba(None, None, None) == (),
   u"entradas vacías no deberían reventar")
ok(EV.con_prueba(_TODAS, "chusta", "chusta") == ("notion_pdf_embedded",),
   u"una fila que no es un diccionario no debería reventar")

print("%d comprobaciones" % hechas[0])
if fallos:
    print("\n%d ROJO(S):" % len(fallos))
    for f_ in fallos:
        print("  - %s" % f_)
    sys.exit(1)
print("verde")
