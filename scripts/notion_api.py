#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""El cuerpo que espera la API de Notion, construido. Sin tocar la red.

Por qué es una pieza y no dos líneas
------------------------------------
`publicar_notion.propiedades` devuelve un diccionario llano (`{"Título": …, "ID (XXXX)": 4012}`).
La API no acepta eso: cada propiedad va **envuelta según su tipo**, y el tipo hay que saberlo.
📏 Medidos del esquema vivo el 29/09/2026:

| Propiedad | Tipo |
|---|---|
| `Título` | `title` |
| `ID (XXXX)` | `number` |
| `Subsistema o Unidad`, `Tipo Aerotech`, `Temporada` | `select` |
| `Etiquetas` | `multi_select` (**183 opciones** ya) |

⛔ **El envoltorio equivocado no da un error que se entienda**, y en el mejor caso deja la
propiedad vacía en una página que sí se crea. O sea: el documento aparece publicado y sin
clasificar.

El problema de verdad: las etiquetas nuevas
-------------------------------------------
Un `multi_select` **crea la opción si no existe**. Medido cruzando las etiquetas reales de cuatro
documentos (`SOLICITUDES.tags_json`) con las 183 opciones de Notion:

- **19** coinciden exactas,
- **22** son nuevas de verdad,
- ⛔ **7 sólo se diferencian en la caja o las tildes** de una que ya existe: `Python`/`python`,
  `MPC`/`mpc`, `RocketPy`/`rocketpy`, `VSPAERO`/`vspaero`, `simulación`/`simulacion`, y
  `Viradinha MKII` **y** `Viradinha MkII` contra `viradinha mkII` — el modelo escribió **el mismo
  tag de dos formas en dos documentos**, y ninguna era la que ya estaba.

Eso no da ningún error: deja dos opciones donde había una, y quien filtre por la vieja **deja de
ver los documentos nuevos**. La lista ya arrastra un caso así: `análisis` y `analisis`.

✅ Por eso, antes de mandar una etiqueta se busca entre las que **ya existen** ignorando caja y
tildes, y si aparece **se manda la que ya está**. Las de verdad nuevas se mandan tal cual y se
devuelven aparte, para que se vea cuántas se están creando.

Cómo se prueba
--------------
`python scripts/test_notion_api.py` — sin red ni credenciales.
"""
import sys
import unicodedata

for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding="utf-8")
    except Exception:  # pragma: no cover
        pass


# 📏 Los tipos, medidos del esquema de «Documentos internos» el 29/09/2026.
TIPOS_PROP = {
    "Título": "title",
    "ID (XXXX)": "number",
    "Subsistema o Unidad": "select",
    "Tipo Aerotech": "select",
    "Temporada": "select",
    "Etiquetas": "multi_select",
}


def _plano(t):
    """El texto sin tildes y en minúsculas, para comparar — nunca para enviar.

    ⚠️ Lo aplanado **no se manda a Notion**: se usa sólo para reconocer que dos formas son la
    misma. Mandar la versión aplanada crearía una tercera opción, que es el problema al revés.
    """
    t = unicodedata.normalize("NFKD", str(t if t is not None else ""))
    return u"".join(c for c in t if not unicodedata.combining(c)).strip().lower()


def casar_etiquetas(etiquetas, opciones):
    """`(a_enviar, reusadas, nuevas)`.

    - `a_enviar`: lo que se manda, con la grafía **que ya está en Notion** cuando la hay.
    - `reusadas`: `[(lo_que_vino, lo_que_se_manda)]` — las que se han rescatado de un duplicado.
    - `nuevas`: las que van a **crear** una opción. No es un error, pero se devuelve para que se
      vea: 22 de 48 en la medición del 29/09, y una lista de etiquetas que crece sin que nadie
      mire acaba siendo inútil para filtrar.
    """
    indice = {}
    for o in (opciones or []):
        indice.setdefault(_plano(o), o)

    enviar, reusadas, nuevas, vistas = [], [], [], set()
    for e in (etiquetas or []):
        t = str(e if e is not None else "").strip()
        if not t:
            continue
        k = _plano(t)
        if k in indice:
            final = indice[k]
            if final != t:
                reusadas.append((t, final))
        else:
            final = t
            nuevas.append(t)
            # La nueva pasa a ser conocida: si el mismo documento trae `Viradinha MkII` y
            # `Viradinha MKII`, la segunda se casa con la primera en vez de crear dos.
            indice[k] = t
        if _plano(final) in vistas:
            continue
        vistas.add(_plano(final))
        enviar.append(final)
    return enviar, reusadas, nuevas


def propiedad(nombre, valor):
    """El objeto con el que la API espera esa propiedad, o `None` si no se sabe envolverla."""
    tipo = TIPOS_PROP.get(nombre)
    if tipo is None:
        return None
    if tipo == "title":
        return {"title": [{"text": {"content": str(valor)}}]}
    if tipo == "number":
        return {"number": valor}
    if tipo == "select":
        return {"select": {"name": str(valor)}}
    if tipo == "multi_select":
        return {"multi_select": [{"name": str(v)} for v in (valor or [])]}
    return None                                                          # pragma: no cover


def cuerpo_pagina(data_source_id, propiedades, opciones_etiquetas=None, markdown_source=None):
    """`(cuerpo, avisos)` para crear la página. Con avisos graves, `cuerpo` es `None`.

    ⛔ Una propiedad que no se sabe envolver **para la creación entera**, no se omite. Omitirla
    crea la página **sin clasificar**, y una página publicada a medias no la vuelve a mirar nadie:
    ya está «hecha».
    """
    avisos = []
    props = {}

    if not str(data_source_id or "").strip():
        avisos.append(u"sin `data_source_id`: no se sabe en qué base crear la página")

    for nombre in sorted(propiedades or {}):
        valor = propiedades[nombre]
        if nombre == "Etiquetas":
            enviar, reusadas, nuevas = casar_etiquetas(valor, opciones_etiquetas)
            for vino, va in reusadas:
                avisos.append(u"la etiqueta %r se manda como %r, que es la que ya existe: si no, "
                              u"quedarían dos opciones donde hay una" % (vino, va))
            if nuevas:
                avisos.append(u"se crearán %d opciones nuevas de «Etiquetas»: %s"
                              % (len(nuevas), u", ".join(nuevas)))
            valor = enviar
        envuelta = propiedad(nombre, valor)
        if envuelta is None:
            avisos.append(u"no sé envolver la propiedad %r: crear la página sin ella la dejaría "
                          u"sin clasificar, y una página publicada a medias no la vuelve a mirar "
                          u"nadie" % nombre)
            continue
        props[nombre] = envuelta

    graves = [a for a in avisos if a.startswith(u"sin `data_source_id`") or
              a.startswith(u"no sé envolver")]
    if graves:
        return None, avisos

    cuerpo = {"parent": {"type": "data_source_id", "data_source_id": data_source_id},
              "properties": props}
    if markdown_source:
        # El `markdown_source` que devuelve la subida directa de ficheros: no hace falta ninguna
        # URL pública, medido el 29/09 ejecutándolo.
        cuerpo["children"] = [{"object": "block", "type": "file",
                               "file": {"type": "file_upload",
                                        "file_upload": {"id": markdown_source}}}]
    return cuerpo, avisos


if __name__ == "__main__":  # pragma: no cover
    print("El cuerpo para Notion. Para probarlo: python scripts/test_notion_api.py")
