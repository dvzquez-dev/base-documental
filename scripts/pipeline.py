#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Lo que ata los pasos: qué toca hacer con un expediente, dado el estado en que está.

Por qué esto es la pieza que faltaba
------------------------------------
Los pasos ya son código — `ingesta_forms` (1), `publicar_notion` (5), `libro_datos` (6),
`cierre` (7) —, pero **nadie decidía en qué orden**. Eso es justo lo que hacía el asistente: mirar
una fila y decir «a ésta le toca publicar». Y es justo lo que un modelo hace de forma distinta
cada vez: en el `EVENTOS_LOG` real hay **~78 nombres distintos de `workflow`** para lo que
debería ser una operación repetida.

Un procedimiento que se improvisa no es un procedimiento. Aquí está escrito.

⛔ **Esto no toca nada.** `siguiente(fila)` **dice** qué toca; ejecutarlo es de quien tenga las
credenciales. Separarlo es lo que permite probar el orden entero sin red, sin cuenta de servicio y
sin escribir en la hoja de un equipo real.

Cómo se prueba
--------------
`python scripts/test_pipeline.py` — sin red ni credenciales.
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
import evidencias as EV


# Las acciones que el pipeline sabe hacer, en el orden en que ocurren.
ANALIZAR = "analizar"
ESPERAR = "esperar_decision"
PUBLICAR = "publicar_notion"
REGISTRAR = "registrar_libro"
CERRAR = "cerrar"
REENVIO = "esperar_reenvio"
NADA = "nada"
REVISAR = "revisar_a_mano"
# ⛔ «El trabajo ya está hecho en el mundo, sólo falta marcarlo». No llama a nadie.
ANOTAR = "anotar_lo_hecho"

ACCIONES = (ANALIZAR, ESPERAR, PUBLICAR, REGISTRAR, CERRAR, REENVIO, NADA, REVISAR, ANOTAR)

# ⚠️ El único paso que sigue necesitando un modelo. Los demás son deterministas, y por eso el
#    reparto es «la IA escribe el código, el código ejecuta»: llamar a un modelo para reservar un
#    número o copiar una fila es caro y, peor, irrepetible.
CON_MODELO = (ANALIZAR,)

# ⛔ Las banderas de publicación que **ningún servicio implementa todavía**: subir el fichero a
#    Notion y embeberlo, y las cuatro de Drive. Están escritas aquí y no supuestas, porque lo
#    contrario — dar por hecho lo que no se hace — es lo que entierra un expediente: con todas
#    las banderas puestas, `cierre` lo da por publicado y lo cierra.
# ✅ `notion_pdf_embedded` SALIÓ de aquí el 699.ª: el adaptador baja el fichero de Drive, lo
#    sube a Notion y lo engancha a la página antes de crearla. Lo hace de verdad, así que
#    dejarlo en esta lista habría parado expedientes que ya se pueden terminar.
# ✅ Y `notion_embedding_verified` salió también: `publicar` **relee la página** y comprueba
#    que el bloque del fichero está dentro. Subir no era verificar — por eso hacía falta la
#    relectura, no una promesa.
# ⚠️ `drive_primary_file_verified` SIGUE AQUÍ aunque el fichero ya se archive: mover no es
#    verificar, igual que subir no era embeber. Verificarlo es releer la carpeta y comprobar
#    que está dentro, y eso aún no se hace.
SIN_IMPLEMENTAR = ("drive_folder_created",
                   "drive_primary_file_verified", "drive_summary_created",
                   "domain_permission_verified")


