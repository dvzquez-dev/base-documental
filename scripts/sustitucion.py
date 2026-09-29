#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""La cadena de reentregas: quién sustituye a quién. Sin tocar la red.

Por qué existe
--------------
📏 **Medido en `SOLICITUDES` el 29/09/2026.** Una sustitución no borra nada: es un envío **nuevo**
enlazado al viejo. El pipeline no seguía esa cadena, y eso le costaba dos cosas a la vez:

1. **Tres de las cuatro filas que esperan un reenvío ya lo han recibido.** Las filas 7, 8 y 13
   están en `changes_requested`, y las filas 8, 9 y 16 son sus reentregas. Sin la cadena, el
   pipeline las deja en `esperar_reenvio` **para siempre**, esperando algo que ya pasó.
2. Las filas 14 y 15 apuntan a un documento **ya publicado y cerrado**, y sin la cadena parecen
   dos expedientes más en vez de dos punteros al mismo.

⛔ La columna `replaces_document` trae **cuatro codificaciones distintas** del mismo dato, y todas
son reales: `"No"`, `"Sí"`, `"TRUE"` y un `request_id` entero. Leerla como un booleano pierde los
punteros; leerla como un id pierde los `Sí`/`TRUE`. Aquí se leen las cuatro.

⚠️ Y cuando no hay `request_id` se traza por **`replacement_reference`** (`Informe_S-1009_26`),
que es lo que salva el caso de la fila 16 — la que dice `TRUE` a secas.

Cómo se prueba
--------------
`python scripts/test_sustitucion.py` — sin red ni credenciales.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding="utf-8")
    except Exception:  # pragma: no cover
        pass

COL_REEMPLAZA = "replaces_document"
COL_REFERENCIA = "replacement_reference"
COL_MOTIVO = "replacement_reason"

# ⛔ Los valores medidos que significan «no sustituye a nadie». Cualquier otra cosa no vacía sí
#    declara una sustitución — un `request_id`, un `Sí`, un `TRUE`.
_NEGATIVOS = ("no", "false", "n", "0", "-")
_AFIRMATIVOS = ("si", "sí", "true", "s", "1", "yes")


def declara(fila):
    """¿Esta fila dice ser la reentrega de otra? `True`/`False`, nunca `None`."""
    v = str((fila or {}).get(COL_REEMPLAZA) or "").strip()
    if not v:
        return False
    return v.lower() not in _NEGATIVOS


def apunta_a(fila):
    """A quién dice sustituir: `(request_id, referencia)`. Cualquiera de los dos puede ser `None`.

    ⚠️ El `request_id` sólo existe cuando la columna lo trae; con un `Sí` o un `TRUE` **no hay
    id**, y entonces lo único que ata la reentrega al original es la referencia. Devolver los dos
    por separado es lo que deja al que llama decidir con cuál puede trabajar, en vez de que este
    módulo elija por él y pierda el caso que no eligió.
    """
    fila = fila if isinstance(fila, dict) else {}
    v = str(fila.get(COL_REEMPLAZA) or "").strip()
    rid = None
    if v and v.lower() not in _NEGATIVOS and v.lower() not in _AFIRMATIVOS:
        rid = v
    ref = str(fila.get(COL_REFERENCIA) or "").strip() or None
    return rid, ref


def sustituidas(filas):
    """Las claves que **ya tienen reentrega**: `{clave: request_id de quien la sustituye}`.

    ⛔⛔ La REFERENCIA sólo cuenta cuando la reentrega **no trae `request_id`** (el caso de los
    `Sí` y los `TRUE`). Si contara siempre, en una cadena de tres —que es lo que hay de verdad
    con `Informe_S-6009_26`— **las tres comparten la referencia**, así que la última quedaría
    marcada como sustituida por una de las anteriores y el expediente vivo se enterraría solo.
    El `request_id` es la clave precisa; la referencia, el paracaídas.
    ⚠️ Se guarda **quién** la declaró para poder excluir a la propia fila: una reentrega lleva
    su misma referencia, y si no, cada `Sí` se marcaría a sí mismo.
    """
    fuera = {}
    for f in (filas or []):
        if not isinstance(f, dict) or not declara(f):
            continue
        quien = str(f.get("request_id") or "").strip()
        rid, ref = apunta_a(f)
        if rid:
            fuera.setdefault(rid, quien)
        elif ref:
            fuera.setdefault(ref, quien)
    return fuera


