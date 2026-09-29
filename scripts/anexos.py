#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Los anexos de un expediente: qué hay, qué falta por copiar y si cuadra. Sin tocar la red.

Por qué existe
--------------
📏 **Medido en `SOLICITUDES` el 29/09/2026**: un expediente puede traer anexos, y el pipeline
nuevo **no los miraba en absoluto**. La fila 18 (`SOL-DOC-20260720-113951-79E115DB`, la *Memoria
Técnica Aviónica EuRoC*) trae **siete**. Publicar sin ellos **no da ningún error**: el documento
queda archivado, la página de Notion creada y el expediente cerrado — sin los siete ficheros que
lo acompañan, y sin que nadie se entere hasta que alguien los busque.

Las cuatro columnas
-------------------
- `annex_drive_file_ids_json` — los ids **de origen**, tal como llegaron del formulario.
- `annex_source_urls` — sus URL, informativas.
- `annex_copied_count` — cuántos se copiaron.
- `annex_final_file_ids_json` — los ids **ya en la carpeta del expediente**.

⛔ **Se llaman `_json` y no siempre lo son**: la fila que tiene anexos los trae **separados por
comas**, y las que no tienen traen `[]`. Por eso se leen con `hoja.lista_de_celda`, que es la
puerta única de «JSON o comas» — la misma que arregló `tags_json`.

⛔ **Copiar, no mover.** El fichero de origen es el adjunto del formulario, que es de quien lo
subió; moverlo se lo quita de su Drive. El documento principal sí se mueve (es el expediente);
un anexo se **copia**, y por eso aquí hay dos listas de ids y no una.

Cómo se prueba
--------------
`python scripts/test_anexos.py` — sin red ni credenciales.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding="utf-8")
    except Exception:  # pragma: no cover
        pass

import hoja as H

COL_ORIGEN = "annex_drive_file_ids_json"
COL_FINALES = "annex_final_file_ids_json"
COL_CUANTOS = "annex_copied_count"


def _ids(valor, nombre):
    """Los ids de una celda, recortados y sin vacíos ni repetidos. `(ids, motivos)`."""
    brutos, motivos = H.lista_de_celda(valor, u"`%s`" % nombre)
    fuera, vistos = [], set()
    for x in brutos:
        t = str(x if x is not None else "").strip()
        if not t or t in vistos:
            continue
        vistos.add(t)
        fuera.append(t)
    return fuera, motivos


def origen(fila):
    """Los ids de los anexos tal como llegaron. `(ids, motivos)`."""
    return _ids((fila or {}).get(COL_ORIGEN), COL_ORIGEN)


def finales(fila):
    """Los ids de los anexos ya copiados a la carpeta del expediente. `(ids, motivos)`."""
    return _ids((fila or {}).get(COL_FINALES), COL_FINALES)


def faltan(fila):
    """Cuántos anexos quedan por copiar. **Un número**, nunca `None`.

    ⚠️ Se compara por **cantidad**, no por id: el id de una copia **no es** el del original, así
    que no hay forma de emparejarlos uno a uno mirando la hoja. Lo que sí se puede afirmar es
    que si hay siete de origen y cinco copiados, faltan dos.
    ⛔ Y si hay **más copiados que de origen**, `faltan` es 0 pero `revisar` lo canta: eso es una
    copia de más, que en Drive queda como un fichero duplicado que nadie va a borrar.
    """
    o, _ = origen(fila)
    f, _ = finales(fila)
    return max(0, len(o) - len(f))


def revisar(fila):
    """Lo que no cuadra en los anexos de una fila. Lista de motivos, vacía si está en regla."""
    fila = fila if isinstance(fila, dict) else {}
    o, m_o = origen(fila)
    f, m_f = finales(fila)
    # ⚠️ Sólo cuentan como problema los motivos cuya lectura **no dio nada**. «Venía separado
    #    por comas» es información —la lista se leyó entera— y meterlo aquí pondría en rojo la
    #    única fila real con anexos, que está perfectamente en regla. Enseñar a ignorar este
    #    aviso es peor que no tenerlo: el día que diga «JSON roto» nadie lo leerá.
    motivos = ([m for m in m_o if not o] + [m for m in m_f if not f])

    if len(f) > len(o):
        motivos.append(u"hay %d anexos copiados y sólo %d de origen: sobra alguna copia, y en "
                       u"Drive queda un fichero duplicado que nadie va a borrar" % (len(f), len(o)))

    # ⛔ `annex_copied_count` tiene que decir lo mismo que la lista. Si no, una de las dos miente
    #    y no se sabe cuál: el contador es lo que se mira de un vistazo y la lista es la prueba.
    crudo = str(fila.get(COL_CUANTOS) or "").strip()
    if crudo:
        try:
            cuantos = int(crudo)
        except ValueError:
            # ⚠️ Aquí NO se canta: de eso ya avisa `hoja.desplazadas`, que mira **las diez**
            #    columnas numéricas y no sólo ésta. Medido sobre las 17 filas reales, tenerlo en
            #    los dos sitios daba **8 líneas para 4 problemas** — y un aviso repetido enseña a
            #    leer el repaso por encima, que es como se pierden los que sí son únicos.
            pass
        else:
            if cuantos != len(f):
                motivos.append(u"`%s` dice %d y hay %d ids copiados: uno de los dos miente"
                               % (COL_CUANTOS, cuantos, len(f)))
    elif f:
        motivos.append(u"hay %d anexos copiados y `%s` está vacío" % (len(f), COL_CUANTOS))

    return motivos


URL_FICHERO = "https://drive.google.com/file/d/%s/view"


def bloques(ids_copiados):
    """Los bloques con que los anexos se enlazan en la página de Notion. Lista, puede ir vacía.

    ⛔ Copiarlos a Drive **no es enlazarlos**: un anexo archivado que la página no menciona **no
    existe** para quien lee el documento en Notion, que es donde el equipo lo lee.
    ⚠️ Van como **marcador** y no como fichero adjunto: el fichero ya está en Drive y subirlo
    otra vez a Notion dejaría dos copias — y la de Notion no se actualizaría nunca.
    """
    fuera = []
    for i in (ids_copiados or []):
        t = str(i if i is not None else "").strip()
        if not t:
            continue
        fuera.append({"object": "block", "type": "bookmark",
                      "bookmark": {"url": URL_FICHERO % t}})
    return fuera


def cambios(ids_copiados):
    """Lo que hay que escribir en la hoja tras copiar. `{}` si no se copió nada.

    ⚠️ Se escribe **JSON**, que es lo que la columna promete, aunque se sepa leer la otra forma.
    Escribir en el formato bueno es lo único que hace que la excepción se vaya muriendo sola.
    """
    ids = [str(x).strip() for x in (ids_copiados or []) if str(x or "").strip()]
    if not ids:
        return {}
    return {COL_FINALES: u"[%s]" % u", ".join(u'"%s"' % i for i in ids),
            COL_CUANTOS: len(ids)}


if __name__ == "__main__":  # pragma: no cover
    print("Los anexos de un expediente. Para probarlo: python scripts/test_anexos.py")