def siguiente(fila):
    """`(acción, por_qué)` para un expediente. Nunca lanza; una fila rara devuelve `REVISAR`.

    El orden sale de las banderas medidas en `SOLICITUDES`, no de lo que parezca razonable:

    1. sin `received` → algo escribió la fila sin recibirla: **a mano**.
    2. sin `analyzed` → **analizar** (el paso del modelo).
    3. sin decisión → **esperar**: decide una persona desde la app.
    4. `changes_requested` → **esperar el reenvío** del autor.
    5. `rejected` → **cerrar** (no hay nada que publicar).
    6. `approved` y sin publicar → **publicar**.
    7. publicado y sin registrar → **registrar en el Libro**.
    8. todo hecho y sin `closed` → **cerrar**.
    """
    if not isinstance(fila, dict):
        return REVISAR, u"la fila no es un registro: %r" % type(fila).__name__

    if C.es_si(fila.get("closed")):
        vale, motivos = C.puede_cerrar(fila)
        if not vale:
            # ⛔ Cerrado sin derecho. No se «reabre» por nuestra cuenta: se manda a mirar. Un
            #    pipeline que deshace decisiones ajenas calladamente es peor que uno que se para.
            return REVISAR, u"está cerrado y no debería: %s" % motivos[0]
        return NADA, u"cerrado y en regla"

    if not C.es_si(fila.get("received")):
        return REVISAR, u"la fila existe y no consta recibida: alguien la escribió a mano"

    decisiones = [d for d in ("approved", "rejected", "changes_requested") if C.es_si(fila.get(d))]
    if len(decisiones) > 1:
        return REVISAR, u"tiene %d decisiones a la vez (%s)" % (len(decisiones),
                                                               u", ".join(decisiones))

    if not C.es_si(fila.get("analyzed")):
        return ANALIZAR, u"recibida y sin analizar"

    if not decisiones:
        return ESPERAR, u"analizada y esperando a que alguien decida en la app"

    if decisiones == ["changes_requested"]:
        return REENVIO, u"cambios pedidos: espera a que el autor reenvíe"

    if decisiones == ["rejected"]:
        return CERRAR, u"rechazada: no hay nada que publicar"

    # Aprobada.
    # ⛔ ANTES de publicar o registrar: si una bandera está sin poner pero su identificador ya
    #    tiene valor, el trabajo SE HIZO y lo que falló fue anotarlo. Rehacerlo crearía una
    #    SEGUNDA página de Notion o una segunda carpeta, sin que nada las marque como duplicadas.
    #    El hueco es real: acaba de medirse que una escritura en Sheets puede no hacer nada y
    #    decir que sí.
    anotables = EV.ya_hecho(fila)
    if anotables:
        return ANOTAR, u"ya está hecho y sin marcar: %s" % u", ".join(anotables)

    faltan = [b for b in C.PUBLICACION if not C.es_si(fila.get(b))]

    # ⛔ Lo que HOY no hace nadie: subir el fichero, embeberlo y todo el lado de Drive. Si la
    #    página ya está creada y lo único que falta es eso, **no se vuelve a publicar** — eso
    #    crearía una segunda página cada pasada — y **tampoco se da por hecho**. Se para y se
    #    manda a mirar, que es lo único honesto mientras el adaptador no lo implemente.
    _sin_manos = [b for b in faltan if b in SIN_IMPLEMENTAR]
    if C.es_si(fila.get("notion_page_created")) and _sin_manos:
        return REVISAR, (u"la página ya está creada y falta lo que aún no hace nadie: %s"
                         % u", ".join(_sin_manos))

    if faltan == ["base_database_registered"]:
        return REGISTRAR, u"publicada y sin registrar en el Libro de Datos"
    if faltan:
        return PUBLICAR, u"aprobada y sin publicar del todo, falta: %s" % u", ".join(faltan)

    return CERRAR, u"aprobada y publicada entera"


def reparto(filas):
    """Qué toca hacer con cada fila, agrupado por acción: `{acción: [(fila, request_id, por_qué)]}`.

    ⚠️ Devuelve **todas** las acciones como claves, incluso las vacías. Un informe donde «publicar»
    desaparece cuando no hay nada que publicar se lee como que la fase no existe, y es justo el
    error que se quiere evitar: la diferencia entre *cero* y *no lo sé* tiene que verse.
    """
    fuera = dict((a, []) for a in ACCIONES)
    for i, f in enumerate(filas):
        n = i + 2
        rid = u"(sin request_id)"
        if isinstance(f, dict):
            rid = str(f.get("request_id") or "").strip() or rid
        accion, porque = siguiente(f)
        fuera[accion].append((n, rid, porque))
    return fuera


def cuantas_con_modelo(filas):
    """Cuántas de estas filas necesitan una llamada a un modelo. El resto es determinista.

    Sirve para lo que Daniel pregunta siempre: cuánto de esto cuesta inferencia. Hoy es
    exactamente una acción de ocho.
    """
    r = reparto(filas)
    return sum(len(r[a]) for a in CON_MODELO)


if __name__ == "__main__":  # pragma: no cover
    print("Lógica pura del orden del pipeline. Para probarla: python scripts/test_pipeline.py")
