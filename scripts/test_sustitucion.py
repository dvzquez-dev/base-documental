#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Banco de `sustitucion.py`. Sin red, sin credenciales, sin reloj.

⛔ Las filas son **las reales** de `SOLICITUDES` (29/09/2026), con las **cuatro codificaciones**
que de verdad tiene `replaces_document`: `"No"`, `"Sí"`, `"TRUE"` y un `request_id` entero.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding="utf-8")
    except Exception:
        pass

import sustitucion as SU

fallos = []
hechas = [0]


def ok(cond, que):
    hechas[0] += 1
    if not cond:
        fallos.append(que)


def f(rid, ref, reemplaza="", refrem="", motivo=""):
    return {"request_id": rid, "reference": ref, SU.COL_REEMPLAZA: reemplaza,
            SU.COL_REFERENCIA: refrem, SU.COL_MOTIVO: motivo}


# 📏 Las filas 3 a 16 reales, con sus tres columnas de sustitución tal cual.
F3 = f("SOL-DOC-20260702-145808-1D8KJ9WF", "Acta_S-6301_26", "No")
F4 = f("SOL-DOC-20260703-115545-1IJZX9QI", "Informe_S-1008_26", u"Sí", "Informe_S-1008_26",
       u"Errata en el documento y cambio en el título y etiquetas")
F7 = f("SOL-DOC-20260705-181606-1ZULU2CY", "Informe_S-6009_26", "No")
F8 = f("SOL-DOC-20260706-202210-1I8XUUNL", "Informe_S-6009_26",
       "SOL-DOC-20260705-181606-1ZULU2CY", "Informe_S-6009_26",
       "Se habia subido una version anterior del informe por error.")
F9 = f("SOL-DOC-20260708-184756-1VAXBFDH", "Informe_S-6009_26",
       "SOL-DOC-20260706-202210-1I8XUUNL", "Informe_S-6009_26", "cambios en el formato")
F13 = f("SOL-DOC-20260709-144314-1KK9PPZQ", "Informe_S-1009_26")
F14 = f("SOL-DOC-20260703-130905-1RM72OTI", "", "SOL-DOC-20260703-115545-1IJZX9QI",
        "Informe_S-1008_26", "Errata en el documento y cambio en el titulo y etiquetas")
# ⛔ La que dice `TRUE` a secas: sin `request_id`, lo único que la ata al original es la
#    referencia. Es la que salva —o pierde— el caso de la fila 13.
F16 = f("SOL-DOC-20260713-230709-B9TTE7W", "Informe_S-1009_26", "TRUE", "Informe_S-1009_26",
        u"Corrección de un párrafo que no debía estar en el documento final")
REALES = [F3, F4, F7, F8, F9, F13, F14, F16]

# ── 1. Las cuatro codificaciones ───────────────────────────────────────────────────────────
ok(SU.declara(F3) is False, u"«No» no declara ninguna sustitución")
ok(SU.declara(F4) is True, u"⛔ «Sí» declara una sustitución y se está perdiendo")
ok(SU.declara(F8) is True, u"un `request_id` declara una sustitución")
ok(SU.declara(F16) is True, u"⛔ «TRUE» declara una sustitución y se está perdiendo")
ok(SU.declara(F13) is False, u"la columna vacía no declara nada")
ok(SU.declara({}) is False and SU.declara(None) is False, u"una fila vacía no revienta")
ok(SU.declara({SU.COL_REEMPLAZA: "  no  "}) is False, u"no recorta ni ignora la caja")
ok(SU.declara({SU.COL_REEMPLAZA: "FALSE"}) is False, u"«FALSE» tampoco declara nada")

ok(SU.apunta_a(F8) == ("SOL-DOC-20260705-181606-1ZULU2CY", "Informe_S-6009_26"),
   u"no saca el id y la referencia: %r" % (SU.apunta_a(F8),))
# ⛔ Con «Sí» o «TRUE» NO hay id: leer la columna como un id perdería estas dos filas.
ok(SU.apunta_a(F4) == (None, "Informe_S-1008_26"),
   u"⛔ toma el «Sí» por un `request_id`: %r" % (SU.apunta_a(F4),))
ok(SU.apunta_a(F16) == (None, "Informe_S-1009_26"),
   u"⛔ toma el «TRUE» por un `request_id`: %r" % (SU.apunta_a(F16),))
ok(SU.apunta_a(F3) == (None, None), u"una fila que no sustituye no apunta a nadie")
ok(SU.apunta_a("chusta") == (None, None), u"una entrada rara no revienta")

# ── 2. Quién ya recibió su reentrega ───────────────────────────────────────────────────────
_claves = SU.sustituidas(REALES)
ok(SU.esta_sustituida(F7, _claves) is True,
   u"⛔ la fila 7 YA fue reentregada (por la 8) y el pipeline la deja esperando para siempre")
ok(SU.esta_sustituida(F8, _claves) is True,
   u"⛔ la fila 8 YA fue reentregada (por la 9)")
# ⛔ ÉSTE es el caso que sólo se salva trazando por REFERENCIA: la 16 dice «TRUE», sin id.
ok(SU.esta_sustituida(F13, _claves) is True,
   u"⛔ la fila 13 fue reentregada por la 16, que no trae `request_id`: hay que trazar por "
   u"la REFERENCIA o se pierde")
ok(SU.esta_sustituida(F3, _claves) is False,
   u"⚠️ la fila 3 NO ha sido reentregada: espera de verdad, y decir lo contrario la entierra")
