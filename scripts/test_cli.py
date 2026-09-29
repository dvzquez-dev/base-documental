#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Banco de `cli.py`. Sin red, sin credenciales, sin reloj.

⛔ Lo primero que se comprueba es lo único que no puede fallar nunca: **sin `--aplicar` no se
escribe**. Todo lo demás es comodidad; eso es lo que protege una hoja que no tiene deshacer.
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
import cli as CLI

fallos = []
hechas = [0]


def ok(cond, que):
    hechas[0] += 1
    if not cond:
        fallos.append(que)


T, F = "TRUE", "FALSE"
AHORA = "2026-09-29T04:00:00Z"
CAB = ["request_id"] + list(C.BANDERAS) + ["updated_at", "last_error", "retry_count"]
POR_CERRAR = [T, T, T, T, T, T, F, F, T, T, T, T, T, T, T, T, T, T, F]


def fila(rid="R-1"):
    return [rid] + list(POR_CERRAR) + ["", "", ""]


class Doble(object):
    def __init__(self, valores=None, libro=None, revienta=None):
        self.valores = valores if valores is not None else [CAB, fila()]
        self.libro = libro or []
        self.revienta = revienta
        self.llamadas = []
        self.escritas = None

    def leer(self):
        self.llamadas.append("leer")
        if self.revienta == "leer":
            raise RuntimeError(u"la hoja contestó 503")
        return self.valores

    def leer_libro(self):
        self.llamadas.append("leer_libro")
        return self.libro

    def cerrar(self, f):
        self.llamadas.append("cerrar")

    def escribir(self, celdas):
        self.llamadas.append("escribir")
        self.escritas = list(celdas)


# ── 1. Lo que no puede fallar: seco por defecto ────────────────────────────────────────────
d = Doble()
txt, cod = CLI.correr([], d, ahora=AHORA)
ok("escribir" not in d.llamadas, u"¡una pasada SIN --aplicar escribió! %r" % (d.llamadas,))
ok("cerrar" not in d.llamadas, u"¡una pasada SIN --aplicar ejecutó! %r" % (d.llamadas,))
ok("SECO" in txt, u"el informe no dice que fue en seco: %r" % txt[:70])
ok(cod == 0, u"una pasada seca limpia debería salir en 0, sale %d" % cod)
# ⚠️ Y en seco SÍ se ve qué se escribiría: si no, el modo seco no sirve de nada.
ok("HAR" in txt, u"la pasada seca no dice qué haría")

d = Doble()
txt, cod = CLI.correr(["--aplicar"], d, ahora=AHORA)
ok("cerrar" in d.llamadas and "escribir" in d.llamadas,
   u"con --aplicar no ejecuta ni escribe: %r" % (d.llamadas,))
ok("APLICADA" in txt, u"el informe no dice que se aplicó")

# ── 2. Los argumentos ──────────────────────────────────────────────────────────────────────
op, m = CLI.parsear([])
ok(op == {"aplicar": False, "limite": None, "revisar": False}, u"los valores por defecto: %r" % (op,))
ok(m == [], u"sin argumentos no debería haber motivos")
ok(CLI.parsear(["--aplicar"])[0]["aplicar"] is True, u"no reconoce --aplicar")
ok(CLI.parsear(["--limite", "3"])[0]["limite"] == 3, u"no reconoce --limite")
ok(CLI.parsear(["--revisar"])[0]["revisar"] is True, u"no reconoce --revisar")
ok(CLI.parsear(["--aplicar", "--limite", "5"])[0] == {"aplicar": True, "limite": 5,
                                                      "revisar": False},
   u"no combina --aplicar con --limite")

# ⛔ Un argumento que no se entiende PARA la pasada. Ignorarlo es como un `--aplciar` mal escrito
#    acaba en una pasada seca que alguien da por aplicada.
for malo, trozo in ((["--aplciar"], "no entiendo"),
                    (["--limite"], "sin número"),
                    (["--limite", "x"], "no es un número"),
                    (["--limite", "0"], "no toca ningún expediente"),
                    (["--limite", "-2"], "no toca ningún expediente"),
                    (["algo"], "no entiendo")):
    op, m = CLI.parsear(malo)
    ok(op is None, u"%r debería parar la pasada" % (malo,))
    ok(m and trozo in m[0], u"el motivo de %r no lo explica: %r" % (malo, m))

