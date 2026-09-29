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

import anexos as AX
import cierre as C
import sustitucion as SU
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
    op = {"aplicar": False, "limite": None, "revisar": False, "ingerir": False}
    i = 0
    args = list(argv or [])
    while i < len(args):
        a = args[i]
        if a == "--aplicar":
            op["aplicar"] = True
        elif a == "--revisar":
            op["revisar"] = True
        elif a == "--ingerir":
            op["ingerir"] = True
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


def ingerir(respuestas, solicitudes_valores, rutas, reservas, hoy=None):
    """Las filas nuevas que hay que añadir a `SOLICITUDES`, y lo que no se ha podido ingerir.

    ⛔⛔ EL PASO 1, QUE NO CORRÍA. `ingesta_forms` era lógica pura y no la llamaba nadie: una
    respuesta enviada a las 23:48 seguía sin ingerir a la mañana siguiente, y el caso peor
    registrado esperó **doce horas**.

    Devuelve `(filas, avisos)`. **Nunca lanza**: una respuesta que no se puede ingerir sale en
    `avisos` y las demás siguen — que el número 3 reviente no puede dejar sin entrar a los 40
    de detrás.
    """
    import ingesta_forms as IF                                           # noqa: PLC0415
    filas, avisos = [], []
    vals = list(respuestas or [])
    if len(vals) < 2:
        return [], []
    cab, cuerpo = vals[0], vals[1:]

    registros = H.a_registros(solicitudes_valores or [[]])[0]
    ya = set(str(r.get("form_row", "")).strip() for r in registros)
    reservas = list(reservas or [])

    for i, fila in enumerate(cuerpo):
        n = i + 2                       # +1 por la cabecera, +1 por contar desde 1
        if str(n) in ya:
            continue
        r = IF.respuesta_de(cab, fila, n)
        rid = r.get("title_short") or u"(sin título)"
        if r.get("motivo_error"):
            avisos.append(u"fila %d %s — %s" % (n, rid, r["motivo_error"]))
            continue
        fecha = IF.fecha_form(r.get("marca_temporal"))
        if not fecha:
            avisos.append(u"fila %d %s — la marca temporal %r no se entiende: sin fecha no se "
                          u"sabe de qué temporada es" % (n, rid, r.get("marca_temporal")))
            continue
        season_label, sufijo = IF.temporada_de(fecha.date() if hasattr(fecha, "date") else fecha)

        # ⛔ La SUSTITUCIÓN manda sobre el número nuevo: una reentrega reusa el de la
        #    referencia que sustituye, o no entra. Darle número nuevo deja dos expedientes del
        #    mismo documento y nadie sabe cuál manda.
        sus = IF.sustitucion_de(r, registros)
        if sus and sus.get("motivo_error"):
            avisos.append(u"fila %d %s — %s" % (n, rid, sus["motivo_error"]))
            continue

        ruta = IF.ruta_de(r.get("unit_label"), r.get("subfolder_label"), rutas or [])
        if ruta is None:
            avisos.append(u"fila %d %s — no hay una sola ruta activa para %r + %r: sin ella el "
                          u"documento se archivaría donde no es, sin dar error"
                          % (n, rid, r.get("unit_label"), r.get("subfolder_label")))
            continue

        if sus:
            num = sus.get("reserved_id")
        else:
            num = IF.siguiente_id(ruta, reservas, sufijo)
        if not num:
            avisos.append(u"fila %d %s — el rango de esa ruta está agotado para la temporada "
                          u"%s: se amplía el rango, no se reutiliza un número" % (n, rid, sufijo))
            continue

        f = IF.fila_solicitud(r, ruta, num, sufijo, season_label, fecha)
        if sus:
            f["replaces_document"] = sus.get("replaces_document", "")
            f["replacement_reference"] = sus.get("replacement_reference", "")
            f["replacement_reason"] = sus.get("replacement_reason", "")
        # ⚠️ El número se apunta en las reservas de esta misma pasada: si no, dos respuestas
        #    seguidas de la misma ruta se llevan **el mismo** número.
        reservas.append({"reserved_id": str(num), "season_suffix": sufijo})
        filas.append(f)

    return filas, avisos