def quien_sustituye(fila, claves):
    """El `request_id` de la reentrega de esta fila, o `None`. Nunca lanza.

    ⚠️ Nunca por sí misma: una reentrega lleva la misma referencia que el original, así que sin
    excluir al declarante un `Sí` se daría por sustituido a sí mismo y se enterraría solo.
    """
    fila = fila if isinstance(fila, dict) else {}
    claves = claves or {}
    yo = str(fila.get("request_id") or "").strip()
    for col in ("request_id", "reference"):
        v = str(fila.get(col) or "").strip()
        if v and v in claves and claves[v] != yo:
            return claves[v] or u"otra fila"
    return None


def esta_sustituida(fila, claves):
    """¿A esta fila le ha llegado ya su reentrega? Por la misma puerta que `quien_sustituye`.

    ⛔ Es un envoltorio a propósito y no una segunda implementación: el criterio ya estuvo
    escrito **dos veces** —aquí y en `pipeline`— y la copia de `pipeline` salió **ciega** a la
    mutación que le quitaba la exclusión de sí misma. Dos copias que hoy coinciden por
    casualidad no dan ningún síntoma hasta el día que una cambia.
    """
    return quien_sustituye(fila, claves) is not None


def revisar(filas):
    """Lo que no cuadra en las cadenas. Lista de `(fila_1based, request_id, qué)`."""
    filas = [f for f in (filas or []) if isinstance(f, dict)]
    avisos = []
    ids = set(str(f.get("request_id") or "").strip() for f in filas)
    refs = set(str(f.get("reference") or "").strip() for f in filas)
    ids.discard("")
    refs.discard("")

    for i, f in enumerate(filas):
        n = i + 2
        rid = str(f.get("request_id") or "").strip() or u"(sin request_id)"
        if not declara(f):
            continue
        apunta_id, apunta_ref = apunta_a(f)

        if not apunta_id and not apunta_ref:
            avisos.append((n, rid, u"dice ser una reentrega y no dice de qué: sin `%s` ni `%s` "
                                   u"no hay forma de atarla al original, y el original se queda "
                                   u"esperando un reenvío que ya llegó"
                           % (COL_REEMPLAZA, COL_REFERENCIA)))
            continue

        if apunta_id and apunta_id not in ids:
            avisos.append((n, rid, u"dice sustituir a %r y ese `request_id` no está en la hoja"
                           % apunta_id))
        if apunta_ref and apunta_ref not in refs:
            avisos.append((n, rid, u"dice sustituir a la referencia %r y no hay ninguna fila con "
                                   u"ella" % apunta_ref))
        if apunta_id and apunta_id == str(f.get("request_id") or "").strip():
            avisos.append((n, rid, u"dice sustituirse a sí misma"))
        # ⚠️ El motivo no es adorno: es lo que lee quien revisa para saber si la reentrega
        #    arregla lo que se pidió. Sin él hay que abrir los dos documentos y compararlos.
        if not str(f.get(COL_MOTIVO) or "").strip():
            avisos.append((n, rid, u"es una reentrega sin motivo escrito: quien revise tendrá "
                                   u"que abrir los dos documentos para ver qué cambió"))

    avisos.sort(key=lambda a: (a[0], a[2]))
    return avisos


if __name__ == "__main__":  # pragma: no cover
    print("La cadena de reentregas. Para probarla: python scripts/test_sustitucion.py")