op, m = CLI.parsear(["--revisar", "--aplicar"])
ok(op is None and m and "Elige uno" in m[0],
   u"--revisar con --aplicar debería pararse: %r" % (m,))
op, m = CLI.parsear(["--ayuda"])
ok(op is None and m and "uso:" in m[0], u"la ayuda no sale: %r" % (m,))

txt, cod = CLI.correr(["--aplciar"], Doble())
ok(cod == 2, u"un argumento malo debería salir en 2, sale %d" % cod)
ok("no entiendo" in txt, u"no explica el argumento malo")

# ── 3. El tope ─────────────────────────────────────────────────────────────────────────────
d = Doble(valores=[CAB] + [fila("R-%d" % i) for i in range(1, 6)])
txt, _c = CLI.correr(["--aplicar", "--limite", "2"], d, ahora=AHORA)
ok(d.llamadas.count("cerrar") == 2,
   u"el tope no limita: cierra %d de 5" % d.llamadas.count("cerrar"))
# ⚠️ El tope se aplica a las filas, no a la hoja: cortar la hoja se llevaría la CABECERA.
ok(d.escritas, u"con tope debería escribirse algo: %r" % (d.escritas,))
ok(all(c[0][0].isalpha() for c in d.escritas),
   u"las celdas no tienen letra de columna: se ha perdido la cabecera: %r" % (d.escritas,))

d = Doble(valores=[CAB] + [fila("R-%d" % i) for i in range(1, 6)])
CLI.correr(["--aplicar"], d, ahora=AHORA)
ok(d.llamadas.count("cerrar") == 5, u"sin tope deberían tocarse las 5")

# ── 4. El repaso ───────────────────────────────────────────────────────────────────────────
# 📏 La fila real con closed=TRUE y todo lo demás en FALSE, y una fila real del Libro.
CERRADA_VACIA = ["R-real-2"] + [T] + [F] * 17 + [T] + ["", "", ""]
LIBRO_MALO = [["Informe_I-1008_25", "Informe_l-1005_25.pdf", "Informe, I+D"]]
d = Doble(valores=[CAB, CERRADA_VACIA], libro=LIBRO_MALO)
txt, cod = CLI.correr(["--revisar"], d, ahora=AHORA)
ok("cerrar" not in d.llamadas, u"¡el repaso ejecutó el pipeline! %r" % (d.llamadas,))
ok("escribir" not in d.llamadas, u"¡el repaso escribió!")
ok("CIERRE" in txt, u"el repaso no ve el cierre injustificado: %r" % txt)
ok("LIBRO" in txt, u"el repaso no ve el defecto del Libro: %r" % txt)
ok(cod == 1, u"un repaso con cosas que no cuadran debería salir en 1, sale %d" % cod)
ok("R-real-2" in txt, u"el repaso no identifica la fila por su request_id")

# ⚠️ La fila «limpia» tiene que estar además CERRADA: `fila()` está publicada y sin cerrar, y
#    el revisor tiene razón en señalarla — lo cual es justo lo que este banco quiere que haga.
CERRADA_OK = ["R-ok"] + POR_CERRAR[:-1] + [T] + ["", "", ""]
d = Doble(valores=[CAB, CERRADA_OK], libro=[])
txt, cod = CLI.correr(["--revisar"], d, ahora=AHORA)
ok("todo cuadra" in txt, u"un repaso limpio no lo dice: %r" % txt)
ok(cod == 0, u"un repaso limpio debería salir en 0, sale %d" % cod)
# ⛔ Y el de al lado: una publicada SIN cerrar SÍ sale, que es media razón de ser del repaso.
d = Doble(valores=[CAB, fila()], libro=[])
txt, _c = CLI.correr(["--revisar"], d, ahora=AHORA)
ok("listo para cerrar" in txt,
   u"el repaso no ve un expediente terminado que nadie cerró: %r" % txt)

# La cabecera duplicada sale en el repaso.
d = Doble(valores=[CAB + ["closed"], fila() + [""]])
txt, _c = CLI.correr(["--revisar"], d)
ok("CABECERA" in txt and "closed" in txt, u"el repaso no ve la columna duplicada: %r" % txt)

