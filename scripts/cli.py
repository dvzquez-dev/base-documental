#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""La puerta por la que se llama al pipeline. Seca salvo que se pida lo contrario.

Por qué esto es una pieza
-------------------------
El resto ya decide y ejecuta; esto es lo que hace que **corra solo**. Y en eso hay una decisión
que no es de estilo:

⛔ **Una tarea programada que escribe en producción sin que nadie mire es lo que NO se debe
hacer.** `SOLICITUDES` no tiene deshacer. Por eso `--aplicar` es **obligatorio** para escribir y
la acción programada **no lo pasa**: las pasadas automáticas salen **secas** y dejan su informe,
y aplicar es una decisión de una persona, con `workflow_dispatch`.

⚠️ Y `--aplicar` tampoco basta por sí solo cuando el trabajo es grande: `--limite` existe para que
la primera pasada de verdad toque **tres expedientes**, se miren, y después se suelte entera. Sin
tope, un error de criterio se multiplica por todo lo que haya en la cola.

Cómo se prueba
--------------
`python scripts/test_cli.py` — sin red ni credenciales.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding="utf-8")
    except Exception:  # pragma: no cover
        pass

import cierre as C
import ejecutor as E
import hoja as H
import libro_datos as LD
import pasada as PA

USO = u"""uso: python scripts/cli.py [--aplicar] [--limite N] [--revisar]

  (sin nada)   pasada SECA: dice qué haría y qué celdas escribiría. No toca nada.
  --aplicar    ejecuta de verdad y escribe en la hoja. No hay deshacer.
  --limite N   no toca más de N expedientes en esta pasada.
  --revisar    no ejecuta el pipeline: sólo repasa los datos y lista lo que no cuadra."""


def parsear(argv):
    """`(opciones, motivos)`. Con motivos, `opciones` es `None` y no se corre nada.

    ⛔ Un argumento que no se entiende **para la pasada**, no se ignora. Ignorarlo es como un
    `--aplciar` mal escrito acaba siendo una pasada seca que alguien da por aplicada, o al revés.
    """
    motivos = []
    op = {"aplicar": False, "limite": None, "revisar": False}
    i = 0
    args = list(argv or [])
    while i < len(args):
        a = args[i]
        if a == "--aplicar":
            op["aplicar"] = True
        elif a == "--revisar":
            op["revisar"] = True
        elif a == "--limite":
            if i + 1 >= len(args):
                motivos.append(u"`--limite` se ha quedado sin número")
            else:
                i += 1
                try:
                    n = int(args[i])
                except (TypeError, ValueError):
                    motivos.append(u"`--limite %s` no es un número" % args[i])
                else:
                    if n < 1:
                        motivos.append(u"`--limite %d` no toca ningún expediente: si la idea era "
                                       u"no tocar nada, eso ya es la pasada seca" % n)
                    else:
                        op["limite"] = n
        elif a in ("-h", "--help", "--ayuda"):
            motivos.append(USO)
        else:
            motivos.append(u"no entiendo %r. Ignorarlo es como un `--aplicar` mal escrito acaba "
                           u"en una pasada seca que alguien da por aplicada" % a)
        i += 1

    if op["revisar"] and op["aplicar"]:
        motivos.append(u"`--revisar` sólo mira; con `--aplicar` no significa nada. Elige uno")

    return (None, motivos) if motivos else (op, [])


def revisar_datos(valores_solicitudes, filas_libro):
    """El repaso de los datos: lo que no cuadra, sin tocar nada. `(lineas, cuantos)`."""
    registros, duplicadas = H.a_registros(valores_solicitudes)
    lineas = []

    for nombre in sorted(duplicadas):
        lineas.append(u"CABECERA  la columna %r sale %d veces: no se puede escribir en ella"
                      % (nombre, len(duplicadas[nombre])))

    for n, rid, que in C.revisar(registros):
        lineas.append(u"CIERRE    fila %d %s — %s" % (n, rid, que))

    for n, ref, que in LD.revisar(filas_libro or []):
        lineas.append(u"LIBRO     fila %d %s — %s" % (n, ref, que))

    return lineas, len(lineas)


def correr(argv, servicios, ahora=None):
    """`(texto, codigo)`. `codigo` distinto de 0 cuando algo no cuadra o falló.

    ⚠️ El código de salida importa: es lo único que mira una tarea programada. Una pasada con
    errores que saliera en 0 se vería **verde** en el historial de acciones, para siempre.
    """
    op, motivos = parsear(argv)
    if motivos:
        return u"\n".join(motivos), 2

    leer = getattr(servicios, "leer", None)
    if not callable(leer):
        return u"`servicios.leer` no existe: no hay de dónde sacar los expedientes", 2

    try:
        valores = leer()
    except Exception as e:
        return u"al leer la hoja: %s: %s" % (type(e).__name__, e), 2

    if op["revisar"]:
        filas_libro = []
        leer_libro = getattr(servicios, "leer_libro", None)
        if callable(leer_libro):
            try:
                filas_libro = leer_libro()
            except Exception as e:
                filas_libro = []
                motivos.append(u"al leer el Libro: %s: %s" % (type(e).__name__, e))
        lineas, cuantos = revisar_datos(valores, filas_libro)
        cab = (u"REPASO: %d cosas que no cuadran" % cuantos) if cuantos else u"REPASO: todo cuadra"
        return u"\n".join([cab] + lineas), (1 if cuantos else 0)

    # ⚠️ El tope se aplica a las FILAS DE DATOS, no a la hoja: cortar la hoja se llevaría la
    #    cabecera y entonces no habría ni columnas con las que trabajar.
    if op["limite"] is not None and valores:
        valores = [valores[0]] + list(valores[1:])[:op["limite"]]

    resultados, celdas, avisos = PA.correr(valores, servicios,
                                           aplicar=op["aplicar"], ahora=ahora)
    texto = PA.informe(resultados, celdas, avisos, aplicar=op["aplicar"])
    _h, _s, _q, errores = E.resumen(resultados)
    return texto, (1 if (errores or avisos) else 0)


if __name__ == "__main__":  # pragma: no cover
    print(USO)