ok(SU.esta_sustituida(F9, _claves) is False, u"a la última de la cadena no la sustituye nadie")
ok(SU.esta_sustituida({}, _claves) is False, u"una fila vacía no está sustituida")
ok(SU.esta_sustituida(F7, {}) is False, u"sin claves, nadie está sustituido")
ok(SU.esta_sustituida(F7, None) is False, u"unas claves None no revientan")
ok(SU.sustituidas([]) == {} and SU.sustituidas(None) == {}, u"sin filas, sin claves")
# ⛔⛔ En una cadena de TRES —la real, `Informe_S-6009_26`— las tres comparten la
#    referencia. Si la referencia contara siempre, la ÚLTIMA quedaría marcada como
#    sustituida por una de las anteriores y el expediente vivo **se enterraría solo**.
ok(_claves.get("Informe_S-6009_26") is None,
   u"⛔ la referencia de una cadena con ids cuenta como clave: %r" % (_claves,))
ok(_claves.get("Informe_S-1009_26") == "SOL-DOC-20260713-230709-B9TTE7W",
   u"la referencia SÍ cuenta cuando la reentrega no trae id: %r" % (_claves,))
# ⚠️ Y nadie se sustituye a sí mismo: la reentrega lleva la MISMA referencia.
ok(SU.esta_sustituida(F16, _claves) is False,
   u"⛔ la propia reentrega se da por sustituida y se entierra sola")
# ⚠️ Y `quien_sustituye` es la última puerta: `esta_sustituida` la envuelve, y `pipeline` la
#    llama. El criterio llegó a estar escrito DOS veces y la copia salió **ciega** justo a la
#    mutación que le quitaba la exclusión de sí misma.
ok(SU.quien_sustituye(F7, _claves) == "SOL-DOC-20260706-202210-1I8XUUNL",
   u"no dice QUIÉN la reentregó: %r" % (SU.quien_sustituye(F7, _claves),))
ok(SU.quien_sustituye(F13, _claves) == "SOL-DOC-20260713-230709-B9TTE7W",
   u"la que sólo se traza por referencia no dice quién: %r"
   % (SU.quien_sustituye(F13, _claves),))
ok(SU.quien_sustituye(F16, _claves) is None, u"⛔ la reentrega se señala a sí misma")
ok(SU.quien_sustituye(F9, _claves) is None, u"la última de la cadena no la sustituye nadie")
ok(SU.quien_sustituye({}, _claves) is None and SU.quien_sustituye(None, None) is None,
   u"entradas vacías no revientan")
# El que declara sin `request_id` propio se nombra igual, para que el aviso sea accionable.
ok(SU.quien_sustituye({"request_id": "A"}, {"A": ""}) == u"otra fila",
   u"sin id de quien sustituye, el aviso debería decir algo en vez de nada")
ok(SU.sustituidas(["chusta", None]) == {}, u"lo que no es un registro se salta")

# ── 3. Lo que no cuadra ────────────────────────────────────────────────────────────────────
ok(SU.revisar(REALES) == [], u"las filas reales están en regla: %r" % (SU.revisar(REALES),))
ok(SU.revisar([]) == [] and SU.revisar(None) == [], u"sin filas no hay avisos")

# Dice ser reentrega y no dice de qué.
_a = SU.revisar([f("SOL-X", "Ref_X", u"Sí")])
ok(_a and "no dice de qué" in _a[0][2], u"⛔ una reentrega sin destino debería cantarse: %r" % (_a,))
ok(_a and "esperando un reenvío que ya llegó" in _a[0][2],
   u"el motivo no dice la consecuencia: %r" % (_a,))

# Apunta a un id que no existe.
_a = SU.revisar([f("SOL-X", "Ref_X", "SOL-QUE-NO-ESTA", "Ref_X", "motivo")])
ok(any("no está en la hoja" in x[2] for x in _a), u"⛔ un id inexistente no se canta: %r" % (_a,))
# Apunta a una referencia que no existe.
_a = SU.revisar([f("SOL-X", "Ref_X", u"Sí", "Ref_QUE_NO_ESTA", "motivo")])
ok(any("no hay ninguna fila con ella" in x[2] for x in _a),
   u"⛔ una referencia inexistente no se canta: %r" % (_a,))
# Se sustituye a sí misma.
_a = SU.revisar([f("SOL-X", "Ref_X", "SOL-X", "Ref_X", "motivo")])
ok(any("sí misma" in x[2] for x in _a), u"⛔ una fila que se sustituye a sí misma: %r" % (_a,))
# Sin motivo escrito.
_a = SU.revisar([f("SOL-X", "Ref_X", u"Sí", "Ref_X")])
ok(any("sin motivo escrito" in x[2] for x in _a), u"una reentrega sin motivo: %r" % (_a,))
ok(any("abrir los dos documentos" in x[2] for x in _a),
   u"el motivo no dice qué cuesta: %r" % (_a,))
# ⚠️ Y una fila que NO declara sustitución no se mira: exigirle motivo la pondría roja por
#    hacer lo correcto.
ok(SU.revisar([F3]) == [], u"⛔ canta sobre una fila que no dice ser reentrega")
ok(all(x[0] >= 2 for x in SU.revisar([f("SOL-X", "R", u"Sí")])),
   u"el número de fila no cuenta la cabecera")

print("%d comprobaciones" % hechas[0])
if fallos:
    print("\n%d ROJO(S):" % len(fallos))
    for f_ in fallos:
        print("  - %s" % f_)
    sys.exit(1)
print("verde")
