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
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding="utf-8")
    except Exception:  # pragma: no cover
        pass

import cierre as C
import evidencias as EV
import sustitucion as SU


# Las acciones que el pipeline sabe hacer, en el orden en que ocurren.
ANALIZAR = "analizar"
PDF = "pdf"
ESPERAR = "esperar_decision"
PUBLICAR = "publicar_notion"
REGISTRAR = "registrar_libro"
CERRAR = "cerrar"
REENVIO = "esperar_reenvio"
NADA = "nada"
REVISAR = "revisar_a_mano"
# ⛔ «El trabajo ya está hecho en el mundo, sólo falta marcarlo». No llama a nadie.
ANOTAR = "anotar_lo_hecho"

ACCIONES = (ANALIZAR, PDF, ESPERAR, PUBLICAR, REGISTRAR, CERRAR, REENVIO, NADA, REVISAR,
            ANOTAR)

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
# ✅ Y el 29/09 se vació: `publicar` archiva el fichero y lo RELEE en la carpeta, comparte con
#    el dominio y lo relee, y escribe el resumen ejecutivo como fichero aparte. La última,
#    `drive_folder_created`, no era una tarea: su propio código la define como «la publicación
#    entera está completa», así que se pone al final, cuando lo demás ya salió bien.
# ⚠️ La lista se queda (vacía) a propósito: es la puerta por la que una bandera nueva se
#    declara «nadie la hace todavía» en vez de darse por hecha en silencio.
SIN_IMPLEMENTAR = ()


def _falta_el_pdf(fila):
    """¿Hay que generar el PDF de este expediente? Nunca lanza.

    ⚠️ Mira el **nombre del original**, no una bandera: no hay ninguna que diga «PDF generado»,
    y la prueba de que está es `drive_primary_file_id`, que es lo que `publicar` sube.
    """
    fila = fila if isinstance(fila, dict) else {}
    if str(fila.get("drive_primary_file_id") or "").strip():
        return False
    nombre = str(fila.get("source_filename") or "").strip().lower()
    return nombre.endswith(".docx")


def cadena_de(filas):
    """Las reentregas que ya llegaron, `{clave: quién}`. **La Única puerta.**

    ⛔ Existía calculada en `reparto` y **NADIE MÁS LA PASABA**: `ejecutor.ejecutar_una` llamaba
    a `siguiente(fila)` a secas, así que `quien_sustituye(fila, None)` daba **siempre** `None` y
    la rama «la reentrega YA llegó» era **inalcanzable en producción**. El arreglo estaba
    escrito, con su banco en verde, y **muerto en el cable de en medio** — sin dar un solo
    síntoma, porque REENVIO es una respuesta perfectamente razonable y falsa.
    ⚠️ Por eso vive aquí y no en cada llamante: dos sitios calculando esto acaban en dos
    criterios, y el segundo nace ciego.
    """
    return SU.sustituidas(filas)


