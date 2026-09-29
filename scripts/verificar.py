#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Releer lo escrito y contrastarlo. Porque una escritura puede no hacer nada y decir que sí.

Por qué existe
--------------
⛔ **Está medido en este proyecto, no supuesto**: el conector de Sheets *«falló **en silencio**
(devolvió vacío, no escribió; verificado releyendo)»*. Por eso `flujos/historico.py`, que sube el
Registro mensual, **relee y contrasta celda a celda** antes de dar el paso por bueno.

El pipeline nuevo escribía y se fiaba. Y fiarse aquí es caro de una forma concreta: la pasada
marca `closed` como hecho, **no vuelve a mirar ese expediente nunca**, y si la celda no se escribió
el trabajo queda deshecho sin que nadie lo sepa. Lo contrario de un error ruidoso.

El problema de verdad: comparar
-------------------------------
No se puede comparar con `==` a secas. Se manda la cadena `"TRUE"` y Sheets, que guarda un
**booleano**, devuelve `True`; se manda el entero `5` y devuelve `"5"`. Un `==` estricto daría
discrepancias en todo y nadie volvería a mirar el informe.

⚠️ Pero aflojar de más es peor: si `"TRUE"` casara con `"FALSE"` por ser los dos texto, la
comprobación diría que todo fue bien **precisamente cuando no**. Aquí se comparan **valores**, no
tipos: `"TRUE"` ≡ `True`, `"5"` ≡ `5`, `"5.0"` ≡ `5` — y nada más.

Cómo se prueba
--------------
`python scripts/test_verificar.py` — sin red ni credenciales.
"""
import sys

for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding="utf-8")
    except Exception:  # pragma: no cover
        pass


_SI = ("true", "verdadero", "si", "sí")
_NO = ("false", "falso", "no")


def mismo_valor(pedido, leido):
    """¿Son el mismo valor, aunque Sheets lo haya devuelto con otro tipo?

    ⚠️ La cadena vacía y `None` cuentan como **lo mismo**: es lo que devuelve una celda vacía, y
    es también lo que se manda para vaciarla. Distinguirlos aquí inventaría una discrepancia en
    cada limpieza de `last_error`.
    """
    a, b = _normal(pedido), _normal(leido)
    return a == b


def _normal(v):
    """El valor en la forma con la que se compara. Nunca se escribe ni se muestra así."""
    if v is None:
        return u""
    if isinstance(v, bool):
        return u"true" if v else u"false"
    if isinstance(v, (int, float)):
        # 5 y 5.0 son el mismo número; 5.5 no es 5.
        return u"%g" % v
    t = str(v).strip()
    b = t.lower()
    if b in _SI:
        return u"true"
    if b in _NO:
        return u"false"
    try:
        return u"%g" % float(t)
    except ValueError:
        return t


def contrastar(pedidas, leidas):
    """`(cuadran, discrepancias)` entre lo que se mandó y lo que hay.

    - `pedidas`: `[(A1, valor)]`, tal cual se mandó.
    - `leidas`: `{A1: valor}` releído **después** de escribir.

    Una celda que **no se pudo releer** cuenta como discrepancia, no como acuerdo: no saber si se
    escribió es justo lo que esta función existe para no dejar pasar.
    """
    discrepancias = []
    for a1, pedido in (pedidas or []):
        clave = str(a1).strip()
        if clave not in (leidas or {}):
            discrepancias.append((clave, pedido, None,
                                  u"no se ha podido releer: no consta que se escribiera"))
            continue
        leido = leidas[clave]
        if not mismo_valor(pedido, leido):
            discrepancias.append((clave, pedido, leido,
                                  u"se escribió %r y hay %r" % (pedido, leido)))
    return (not discrepancias), discrepancias


def informe(cuadran, discrepancias, cuantas):
    """El texto que se enseña cuando algo no cuadró. Vacío si todo fue bien."""
    if cuadran:
        return u""
    lineas = [u"⛔ %d de %d celdas NO quedaron como se pidió. El trabajo se dio por hecho y la "
              u"hoja no lo refleja, así que nadie va a volver a mirarlo."
              % (len(discrepancias), cuantas)]
    for clave, _p, _l, que in discrepancias:
        lineas.append(u"   %s — %s" % (clave, que))
    return u"\n".join(lineas)


if __name__ == "__main__":  # pragma: no cover
    print("Releer y contrastar. Para probarlo: python scripts/test_verificar.py")
