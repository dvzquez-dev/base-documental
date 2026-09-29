#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Paso 5 del pipeline documental: las propiedades de la página de Notion, construidas.

Por qué existe
--------------
Este paso era «la última incógnita»: se dijo que requería una sesión de Cowork. Se midió el
29/09/2026 y no es verdad — **la API de Notion acepta el fichero directamente**, sin URL
pública (HTTP 200, `status: uploaded`, con `markdown_source`). Lo que fallaba era el conector,
que sólo sabía adjuntar desde una URL, y por eso existe todo el montaje de GitHub Pages.

Con eso, el paso 5 deja de necesitar a nadie vivo. Lo que queda es esto: traducir un expediente
a las propiedades de la base «Documentos internos». Es una tabla de equivalencias, y una tabla
de equivalencias es código.

⛔ Y ES LA PIEZA QUE MÁS FALTA HACÍA ESCRITA. Cowork señaló como su punto más frágil que «la
traducción de las etiquetas a las rutas no está escrita en ningún sitio; la deduce el modelo cada
vez». Esta es la otra mitad de esa misma traducción: de `unit_key` al nombre que Notion enseña.

Cómo se prueba
--------------
`python scripts/test_publicar_notion.py` — sin red ni credenciales.
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

import analisis as A


# ── La traducción que sólo vivía en la cabeza del modelo ────────────────────────────────────
# ⛔ MEDIDO el 28/09/2026 leyendo el esquema real de la base «Documentos internos» y la pestaña
#    RUTAS. Las claves son las `unit_key` de RUTAS; los valores, las opciones EXACTAS del
#    desplegable «Subsistema o Unidad» de Notion, con sus tildes y su `&` sin espacios.
# ⚠️ NO coinciden con los nombres nuevos del equipo (GNC, Aviónica, Aeroestructuras): Notion
#    conserva los viejos a propósito, porque renombrarlos cambiaría lo que muestran los
#    documentos de cursos pasados. Esa decisión es de Daniel y está sin tomar.
UNIDAD_NOTION = {
    "dinamica_control": "Subsistema de Dinámica&Control",
    "electronica": "Subsistema de Electrónica",
    "estructuras_aerodinamica": "Subsistema de Estructuras&Aerodinámica",
    "propulsion": "Subsistema de Propulsión",
    "uct": "Unidad de Coordinación Técnica",
    "recovery": "Unidad de Recovery",
    "seguridad_verificacion": "Unidad de Seguridad y Verificación",
    "patrocinios_relaciones_externas": "Unidad de Patrocinios y Relaciones Externas",
    "logistica": "Unidad de Logística",
}

# Los valores que admite «Tipo Aerotech», medidos del esquema. El formulario ofrece doce y
# Notion trece: la que sobra es `SinTipo`, que existe para lo que no encaja.
TIPOS_NOTION = ("txt", "Cuestionario", "Carpeta", "Informe", "Imagen", "Tabla", "Pieza",
                "Simulación", "Manual", "SinTipo", "Informe de Subsistema", "Memoria", "Acta")

TEMPORADAS_NOTION = ("2024/25", "2025/26", "2026/27")


def unidad_de(unit_key):
    """La opción de Notion para una `unit_key` de RUTAS, o `None`.

    ⛔ `None`, nunca una aproximación. Notion rechaza una opción que no existe, y el modo de
    fallo de «parecerse» sería peor: una página archivada bajo el subsistema equivocado no da
    error y nadie la busca donde está.
    """
    return UNIDAD_NOTION.get(str(unit_key or "").strip())


def tipo_de(document_type):
    """El «Tipo Aerotech» para el tipo que puso el autor en el formulario, o `None`.

    ⚠️ NO cae a `SinTipo` por su cuenta. `SinTipo` es una respuesta legítima cuando de verdad
    no se sabe, pero ponerla automáticamente convierte «no reconozco este tipo» en un dato, y
    entonces nadie se entera de que el formulario ofrece algo que Notion no tiene.
    """
    v = str(document_type or "").strip()
    return v if v in TIPOS_NOTION else None


