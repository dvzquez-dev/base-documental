#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""El cuerpo que espera `values.batchUpdate` de Sheets. Sin tocar la red.

Dos trampas, las dos medidas
----------------------------
1. ⛔ **El nombre de la pestaña hay que entrecomillarlo si lleva espacios.** No es hipotético:
   la pestaña del Libro de Datos se llama **«Base de Datos»**. Sin comillas, `Base de Datos!A2`
   no es un rango válido y la escritura se pierde entera.

2. ⛔⛔ **Un rango mal formado no falla: escribe donde no toca.** `SOLICITUDES!A` se interpreta
   como `A1` — o sea, **la cabecera** —, y `SOLICITUDES!A:A` es **la columna entera**. Mandar
   `values: [[x]]` contra una columna entera no da error: escribe en su primera celda. Por eso
   aquí una referencia que no tenga la forma `<LETRAS><NÚMERO≥2>` **no se manda**.

La pregunta abierta, escrita en vez de adivinada
-----------------------------------------------
⚠️ `valueInputOption` decide si `"TRUE"` entra como **texto** (`RAW`) o Sheets lo convierte en el
**booleano** `TRUE` (`USER_ENTERED`). No se ha podido medir cómo están hoy las columnas de
banderas: el conector devuelve `"TRUE"` en los dos casos, porque convierte a texto al leer.

Por defecto va **`RAW`**, que escribe exactamente lo que se le da y es la opción que no
reinterpreta nada. Si resulta que las columnas guardan booleanos de verdad, hay que pasar
`USER_ENTERED` — y conviene saberlo antes de la primera pasada con `--aplicar`, porque una
columna con las dos cosas mezcladas rompe cualquier `COUNTIF` que haya montado encima.

Cómo se prueba
--------------
`python scripts/test_sheets_api.py` — sin red ni credenciales.
"""
import re
import sys

for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding="utf-8")
    except Exception:  # pragma: no cover
        pass


MODOS = ("RAW", "USER_ENTERED")
MODO_POR_DEFECTO = "RAW"

# ⛔ Fila **2 o mayor**: la 1 es la cabecera y escribir ahí renombra columnas. Y el `$` del final
#    es lo que impide que `A2:B9` o `A:A` se cuelen como si fueran una celda.
_CELDA = re.compile(r"^[A-Z]{1,3}[2-9][0-9]*$|^[A-Z]{1,3}[1-9][0-9]+$")


def es_celda(a1):
    """¿Es una referencia a UNA celda de datos? (`AW2` sí; `A1`, `A`, `A:A` y `A2:B3` no)."""
    return bool(_CELDA.match(str(a1 or "").strip()))


def nombre_pestana(pestana):
    """El nombre listo para meter en un rango, entrecomillado si hace falta.

    ⚠️ La comilla simple dentro del nombre **se duplica**, que es como se escapa en A1. Un nombre
    con apóstrofo sin escapar cierra la cadena antes de tiempo y el rango apunta a otro sitio.
    """
    n = str(pestana if pestana is not None else "").strip()
    if not n:
        return None
    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", n) and not re.match(r"^[A-Z]{1,3}[0-9]+$", n):
        return n
    return u"'%s'" % n.replace(u"'", u"''")


def rango(pestana, a1):
    """`'Base de Datos'!A2`, o `None` si la pestaña o la celda no valen."""
    n = nombre_pestana(pestana)
    if n is None or not es_celda(a1):
        return None
    return u"%s!%s" % (n, str(a1).strip())


def cuerpo_batch(pestana, celdas, modo=MODO_POR_DEFECTO):
    """`(cuerpo, motivos)` para `values.batchUpdate`. Con motivos, `cuerpo` es `None`.

    ⛔ Si **una** celda es inválida no se manda **ninguna**. Una escritura parcial deja la fila en
    un estado que no corresponde a nada, y además nadie vuelve a mirarla: la pasada dice que hizo
    su trabajo.
    """
    motivos = []

    if modo not in MODOS:
        motivos.append(u"`valueInputOption` %r no existe: los válidos son %s"
                       % (modo, u", ".join(MODOS)))

    if nombre_pestana(pestana) is None:
        motivos.append(u"sin nombre de pestaña: el rango apuntaría a la hoja entera")

    celdas = list(celdas or [])
    if not celdas:
        motivos.append(u"no hay ninguna celda que escribir")

    datos, vistas = [], {}
    for a1, valor in celdas:
        if not es_celda(a1):
            motivos.append(u"%r no es una celda de datos: un rango así no falla, escribe donde "
                           u"no toca (la cabecera, o la primera celda de la columna entera)" % (a1,))
            continue
        # (sin `.upper()`: `es_celda` ya ha rechazado la minúscula un par de líneas antes,
        #  así que normalizar la caja aquí no puede cambiar el resultado — y una condición
        #  que no puede cambiar nada sale ciega al mutarla.)
        clave = str(a1).strip()
        if clave in vistas and vistas[clave] != valor:
            motivos.append(u"la celda %s se escribiría dos veces con valores distintos (%r y %r): "
                           u"gana la última y nadie sabría cuál" % (clave, vistas[clave], valor))
            continue
        if clave in vistas:
            continue
        vistas[clave] = valor
        datos.append({"range": rango(pestana, clave), "values": [[valor]]})

    if motivos:
        return None, motivos
    return {"valueInputOption": modo, "data": datos}, []


if __name__ == "__main__":  # pragma: no cover
    print("El cuerpo para Sheets. Para probarlo: python scripts/test_sheets_api.py")
