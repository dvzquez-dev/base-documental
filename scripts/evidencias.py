#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Lo que ya está hecho en el mundo aunque la hoja no lo diga.

El agujero que tapa
-------------------
⛔ El pipeline decide qué hacer **por las banderas**. Pero entre hacer el trabajo y escribir su
bandera hay un hueco, y ese hueco es real: acaba de medirse que **una escritura en Sheets puede no
hacer nada y decir que sí**.

Si la página de Notion se crea y la bandera `notion_page_created` no llega a escribirse, la pasada
siguiente ve `FALSE` y **la crea otra vez**. Dos páginas del mismo documento, ninguna marcada como
duplicada, y el equipo con dos sitios donde mirar. Lo mismo con la carpeta de Drive.

La idea, y por qué se puede
---------------------------
📏 **`SOLICITUDES` ya guarda la prueba**: junto a cada bandera hay una columna con el
identificador que devolvió el mundo. Medidas en la cabecera el 29/09/2026:

| Bandera | Su prueba |
|---|---|
| `notion_page_created` | `notion_page_id` |
| `drive_folder_created` | `drive_folder_id` |
| `drive_primary_file_verified` | `drive_primary_file_id` |
| `drive_summary_created` | `drive_summary_file_id` |
| `base_database_registered` | `base_database_row` |

Si el identificador está, **el trabajo se hizo**: nadie escribe un `notion_page_id` sin que Notion
haya devuelto uno. Entonces no hay que rehacerlo — hay que **anotarlo**.

⚠️ Y al revés **no vale**: una bandera puesta sin su identificador no prueba nada, y no se toca.
Borrarla «para rehacer» sería decidir por nuestra cuenta que algo no se hizo, y eso lo mira una
persona.

Cómo se prueba
--------------
`python scripts/test_evidencias.py` — sin red ni credenciales.
"""
import sys

for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding="utf-8")
    except Exception:  # pragma: no cover
        pass

import cierre as C


# 📏 Medido en la cabecera de `SOLICITUDES` (78 columnas) el 29/09/2026.
# ⚠️ Va en orden ALFABÉTICO a propósito, que NO es el de la cabecera. Escrito en el orden de la
#    cabecera, iterar el diccionario y iterar `BANDERAS` daban lo mismo y la garantía de orden era
#    **inobservable**: su mutación salía ciega. Así se puede comprobar, y añadir una entrada en
#    cualquier sitio deja de cambiar lo que se enseña.
# ⛔⛔ DOS SE CAYERON DE AQUÍ EL 29/09 (697.ª), Y NO POR GUSTO.
#    El código de Cowork que vive en este mismo repo lo dice literal:
#      «no toca `drive_folder_created`: esa la decide `05_publicar_aprobado` **cuando el resto
#       de la publicación esté completa**»  (`fix_docx_publication_date.py`)
#    O sea que `drive_folder_id` prueba que **la carpeta existe**, NO lo que la bandera afirma.
#    Anotarla al ver el id marcaría como publicado un expediente al que le falta todo lo demás.
#    ⚠️ Y `drive_primary_file_verified` se cae por lo mismo, leyendo su propio nombre: el id
#    prueba que el fichero **está**, no que se haya **verificado**. «Existe» y «comprobado» no
#    son la misma afirmación, y aquí la diferencia es justo lo que se estaba regalando.
#    ✅ Se quedan las tres cuyo identificador SÍ prueba lo que la bandera dice.
PRUEBA_DE = {
    "base_database_registered": "base_database_row",
    "drive_summary_created": "drive_summary_file_id",
    "notion_page_created": "notion_page_id",
}


def hay_prueba(valor):
    """¿Este valor es una prueba de que el trabajo se hizo?

    ⛔ **Sin `or ""`**, que es donde se cuela el cero: `0 or ""` vale `""`, así que un `0` pasaba
    por vacío **por accidente**, no por decisión. Aquí la decisión está escrita: un `0` **no** es
    prueba — no existe la fila 0 de una hoja ni un identificador `0` —, y darlo por bueno
    marcaría como hecho algo que no lo está, que es peor que rehacerlo.
    """
    if valor is None:
        return False
    if isinstance(valor, bool):
        return False
    if isinstance(valor, (int, float)):
        return valor != 0
    return bool(str(valor).strip())


def ya_hecho(fila):
    """Las banderas que están sin poner y **tienen su prueba**. Lista ordenada de nombres.

    ⚠️ El orden es el de `cierre.BANDERAS`, no el del diccionario: lo que se enseña a una persona
    va en el orden en que ocurren las cosas, no en el que Python decida iterar.
    """
    if not isinstance(fila, dict):
        return []
    fuera = []
    for bandera in C.BANDERAS:
        prueba = PRUEBA_DE.get(bandera)
        if not prueba:
            continue
        if C.es_si(fila.get(bandera)):
            continue
        if hay_prueba(fila.get(prueba)):
            fuera.append(bandera)
    return fuera


def motivos(fila):
    """Una línea por bandera anotable, diciendo qué prueba la sostiene."""
    fila = fila if isinstance(fila, dict) else {}
    return [u"%s está sin marcar pero %s ya tiene valor (%s): el trabajo se hizo y lo que falló "
            u"fue anotarlo" % (b, PRUEBA_DE[b], str(fila.get(PRUEBA_DE[b])).strip())
            for b in ya_hecho(fila)]


if __name__ == "__main__":  # pragma: no cover
    print("Lo ya hecho. Para probarlo: python scripts/test_evidencias.py")