def temporada_de(season_label):
    """La opción de «Temporada», o `None` si esa temporada no existe todavía en la base.

    ⛔ Esto es un guardia con historia: el 28/09 la opción `2026/27` **no existía**, y el primer
    documento del curso habría fallado al publicarse. Se añadió a mano. Mientras la base no las
    genere sola, cada 1 de septiembre hay que crearla — y este `None` es lo que hace que se
    note en vez de romperse por dentro.
    """
    v = str(season_label or "").strip()
    return v if v in TEMPORADAS_NOTION else None


_REF = re.compile(r"^[A-Za-zÀ-ÖØ-öø-ÿ]+_S-(\d{3,5})_(\d{2})$")


def id_de_referencia(reference):
    """El número de la referencia, para la propiedad «ID (XXXX)». `None` si no es canónica.

    ⚠️ Se saca de la referencia y no del `reserved_id` a propósito: si los dos discreparan,
    la página debe llevar el número que lleva el documento impreso en la cabecera, que es por
    el que alguien lo va a buscar.
    """
    m = _REF.match(str(reference or "").strip())
    return int(m.group(1)) if m else None


def propiedades(expediente):
    """Las propiedades de la página, o `(None, motivos)` si falta algo.

    Devuelve siempre una tupla `(propiedades, motivos)`. Con motivos, `propiedades` es `None`:
    no se publica a medias. Una página creada sin unidad o sin temporada hay que ir a
    arreglarla a mano, y nadie sabe que existe hasta que la busca.
    """
    motivos = []

    titulo = str(expediente.get("title_short") or "").strip()
    if not titulo:
        motivos.append("sin título: la página quedaría «Sin título» en el índice del equipo")

    unidad = unidad_de(expediente.get("unit_key"))
    if unidad is None:
        motivos.append("la unidad %r no tiene opción en Notion: hay que añadirla antes de "
                       "publicar" % (expediente.get("unit_key"),))

    tipo = tipo_de(expediente.get("document_type"))
    if tipo is None:
        motivos.append("el tipo %r no está en «Tipo Aerotech»: el formulario ofrece algo que "
                       "Notion no tiene" % (expediente.get("document_type"),))

    temporada = temporada_de(expediente.get("season_label"))
    if temporada is None:
        motivos.append("la temporada %r no existe en la base: se crea a mano cada 1 de "
                       "septiembre" % (expediente.get("season_label"),))

    numero = id_de_referencia(expediente.get("reference"))
    if numero is None:
        motivos.append("la referencia %r no es canónica: sin ella la página no se puede "
                       "encontrar por su número" % (expediente.get("reference"),))

    if motivos:
        return None, motivos

    props = {
        "Título": titulo,
        "ID (XXXX)": numero,
        "Subsistema o Unidad": unidad,
        "Tipo Aerotech": tipo,
        "Temporada": temporada,
    }
    # ⛔ El `if e` va ANTES del `str()`: `str(None).strip()` es `"None"`, que es verdadero, y
    #    colaba en Notion una etiqueta fantasma llamada «None». Lo cazó el banco.
    crudas = expediente.get("tags")
    avisos_etq = []
    if crudas is None:
        # ⛔⛔ La columna se llama `tags_json`, no `tags`. Leyendo `tags` —que no existe en
        #    `SOLICITUDES`— **ninguna página publicada llevaba etiquetas**, y sin dar un solo
        #    error: la página se creaba, vacía de etiquetas, y nadie lo notaba. Con ella se
        #    quedaban muertas `analisis.etiquetas` y toda la máquina de no duplicar opciones de
        #    `notion_api.casar_etiquetas`. `tags` sigue mandando si viene: es por donde entran
        #    unas ya casadas.
        crudas, avisos_etq = A.etiquetas(expediente.get("tags_json"))
    etiquetas = [str(e).strip() for e in (crudas or []) if e and str(e).strip()]
    if etiquetas:
        props["Etiquetas"] = etiquetas
    # ⚠️ Los avisos de las etiquetas van **detrás** de devolver las propiedades, no delante:
    #    perder las etiquetas es malo, **no publicar el documento es peor**. Pero se dice.
    return props, avisos_etq


if __name__ == "__main__":  # pragma: no cover
    print("Lógica pura del Paso 5. Para probarla: python scripts/test_publicar_notion.py")