# Sin `leer_libro` el repaso sigue funcionando: no todo el mundo tiene acceso al Libro.
class SoloHoja(object):
    def leer(self):
        return [CAB, CERRADA_VACIA]

txt, cod = CLI.correr(["--revisar"], SoloHoja())
ok("CIERRE" in txt, u"sin acceso al Libro el repaso debería mirar igual la hoja: %r" % txt)

# ── 5. Los códigos de salida ───────────────────────────────────────────────────────────────
# ⚠️ Es lo único que mira una tarea programada: una pasada con errores en 0 se ve VERDE para
#    siempre en el historial.
class SinLeer(object):
    pass

txt, cod = CLI.correr([], SinLeer())
ok(cod == 2, u"sin `leer` debería salir en 2, sale %d" % cod)
# ⛔ Se ata al mensaje CONCRETO, no a que aparezca la palabra «leer»: el error genérico
#    «al leer la hoja: TypeError…» también la lleva, así que las dos ramas satisfacían la
#    comprobación y la guarda salía CIEGA al mutarla.
ok("no existe" in txt, u"no dice que `servicios.leer` NO EXISTE: %r" % txt)
ok("TypeError" not in txt,
   u"llega a llamar a `None()` en vez de decirlo antes: %r" % txt)

d = Doble(revienta="leer")
txt, cod = CLI.correr([], d)
ok(cod == 2, u"si falla la lectura debería salir en 2, sale %d" % cod)
ok("503" in txt, u"el error de lectura no conserva lo que dijo el mundo: %r" % txt)

# Una pasada que no puede anotar lo hecho NO sale en 0.
d = Doble(valores=[CAB + ["closed"], fila() + [""]])
txt, cod = CLI.correr(["--aplicar"], d, ahora=AHORA)
ok(cod == 1, u"con avisos debería salir en 1, sale %d" % cod)

# ── El repaso canta las filas DESPLAZADAS ────────────────────────
# ⚠️ Escribir el detector y no llamarlo desde el repaso lo deja siendo una función que nadie
#    ejecuta: la avería de «escrita entera, muerta en el cable de en medio».
_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_CAB2 = ["request_id", "range_end", "annex_copied_count", "closed"]
_lineas, _n = CLI.revisar_datos([_CAB2, ["SOL-9", "Es un informe bimensual", _MIME, "FALSE"]], [])
ok(any(l.startswith("COLUMNA") for l in _lineas),
   u"⛔ el repaso no canta una fila desplazada: %r" % (_lineas,))
ok(any("annex_copied_count" in l for l in _lineas),
   u"el aviso no dice en qué columna: %r" % (_lineas,))
ok(any("SOL-9" in l for l in _lineas), u"el aviso no dice de qué expediente es")
ok(_n == len(_lineas), u"el recuento y las líneas no cuadran")
_lineas, _ = CLI.revisar_datos([_CAB2, ["SOL-8", "6499", "7", "FALSE"]], [])
ok(not [l for l in _lineas if l.startswith("COLUMNA")],
   u"canta sobre una fila sana: %r" % (_lineas,))

# ── El repaso canta lo que no cuadra en los ANEXOS ───────────────
_CAB3 = ["request_id", "annex_drive_file_ids_json", "annex_final_file_ids_json",
         "annex_copied_count", "closed"]
_l, _ = CLI.revisar_datos(
    [_CAB3, ["SOL-7", "a, b", '["x","y"]', "1", "FALSE"]], [])
ok(any(l.startswith("ANEXOS") for l in _l), u"⛔ el repaso no mira los anexos: %r" % (_l,))
ok(any("miente" in l for l in _l), u"no dice qué no cuadra: %r" % (_l,))
ok(any("SOL-7" in l for l in _l), u"no dice de qué expediente es")
# ⚠️ Y la fila real, que trae los ids por comas y está en regla, **no canta**: un aviso que
#    sale sobre trabajo bien hecho enseña a ignorarlo.
_l, _ = CLI.revisar_datos(
    [_CAB3, ["SOL-6", "a, b", '["x", "y"]', "2", "FALSE"]], [])
ok(not [l for l in _l if l.startswith("ANEXOS")],
   u"⛔ canta sobre unos anexos en regla que venían por comas: %r" % (_l,))

