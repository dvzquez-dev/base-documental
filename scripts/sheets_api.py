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

3. ⛔⛔ **Las columnas de banderas guardan BOOLEANOS, no texto — y eso decide
   `valueInputOption`.** Con `RAW`, la cadena `"TRUE"` entra como **texto** y quedaría un texto
   entre booleanos: `es_si` de nuestro lado lo aceptaría igual, pero cualquier `COUNTIF(rango;
   VERDADERO)` montado sobre la hoja **dejaría de contarlo**, y sin dar ningún error.

   📏 **Cómo se midió, porque no era obvio**: el conector devuelve `"TRUE"` tanto si es
   booleano como si es texto. Se miró la **alineación**: `B2` (un número) sale `RIGHT` y `A2`/`C2`
   (texto) salen `LEFT` — o sea que la herramienta informa de la alineación **efectiva**, defectos
   incluidos, aunque su descripción diga que sólo devuelve lo aplicado a mano. Y `AW3` (bandera)
   sale `CENTER` mientras sus **vecinas inmediatas** `AX3`/`AY3` (identificadores de texto) salen
   `LEFT`: el centrado es **por tipo de celda**, no un formato puesto al bloque. `CENTER` es el
   defecto de un booleano.

   ✅ Por eso el modo por defecto es **`USER_ENTERED`**.

   ⚠️ **Y `USER_ENTERED` trae su propio filo**: un texto que empiece por `=`, `+`, `-` o `@` lo
   interpreta como **fórmula**. Un `last_error` que empezara así no se guardaría como el mensaje
   que es. Por eso se rechaza — no se escapa a escondidas: escapar cambiaría lo que se guarda sin
   decirlo, y quien lea la celda no sabría que no es lo que se escribió.

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
MODO_POR_DEFECTO = "USER_ENTERED"

# ⛔ Fila **2 o mayor**: la 1 es la cabecera y escribir ahí renombra columnas. Y el `$` del final
#    es lo que impide que `A2:B9` o `A:A` se cuelen como si fueran una celda.
_CELDA = re.compile(r"^[A-Z]{1,3}[2-9][0-9]*$|^[A-Z]{1,3}[1-9][0-9]+$")


# ⚠️ Los cuatro caracteres con los que Sheets empieza a leer una fórmula.
_ARRANQUES = ("=", "+", "-", "@")


def es_formula(valor):
    """¿Este valor lo leería Sheets como una fórmula con `USER_ENTERED`?

    ⚠️ Un número negativo (`-3`, `-3.5`) **no** lo es: empieza por `-` pero Sheets lo entiende
    como el número que es. Rechazarlo sería un falso rojo sobre un valor perfectamente normal,
    y una guarda que griñe por lo correcto se acaba quitando.
    """
    # (sin el `isinstance` de números que había aquí: el `float()` de abajo ya los deja pasar,
    #  así que la condición no podía cambiar el resultado y salía ciega al mutarla. Es la tercera
    #  vez esta noche con esta forma: una guarda defensiva que otra rama de más abajo ya cubre.)
    t = str(valor if valor is not None else "").strip()
    if not t or t[0] not in _ARRANQUES:
        return False
    try:
        float(t)
    except ValueError:
        return True
    return False


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
        if modo == "USER_ENTERED" and es_formula(valor):
            motivos.append(u"el valor de %s empieza por %r y Sheets lo guardaría como FÓRMULA, no "
                           u"como el texto que es: %r" % (a1, str(valor).strip()[0], valor))
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