def siguiente(fila, cadena=None):
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
        # ⛔⛔ …salvo que la reentrega YA haya llegado. Medido el 29/09: de las **cuatro**
        #    filas esperando reenvío, **TRES ya lo habían recibido**, y el pipeline las dejaba
        #    esperando para siempre — que es exactamente el estado en que nadie las vuelve a
        #    mirar. Cerrarlas aquí sería decidir por una persona; se manda a mirar **diciendo
        #    quién** la reentregó, que es lo único accionable.
        # ⛔ Por la puerta de `sustitucion`, no por una copia: el criterio estuvo
        #    escrito aquí también, y la copia salió CIEGA a la mutación que le quitaba
        #    la exclusión de sí misma — dos copias que hoy coinciden por casualidad.
        quien = SU.quien_sustituye(fila, cadena)
        if quien:
            return REVISAR, (u"pidió cambios y la reentrega YA llegó (%s): sigue abierta "
                             u"esperando algo que ya pasó" % quien)
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

    # ⛔⛔ EL PDF, ANTES DE PUBLICAR. `servicios.publicar` sube `drive_primary_file_id` —el
    #    PDF— y si no lo hay **cae al DOCX original**: Notion lo acepta, crea un bloque de
    #    fichero **que no se puede leer en la página**, y quien abra el documento ve un adjunto
    #    para descargar. Eso es justo lo que la página existe para evitar.
    # ⚠️ Aquel respaldo tenía su motivo escrito — *«quedarse sin documento esperando un fichero
    #    que NADIE VA A GENERAR es peor que un adjunto sin previsualización»* — y ese motivo
    #    **caducó** el 30/09: desde que existe `pdf.docx_a_pdf`, sí hay quien lo genere. El
    #    respaldo se queda por si LibreOffice falla, pero deja de ser la vía normal.
    # ⚠️ Va DESPUÉS de `ya_hecho` y de mirar `faltan`: si la publicación está entera no hay
    #    nada que generar, y pedirlo dejaría al expediente dando vueltas en un paso inútil.
    # ⚠️ Y **sin nombre de fichero no se adivina**: se publica como siempre. Fallar hacia
    #    «generar» dejaría a LibreOffice intentando convertir cualquier cosa.
    if faltan and _falta_el_pdf(fila):
        return PDF, u"aprobada, el original es un DOCX y no hay PDF que publicar"

    if faltan == ["base_database_registered"]:
        return REGISTRAR, u"publicada y sin registrar en el Libro de Datos"
    # ⛔⛔ LA PÁGINA YA CREADA MANDA. `publicar` **crea la página**, así que volver a llamarlo
    #    con la página hecha deja una SEGUNDA página del mismo documento — y otra a la pasada
    #    siguiente, y otra. Da igual qué bandera falte: si hay página y la publicación está a
    #    medias, se para y lo mira una persona.
    #    ⚠️ Va DESPUÉS de registrar el Libro a propósito: ese camino **no** crea página,
    #       así que pararlo dejaría a mano un trabajo que el pipeline sabe hacer solo.
    #    ⚠️ Antes esto sólo miraba las de `SIN_IMPLEMENTAR`, y al vaciarse esa lista el agujero
    #    se abría solo, sin tocar este `if`: el guardia pedía por una lista que iba a quedarse
    #    vacía, en vez de por la condición que hace daño.
    if faltan and C.es_si(fila.get("notion_page_created")):
        return REVISAR, (u"la página ya está creada y la publicación está a medias; falta: %s"
                         % u", ".join(faltan))

    if faltan:
        return PUBLICAR, u"aprobada y sin publicar del todo, falta: %s" % u", ".join(faltan)

    # ⛔⛔ Y quien decide si se puede cerrar es `cierre.puede_cerrar`, NO este módulo. Aquí
    #    había una copia de su criterio —«si no falta ninguna bandera, cerrar»— que coincidía
    #    con él **por casualidad**: el día que `puede_cerrar` ganó una razón más para negarse
    #    (el campo «Revisor/es» del documento, que ninguna bandera ve), esta línea siguió
    #    diciendo CERRAR. Una regla cumplida en dos de sus tres caminos no es una regla.
    vale, motivos = C.puede_cerrar(fila)
    if not vale:
        return REVISAR, (u"publicada entera pero no se puede cerrar: %s" % u"; ".join(motivos))
    return CERRAR, u"aprobada y publicada entera"


def reparto(filas):
    """Qué toca hacer con cada fila, agrupado por acción: `{acción: [(fila, request_id, por_qué)]}`.

    ⚠️ Devuelve **todas** las acciones como claves, incluso las vacías. Un informe donde «publicar»
    desaparece cuando no hay nada que publicar se lee como que la fase no existe, y es justo el
    error que se quiere evitar: la diferencia entre *cero* y *no lo sé* tiene que verse.
    """
    fuera = dict((a, []) for a in ACCIONES)
    # ⚠️ La cadena se calcula AQUÍ, una vez. Pedírsela al que llama es pedirle que se acuerde,
    #    y el que no se acuerde tendrá el fallo de vuelta: filas esperando para siempre.
    cadena = cadena_de(filas)
    for i, f in enumerate(filas):
        n = i + 2
        rid = u"(sin request_id)"
        if isinstance(f, dict):
            rid = str(f.get("request_id") or "").strip() or rid
        accion, porque = siguiente(f, cadena)
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