# ── EL WORKFLOW TIENE QUE PASAR TODO LO QUE EL CÓDIGO LEE ──────────
# ⛔⛔ Medido el 29/09: el código que corre la pasada lee **cuatro** variables de entorno y el
#    workflow declaraba **tres**. La que faltaba era `DOMINIO_EQUIPO`, o sea que la primera
#    publicación de verdad se habría parado en seco — con todos los secretos puestos y sin que
#    nada en el repo lo dijera. Las dos mitades del contrato viven en ficheros distintos y en
#    lenguajes distintos, que es justo donde nadie mira.
# ⚠️ Se descubren **los módulos que el propio `cli.py` alcanza**, con `ast`: escribir la lista
#    a mano es escribir la tercera copia del contrato.
import ast as _ast
import io as _io
import re

_AQUI = os.path.dirname(os.path.abspath(__file__))


def _lee_entorno(mod, vistos):
    """Las variables de entorno que lee `mod` y todo lo que importa, transitivamente."""
    if mod in vistos:
        return set()
    vistos.add(mod)
    ruta = os.path.join(_AQUI, mod + ".py")
    if not os.path.exists(ruta):
        return set()
    arbol = _ast.parse(_io.open(ruta, encoding="utf-8").read())
    fuera = set()
    for nodo in _ast.walk(arbol):
        if isinstance(nodo, _ast.Import):
            for a_ in nodo.names:
                fuera |= _lee_entorno(a_.name, vistos)
        elif isinstance(nodo, _ast.ImportFrom) and nodo.module:
            fuera |= _lee_entorno(nodo.module, vistos)
        elif isinstance(nodo, _ast.Call):
            f = nodo.func
            if (isinstance(f, _ast.Attribute) and f.attr == "get"
                    and isinstance(f.value, _ast.Attribute) and f.value.attr == "environ"
                    and nodo.args and isinstance(nodo.args[0], _ast.Constant)):
                fuera.add(nodo.args[0].value)
        elif (isinstance(nodo, _ast.Subscript) and isinstance(nodo.value, _ast.Attribute)
              and nodo.value.attr == "environ" and isinstance(nodo.slice, _ast.Constant)):
            fuera.add(nodo.slice.value)
    return fuera


_PEDIDAS = set(v for v in _lee_entorno("cli", set()) if isinstance(v, str) and v.isupper())
_YML = os.path.join(os.path.dirname(_AQUI), ".github", "workflows", "pipeline.yml")
_TXT = _io.open(_YML, encoding="utf-8").read() if os.path.exists(_YML) else ""

# ⛔⛔ Se leen las DECLARACIONES, no el texto del fichero. Con un `in _TXT` la comprobación
#    salió **CIEGA**: el comentario que yo mismo escribí al añadir `DOMINIO_EQUIPO` nombra la
#    variable, así que borrar la línea que la pasa **no cambiaba nada**. Es la trampa de «el
#    comando que re-mide cuenta la prosa del arreglo», y aquí la escribí yo.
_DECLARADAS = set(re.findall(r"(?m)^\s*([A-Z][A-Z0-9_]+):\s*\$\{\{", _TXT))

ok(_TXT, u"no se encuentra `.github/workflows/pipeline.yml`: el contrato no se puede mirar")
ok("DOMINIO_EQUIPO" in _PEDIDAS,
   u"⚠️ el descubridor no ve `DOMINIO_EQUIPO`: mide mal y diría que todo cuadra")
ok(len(_PEDIDAS) >= 4, u"el descubridor ve muy poco (%d): %r" % (len(_PEDIDAS), sorted(_PEDIDAS)))
ok(len(_DECLARADAS) >= 4,
   u"⚠️ el lector del workflow ve %d declaraciones: si viera 0, todo saldría «falta» y el "
   u"caso sería inútil al revés" % len(_DECLARADAS))
_faltan = sorted(v for v in _PEDIDAS if v not in _DECLARADAS)
ok(_faltan == [],
   u"⛔ el workflow no pasa %r: la pasada se pararía con los secretos puestos y sin que nada "
   u"en el repo lo dijera" % (_faltan,))

print("%d comprobaciones" % hechas[0])
if fallos:
    print("\n%d ROJO(S):" % len(fallos))
    for f_ in fallos:
        print("  - %s" % f_)
    sys.exit(1)
print("verde")