def revisar_datos(valores_solicitudes, filas_libro):
    """El repaso de los datos: lo que no cuadra, sin tocar nada. `(lineas, cuantos)`."""
    registros, duplicadas = H.a_registros(valores_solicitudes)
    lineas = []

    for nombre in sorted(duplicadas):
        lineas.append(u"CABECERA  la columna %r sale %d veces: no se puede escribir en ella"
                      % (nombre, len(duplicadas[nombre])))

    # ⛔ Las filas DESPLAZADAS van primero: si la cola de una fila está corrida, todo lo que
    #    se diga de ella después se ha leído de la columna equivocada.
    # ⛔ Y los ids con basura dentro, que es peor que un hueco: una carpeta con una comilla
    #    delante **parece existir**, así que no se crea ninguna y el fichero se archiva en un id
    #    que Drive no conoce.
    for nf, rid, col, valor in H.ids_raros(registros):
        lineas.append(u"ID        fila %d %s — `%s` vale %r y no tiene forma de id de Drive: "
                      u"parece existir y Drive no lo conoce" % (nf, rid, col, valor))

    for nf, rid, col, valor in H.desplazadas(registros):
        lineas.append(u"COLUMNA   fila %d %s — `%s` debería ser un número y vale %r: la fila "
                      u"parece desplazada respecto a la cabecera" % (nf, rid, col, valor))

    for n, rid, que in C.revisar(registros):
        lineas.append(u"CIERRE    fila %d %s — %s" % (n, rid, que))

    # Los anexos: un expediente puede traerlos y publicarlo sin ellos no da ningún error.
    for i, r in enumerate(registros):
        rid = str(r.get("request_id") or "").strip() or u"(sin request_id)"
        for que in AX.revisar(r):
            lineas.append(u"ANEXOS    fila %d %s — %s" % (i + 2, rid, que))

    # ⛔ Publicado y sin PDF. Casi todos los expedientes llegan en DOCX y **el PDF no lo genera
    #    nadie todavía**; sin este aviso, un expediente con el DOCX colgado —que Notion no
    #    previsualiza— queda igual de «completo» que uno con su PDF. Lo que no se hace se dice.
    for i, r in enumerate(registros):
        if not C.es_si(r.get("notion_page_created")):
            continue
        if str(r.get("drive_primary_file_id") or "").strip():
            continue
        if not str(r.get("drive_docx_file_id") or "").strip():
            continue
        rid = str(r.get("request_id") or "").strip() or u"(sin request_id)"
        lineas.append(u"PDF       fila %d %s — publicado con el DOCX y **sin PDF**: Notion no lo "
                      u"previsualiza, y generarlo no lo hace nadie todavía" % (i + 2, rid))

    # Las cadenas de reentrega: una que no se pueda seguir deja el original esperando para
    # siempre un reenvío que ya llegó.
    for nf, rid, que in SU.revisar(registros):
        lineas.append(u"CADENA    fila %d %s — %s" % (nf, rid, que))

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

    # ⛔⛔ EL PASO 1. Va ANTES del reparto a propósito: lo que se acaba de ingerir entra en la
    #    misma pasada, y si no, una respuesta nueva espera a la vuelta siguiente — que es
    #    exactamente lo que hacía que una enviada a las 23:48 siguiera ahí por la mañana.
    #    ⚠️ Y es **seco** salvo `--aplicar`, como todo lo demás: añadir filas a `SOLICITUDES`
    #       no tiene deshacer.
    if op["ingerir"]:
        _lr = getattr(servicios, "leer_respuestas", None)
        _lru = getattr(servicios, "leer_rutas", None)
        _lre = getattr(servicios, "leer_reservas", None)
        if not (callable(_lr) and callable(_lru)):
            return u"`servicios.leer_respuestas` o `leer_rutas` no existen: no hay ingesta", 2
        try:
            _resp = _lr()
            _rut = _lru()
            _res = _lre() if callable(_lre) else []
        except Exception as e:
            return u"al leer para la ingesta: %s: %s" % (type(e).__name__, e), 2
        _nuevas, _avisos = ingerir(_resp, valores, _rut, _res)
        _lin = [u"INGESTA: %d respuesta(s) nueva(s)" % len(_nuevas)]
        _lin += [u"  + %s  %s" % (f.get("reference"), f.get("title_short")) for f in _nuevas]
        _lin += [u"  !! %s" % x for x in _avisos]
        if not op["aplicar"]:
            _lin.append(u"(seco: nada escrito. Con --aplicar se añaden a SOLICITUDES)")
            return u"\n".join(_lin), (1 if _avisos else 0)
        _add = getattr(servicios, "anadir_solicitudes", None)
        if not callable(_add):
            return u"`servicios.anadir_solicitudes` no existe: no se escribe nada", 2
        try:
            _n = _add(_nuevas)
        except Exception as e:
            return u"al añadir a SOLICITUDES: %s: %s" % (type(e).__name__, e), 2
        _lin.append(u"%d fila(s) añadida(s) a SOLICITUDES" % _n)
        return u"\n".join(_lin), (1 if _avisos else 0)

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
    # ⛔ AQUÍ SE CONSTRUYEN LAS MANOS, Y SÓLO AQUÍ. Todo lo de arriba recibe `servicios` por
    #    parámetro para poder probarse con dobles; el único sitio que instancia las de verdad es
    #    este `__main__`, o sea cuando una persona (o la acción) lanza el script a propósito.
    #    Importar `servicios` arriba haría que **cargar el módulo** arrastrara las librerías de
    #    Google, y el banco dejaría de correr sin credenciales.
    import servicios as _SRV                                            # noqa: PLC0415
    from datetime import datetime, timezone                             # noqa: PLC0415

    _ahora = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    _texto, _codigo = correr(sys.argv[1:], _SRV.Servicios(), ahora=_ahora)
    print(_SRV.sin_secretos(_texto))
    sys.exit(_codigo)
