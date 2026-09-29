#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Paso 7 del pipeline documental: cuándo un expediente puede darse por cerrado.

Qué mide esto
-------------
`SOLICITUDES` lleva **19 banderas** por expediente, de `received` a `closed`. El paso 7 es poner
`closed`, y la pregunta que nadie tenía escrita es **qué tiene que ser cierto antes**.

⛔ **Y no es teórica.** Medido el 29/09/2026 sobre las primeras filas reales: hay una con
`closed = TRUE` y **todas las demás banderas en FALSE** — recibida, nunca analizada, nunca
aprobada, nunca publicada, y cerrada igual. Hoy `closed` no implica nada, así que contar
expedientes cerrados no dice cuánto trabajo se hizo.

⚠️ **Tres valores, no dos.** Las celdas traen `"TRUE"`, `"FALSE"` **y vacío**. El vacío no es
`FALSE`: significa que el pipeline **nunca pasó por ahí**, y es un dato distinto que conviene no
tirar — una fila con `reported` vacío no es lo mismo que una con `reported` puesto a `FALSE`.
Aplastarlos hace que un expediente que se quedó a medias parezca uno que se decidió que no.

Cómo se prueba
--------------
`python scripts/test_cierre.py` — sin red ni credenciales.
"""
import sys

for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding="utf-8")
    except Exception:  # pragma: no cover
        pass


SI, NO, SIN_TOCAR = "si", "no", "sin_tocar"

# 📏 Las 19 banderas, en el orden EXACTO de la cabecera de `SOLICITUDES` (columnas 31–49),
#    leídas el 29/09/2026.
BANDERAS = ("received", "analyzed", "id_reserved", "approval_email_sent", "reported",
            "approved", "rejected", "changes_requested", "notion_page_created",
            "notion_pdf_embedded", "notion_embedding_verified", "drive_folder_created",
            "drive_primary_file_verified", "drive_summary_created",
            "domain_permission_verified", "base_database_registered",
            "author_confirmation_sent", "thread_confirmation_sent", "closed")

# Lo que tiene que estar hecho para cerrar un expediente APROBADO: se publicó de verdad.
# ⚠️ `approval_email_sent` y `reported` NO están: son del paso 3, que la app sustituyó. Exigirlos
#    dejaría sin cerrar para siempre todo lo que se apruebe desde el móvil.
PUBLICACION = ("notion_page_created", "notion_pdf_embedded", "notion_embedding_verified",
               "drive_folder_created", "drive_primary_file_verified", "drive_summary_created",
               "domain_permission_verified", "base_database_registered")


def estado(valor):
    """`SI`, `NO` o `SIN_TOCAR` para una celda de bandera.

    ⛔ El vacío se devuelve como `SIN_TOCAR` a propósito, en vez de aplastarlo contra `NO`. Es la
    diferencia entre «el pipeline decidió que no» y «el pipeline nunca llegó aquí», y quien mire
    por qué un expediente lleva dos semanas parado necesita justo esa diferencia.
    """
    if valor is True:
        return SI
    if valor is False:
        return NO
    v = str(valor if valor is not None else "").strip().upper()
    if v in ("TRUE", "SI", "SÍ", "1", "YES", "X"):
        return SI
    if v in ("FALSE", "NO", "0"):
        return NO
    return SIN_TOCAR


def es_si(valor):
    """Sólo `True` cuando la bandera está puesta de verdad.

    ⚠️ Nunca se pregunta `!= "FALSE"`: con eso, el vacío contaría como puesta y un expediente que
    el pipeline no tocó pasaría por hecho.
    """
    return estado(valor) == SI


def via(fila):
    """Por dónde va este expediente: `"aprobado"`, `"rechazado"`, `"cambios"` o `None`.

    `None` significa que todavía no hay decisión, no que esté mal.
    """
    if es_si(fila.get("approved")):
        return "aprobado"
    if es_si(fila.get("rejected")):
        return "rechazado"
    if es_si(fila.get("changes_requested")):
        return "cambios"
    return None


# ⛔ La columna que bloquea el cierre y **no es una bandera**: el hueco «Revisor/es: ----» vive
#    DENTRO del documento, no en la hoja, así que ninguna bandera de publicación puede verlo.
#    📏 Medido en `SOLICITUDES` el 29/09/2026 (CV1:CZ19): la columna lleva **marcas de tiempo**
#    en 8 filas y un `TRUE` en una — la 18, que es la única que este pipeline tocaría hoy.
REVISOR_PENDIENTE = "revisor_field_pendiente"


def puede_cerrar(fila):
    """`(True, [])` si el expediente puede cerrarse, o `(False, motivos)`.

    Las tres vías no piden lo mismo, y ahí está el fondo del asunto:

    - **aprobado** → sólo cierra cuando está **publicado de verdad** (las 8 banderas de
      publicación). Cerrar un aprobado sin publicar es perder el documento con acuse de que fue
      bien.
    - **rechazado** → cierra sin publicar nada: no hay nada que publicar.
    - **cambios pedidos** → **no cierra**. Está esperando a que el autor reenvíe, y cerrarlo es
      justo lo que hace que nadie vuelva a mirarlo.
    """
    motivos = []
    v = via(fila)

    if v is None:
        motivos.append(u"sin decisión: no está aprobado, ni rechazado, ni con cambios pedidos")
    elif v == "cambios":
        motivos.append(u"tiene cambios pedidos: está esperando a que el autor reenvíe, y cerrarlo "
                       u"es lo que hace que nadie vuelva a mirarlo")
    elif v == "aprobado":
        if not es_si(fila.get("analyzed")):
            motivos.append(u"aprobado sin analizar: no hay resumen ni avisos de calidad")
        faltan = [b for b in PUBLICACION if not es_si(fila.get(b))]
        if faltan:
            motivos.append(u"aprobado pero sin publicar del todo, falta: %s" % u", ".join(faltan))
        # ⛔⛔ Y el campo «Revisor/es» del propio documento. No es una bandera de publicación: es
        #    un hueco DENTRO del PDF, y por eso ninguna de las ocho lo ve. Cowork lo dice en la
        #    propia hoja — *«Es el unico item que bloquea el cierre del expediente; Cowork NO
        #    cierra hasta que el revisor este relleno»*— y era justo lo que pasaba con la única
        #    fila sobre la que este código habría actuado hoy.
        #    ⚠️ El criterio es **un SÍ**, no «no vacío», y lo decidió quién se pone rojo: esa
        #       columna lleva marcas de tiempo en 8 filas reales y **cuatro ya están cerradas**.
        if es_si(fila.get(REVISOR_PENDIENTE)):
            motivos.append(u"el campo «Revisor/es» del documento sigue sin rellenar "
                           u"(`%s`): publicarlo y cerrarlo deja el hueco dentro del PDF y "
                           u"ya no lo mira nadie" % REVISOR_PENDIENTE)

    return (not motivos), motivos


def revisar(filas):
    """Los cierres que no se sostienen. Lista de `(fila_1based, request_id, qué)`.

    ⛔ Este es el revisor que destapó la fila real con `closed = TRUE` y **todo lo demás en
    FALSE**. Sin él, «cuántos expedientes hay cerrados» es un número que no significa nada.
    """
    avisos = []
    for i, f in enumerate(filas):
        n = i + 2  # +1 por contar desde 1, +1 por la cabecera
        rid = str(f.get("request_id") or "").strip() or u"(sin request_id)"

        cerrado = es_si(f.get("closed"))
        vale, motivos = puede_cerrar(f)

        if cerrado and not vale:
            for m in motivos:
                avisos.append((n, rid, u"cerrado y no debería: %s" % m))
        elif not cerrado and vale:
            avisos.append((n, rid, u"está listo para cerrar y sigue abierto"))

        # ⚠️ Dos decisiones a la vez no es un estado válido: alguien las pisó y no se sabe cuál
        #    manda. Se mira aparte de `puede_cerrar`, que se queda con la primera que encuentra.
        puestas = [d for d in ("approved", "rejected", "changes_requested") if es_si(f.get(d))]
        if len(puestas) > 1:
            avisos.append((n, rid, u"tiene %d decisiones a la vez (%s): no se sabe cuál manda"
                           % (len(puestas), u", ".join(puestas))))

        if es_si(f.get("closed")) and estado(f.get("received")) != SI:
            avisos.append((n, rid, u"cerrado sin estar ni recibido"))

    avisos.sort(key=lambda a: (a[0], a[2]))
    return avisos


if __name__ == "__main__":  # pragma: no cover
    print("Lógica pura del Paso 7. Para probarla: python scripts/test_cierre.py")
