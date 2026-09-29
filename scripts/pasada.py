#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""La pasada entera: leer la hoja, decidir, ejecutar, y **escribir lo que se hizo**.

El cable que faltaba
--------------------
`ejecutor.ejecutar_una` llama al servicio y **devuelve** qué banderas quedarían puestas… y hasta
aquí nadie las escribía. Eso es una capacidad escrita entera y muerta en el cable de en medio: el
trabajo se hace, y la hoja sigue diciendo que está por hacer, así que la pasada siguiente lo repite.

⛔ **Y repetirlo no es inocente**: volver a publicar lo ya publicado es como se crean las páginas
duplicadas en Notion.

Lo que se escribe, y por qué eso
--------------------------------
- Las **banderas** que la acción promete, a `TRUE`.
- **`updated_at`** con la hora que se le pase. El reloj va **inyectado**: un banco que mira la hora
  del sistema falla un día al año y nadie sabe por qué.
- Si algo revienta, **`last_error`** con el motivo y **`retry_count`** subido en uno. Guardar el
  error en la fila es lo que hace que un fallo se vea al mirar la hoja, en vez de quedarse en la
  consola de quien corrió la pasada.

Seca por defecto, igual que el ejecutor.

Cómo se prueba
--------------
`python scripts/test_pasada.py` — sin red ni credenciales.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding="utf-8")
    except Exception:  # pragma: no cover
        pass

import ejecutor as E
import hoja as H


COL_ACTUALIZADO = "updated_at"
COL_ERROR = "last_error"
COL_INTENTOS = "retry_count"


def _entero(v):
    """El `retry_count` de una celda. Una celda vacía o rara vale 0, no revienta."""
    try:
        # (el `or 0` sobraba: `int("")` ya cae en el `except` de abajo, y una condición que
        #  no puede cambiar el resultado sale ciega al mutarla.)
        return int(str(v).strip())
    except (TypeError, ValueError):
        return 0


def cambios_de(resultado, fila, ahora=None):
    """Qué columnas hay que escribir para un `Resultado`. `{}` si no hay nada que escribir.

    ⚠️ Una fila que se queda quieta no escribe **nada**, ni siquiera `updated_at`. Tocar la fila
    para decir que no se hizo nada llena la hoja de ruido y, peor, hace que «última modificación»
    deje de significar «última vez que pasó algo».
    """
    fila = fila if isinstance(fila, dict) else {}

    if resultado.error:
        cambios = {COL_ERROR: resultado.error,
                   COL_INTENTOS: _entero(fila.get(COL_INTENTOS)) + 1}
        if ahora:
            cambios[COL_ACTUALIZADO] = ahora
        return cambios

    # ⛔ La fila SECA calcula sus celdas igual que la hecha. Si no, una pasada en seco
    #    devuelve **cero celdas** y no enseña nada de lo que tocaría — que era su única razón de
    #    ser. Lo dijo una mutación que salió ciega: `if aplicar and celdas` no podía distinguirse
    #    de `if celdas` **porque en seco nunca había celdas**. El guardia parecía proteger algo
    #    que ya era imposible, y lo que fallaba de verdad era la pasada seca.
    if not (resultado.hecho or resultado.seco):
        return {}

    cambios = dict((b, "TRUE") for b in resultado.banderas)
    if ahora:
        cambios[COL_ACTUALIZADO] = ahora
    # ⛔ Al salir bien se LIMPIA el error anterior. Si no, una fila que falló el martes y funcionó
    #    el miércoles se queda para siempre con el error del martes escrito, y quien mire la hoja
    #    arregla un problema que ya no existe.
    if str(fila.get(COL_ERROR) or "").strip():
        cambios[COL_ERROR] = ""
    return cambios


def correr(valores, servicios, aplicar=False, ahora=None):
    """La pasada entera sobre los valores crudos de la hoja (cabecera incluida).

    Devuelve `(resultados, celdas, avisos)`:

    - `resultados`: uno por fila, de `ejecutor.pasada`.
    - `celdas`: `[(A1, valor)]` — lo que se escribiría o se escribió.
    - `avisos`: lo que no se pudo traducir a celdas, con su motivo.

    ⛔ En seco calcula las celdas **igual**, y no las escribe. Ésa es toda la gracia: se puede leer
    exactamente qué tocaría antes de soltarlo sobre la hoja de un equipo real.
    """
    registros, duplicadas = H.a_registros(valores)
    cabecera = (valores or [[]])[0]

    avisos = []
    for nombre in sorted(duplicadas):
        avisos.append(u"la columna %r sale %d veces en la cabecera: no se escribirá en ella"
                      % (nombre, len(duplicadas[nombre])))

    resultados = E.pasada(registros, servicios, aplicar=aplicar)

    celdas = []
    for r, reg in zip(resultados, registros):
        cambios = cambios_de(r, reg, ahora=ahora)
        if not cambios:
            continue
        unas, motivos = H.celdas_de_cambios(cabecera, r.n, cambios)
        if motivos:
            for m in motivos:
                avisos.append(u"fila %d (%s): %s" % (r.n, r.request_id, m))
            continue
        celdas.extend(unas)

    if aplicar and celdas:
        escribir = getattr(servicios, "escribir", None)
        if not callable(escribir):
            avisos.append(u"`servicios.escribir` no existe: el trabajo se hizo y la hoja NO se "
                          u"ha actualizado, así que la próxima pasada lo repetirá")
        else:
            try:
                escribir(celdas)
            except Exception as e:
                avisos.append(u"al escribir en la hoja: %s: %s" % (type(e).__name__, e))

    return resultados, celdas, avisos


def informe(resultados, celdas, avisos, aplicar=False):
    """El texto que se enseña. Se refuta igual que una función, así que va aquí y no en un `print`.

    ⚠️ Dice **en seco** cuando lo está. Un informe que se lee igual haya escrito o no es la forma
    de que alguien crea que ya está hecho.
    """
    h, s, q, e = E.resumen(resultados)
    lineas = []
    lineas.append(u"PASADA APLICADA" if aplicar else u"PASADA EN SECO (no se ha escrito nada)")
    lineas.append(u"%d expedientes: %d hechos · %d por hacer · %d quietos · %d con error"
                  % (len(resultados), h, s, q, e))
    lineas.append(u"%d celdas %s" % (len(celdas), u"escritas" if aplicar else u"se escribirían"))

    for r in resultados:
        if r.error:
            lineas.append(u"  ERROR  fila %d %s — %s" % (r.n, r.request_id, r.error))
    for r in resultados:
        if r.hecho or r.seco:
            lineas.append(u"  %-6s fila %d %s — %s"
                          % (u"HECHO" if r.hecho else u"HARÍA", r.n, r.request_id, r.accion))
    for a in avisos:
        lineas.append(u"  AVISO  %s" % a)
    return u"\n".join(lineas)


if __name__ == "__main__":  # pragma: no cover
    print("La pasada entera. Para probarla: python scripts/test_pasada.py")
