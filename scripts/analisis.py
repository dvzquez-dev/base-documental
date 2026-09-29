#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""La frontera con el modelo: validar y normalizar lo que devuelve el paso 2.

Por qué hace falta
------------------
El paso 2 es el único que seguirá llamando a un modelo, y un modelo **improvisa el formato**. Aquí
no se le juzga el criterio — resumir un documento está bien que lo haga él —, se le comprueba la
**forma**, que es lo que el resto del código da por hecho.

⛔ **Y no es precaución teórica.** Medido el 29/09/2026 en `SOLICITUDES.quality_issues`, filas
reales consecutivas:

```
{"severity":"MEDIA",       "issues":[...]}     ← español, mayúsculas
{"severity": "LOW_MEDIUM", "issues": [...]}    ← inglés, y COMPUESTO
```

El contrato dice `severidad ∈ baja | media | alta`. **Ninguno de los dos lo cumple**, y
`LOW_MEDIUM` ni siquiera está en ese conjunto. La app pinta la severidad en la tarjeta que el
revisor mira antes de aprobar, así que un valor que no reconoce se queda sin pintar y el revisor
decide **sin ver los avisos de calidad**.

La decisión que importa: un compuesto sube, no baja
---------------------------------------------------
`LOW_MEDIUM` son dos niveles a la vez. Se resuelve al **más alto**, no al más bajo. Equivocarse
hacia arriba hace que alguien mire un documento que estaba bien; equivocarse hacia abajo hace que
alguien apruebe uno que no lo estaba.

Cómo se prueba
--------------
`python scripts/test_analisis.py` — sin red ni credenciales.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding="utf-8")
    except Exception:  # pragma: no cover
        pass

import hoja as H


NIVELES = ("baja", "media", "alta")

# 📏 Lo que se ha visto de verdad, más las formas obvias del mismo vocabulario. Un valor que no
#    esté aquí devuelve `None`: inventarse un nivel es peor que decir que no se sabe.
_SEVERIDAD = {
    "baja": "baja", "low": "baja", "leve": "baja",
    "media": "media", "medium": "media", "moderada": "media", "moderate": "media",
    "alta": "alta", "high": "alta", "critica": "alta", "critical": "alta", "grave": "alta",
}

_ORDEN = dict((n, i) for i, n in enumerate(NIVELES))


def severidad(valor):
    """`"baja"`, `"media"`, `"alta"` o `None`.

    Acepta las dos lenguas y cualquier caja, y resuelve los **compuestos** (`LOW_MEDIUM`,
    `media-alta`) **al más alto de los dos**.
    """
    v = str(valor if valor is not None else "").strip().lower()
    if not v:
        return None

    # Se parte por los separadores que se han visto y por los obvios del mismo estilo.
    trozos = [t for t in v.replace("-", "_").replace("/", "_").replace(" ", "_").split("_") if t]
    niveles = [_SEVERIDAD[t] for t in trozos if t in _SEVERIDAD]
    if not niveles:
        return None
    # ⛔ `max` por el orden baja<media<alta: hacia arriba, nunca hacia abajo.
    return max(niveles, key=lambda n: _ORDEN[n])


def avisos(calidad):
    """La lista de avisos de calidad, limpia. `[]` si no hay ninguno.

    Acepta el `dict` ya parseado o la cadena JSON tal cual está en la celda, porque de la hoja
    viene lo segundo y de una llamada al modelo lo primero.
    """
    d = _dict(calidad)
    brutos = d.get("issues")
    if brutos is None:
        brutos = d.get("avisos")
    if isinstance(brutos, (str, bytes)):
        brutos = [brutos]
    fuera = []
    for a in (brutos or []):
        t = str(a if a is not None else "").strip()
        if t:
            fuera.append(t)
    return fuera


def _dict(v):
    """Un `dict` desde un `dict` o desde una cadena JSON. `{}` si no se puede."""
    if isinstance(v, dict):
        return v
    try:
        cargado = json.loads(v)
    except Exception:
        return {}
    return cargado if isinstance(cargado, dict) else {}


def etiquetas(valor):
    """`(etiquetas, motivos)` desde `tags_json`. Con motivos, la lista sale **sin** las malas.

    ⛔ Una etiqueta con **coma** no puede ir a un multi-select de Notion: Notion parte por comas,
    así que `"control, EKF"` entraría como **dos** opciones nuevas y ninguna sería la que se
    quería. Se rechaza con su motivo en vez de colarla.

    ⚠️ Aquí, a diferencia de las propiedades de la página, las buenas **sí pasan**: perder todas
    las etiquetas porque una lleve una coma deja el documento sin indexar por ninguna.
    """
    # ⛔ Por la PUERTA ÚNICA: la columna se llama `tags_json` y **miente en una fila de
    #    quince** — medido el 29/09/2026—, y la de los anexos hace lo mismo. El lector de
    #    «JSON o comas» vive en `hoja.lista_de_celda` para que curarlo aquí no deje rota la otra.
    brutas, motivos = H.lista_de_celda(valor, u"`tags_json`")
    if motivos and not brutas:
        return [], motivos

    fuera = []
    vistas = set()
    for e in brutas:
        t = str(e if e is not None else "").strip()
        if not t:
            continue
        if "," in t:
            motivos.append(u"la etiqueta %r lleva una coma: Notion la partiría en dos opciones "
                           u"nuevas y ninguna sería la que se quiere" % t)
            continue
        if t.lower() in vistas:
            continue
        vistas.add(t.lower())
        fuera.append(t)
    return fuera, motivos


def revisar_analisis(calidad, tags_json):
    """`(normalizado, motivos)` para lo que el modelo devolvió de un expediente.

    `normalizado` es `{"severidad", "avisos", "etiquetas"}`. Se devuelve **siempre**, también con
    motivos: lo que sí se entendió sirve igual, y tirarlo entero porque una parte venga rara deja
    al revisor sin los avisos de calidad justo cuando hay algo raro.
    """
    motivos = []
    d = _dict(calidad)

    cruda = d.get("severity", d.get("severidad"))
    sev = severidad(cruda)
    if sev is None:
        motivos.append(u"la severidad %r no es un nivel reconocible: la tarjeta la dejaría en "
                       u"blanco y el revisor decidiría sin verla" % (cruda,))
    elif str(cruda or "").strip().lower() not in NIVELES:
        # No es un fallo, pero conviene que se vea: el modelo no está usando el vocabulario.
        motivos.append(u"la severidad venía como %r y se ha normalizado a %r" % (cruda, sev))

    avs = avisos(d)
    if not avs and sev in ("media", "alta"):
        motivos.append(u"severidad %r sin un solo aviso: o falta el detalle o la severidad sobra"
                       % sev)

    etqs, m_etq = etiquetas(tags_json)
    motivos.extend(m_etq)

    return {"severidad": sev, "avisos": avs, "etiquetas": etqs}, motivos


# ── El encargo: qué se le pide al modelo y qué se hace con lo que conteste ─────────────────
# ⛔ Un resumen más corto que esto no es un resumen. `crear_resumen` se niega a archivar un
#    fichero vacío —con razón: *«un documento con un resumen en blanco es peor que uno sin
#    resumen»*—, así que dejarlo pasar deja el expediente publicado sin nada que leer.
MIN_RESUMEN = 20


def prompt_de(fila, texto=None):
    """El encargo del paso 2, con los datos del expediente **y el documento** dentro.

    ⛔ **`texto` es el contenido del documento, y sin él esto es adivinar por el título.** Nació
    sin ese argumento y el resumen ejecutivo salía de los metadatos: se lee bien, no dice nada, y
    el revisor ya veía el título. Quien llama es `servicios.analizar`, que lo baja de Drive con
    `documento.texto_de` — y **se planta** si no hay texto, en vez de pedir un resumen a ciegas.

    ⛔ **Nombra el título, el tipo y la unidad**: sin eso el modelo resume a ciegas y el resumen
    sale genérico, que es exactamente lo que el revisor no necesita.
    ⛔ **Pide JSON explícitamente y nombra las claves y los tres niveles.** `modelo.leer_json`
    sabe rebuscar el objeto entre la prosa, pero eso es el **paracaídas, no el plan**; y si no se
    nombran los niveles el modelo se inventa su vocabulario y `severidad()` devuelve `None` —
    correcto, y deja el expediente sin severidad.
    """
    f = fila if isinstance(fila, dict) else {}

    def _c(k, sino=u"(sin dato)"):
        return str(f.get(k) or "").strip() or sino

    return (
        u"Eres el analista documental de UVigo Aerotech: Solaris, un equipo universitario de\n"
        u"cohetería. Analiza el documento que se te indica y devuelve SOLO un objeto JSON.\n"
        u"\n"
        u"EXPEDIENTE\n"
        u"  Referencia : %s\n"
        u"  Título     : %s\n"
        u"  Tipo       : %s\n"
        u"  Unidad     : %s\n"
        u"  Autor      : %s\n"
        u"  Temporada  : %s\n"
        u"\n"
        u"DEVUELVE UN OBJETO JSON con exactamente estas claves:\n"
        u"  \"resumen\"    : resumen ejecutivo en español, de 2 a 4 frases. Lo lee quien tiene\n"
        u"                 que aprobar el documento sin abrirlo, así que di QUÉ contiene y\n"
        u"                 PARA QUÉ sirve, no que «es un informe».\n"
        u"  \"etiquetas\"  : lista de 2 a 6 etiquetas temáticas. Sin comas dentro de una\n"
        u"                 etiqueta: se indexan en un multi-select y una coma la partiría\n"
        u"                 en dos.\n"
        u"  \"severidad\"  : uno de \"%s\", exactamente. Es la urgencia con la que hay que\n"
        u"                 mirar el documento antes de aprobarlo, no su importancia.\n"
        u"  \"avisos\"     : lista de problemas de calidad concretos y accionables (falta la\n"
        u"                 fecha, la referencia no coincide, secciones vacías…). Lista vacía\n"
        u"                 si no hay ninguno.\n"
        u"\n"
        u"Si la severidad es \"media\" o \"alta\", tiene que venir con al menos un aviso que la\n"
        u"justifique. No añadas texto fuera del JSON.\n"
        u"\n"
        u"DOCUMENTO\n"
        u"%s\n"
        % (_c("reference"), _c("doc_title"), _c("doc_type"), _c("unit_label"),
           _c("author_name"), _c("season"), u'", "'.join(NIVELES),
           # ⚠️ El aviso va DENTRO del encargo, no sólo en la consola: si el documento no se
           #    pudo leer, el modelo tiene que saber que no lo tiene — si no, se lo inventa.
           str(texto or u"").strip()
           or u"(no se ha podido leer el documento: NO inventes su contenido)")
    )


def de_la_respuesta(datos):
    """`(columnas, motivos)`: qué escribir en `SOLICITUDES` con lo que contestó el modelo.

    ⛔⛔ **`analyzed` solo se marca si el análisis vino ENTERO.** Un paso que escribe la bandera
    sin los datos deja el expediente **dado por analizado sin análisis**, y el siguiente paso lo
    publica: el revisor abre la ficha y no ve ni resumen ni avisos, que es justo lo que tiene que
    leer antes de aprobar. Por eso `servicios.analizar` se negaba en voz alta hasta hoy — y esta
    función existe para poder dejar de negarse **sin perder esa garantía**.

    ⚠️ **Sin etiquetas SÍ se da por analizado**: no todo documento tiene etiquetas que poner, y
    exigirlas pararía expedientes correctos. La columna queda como `[]`, no vacía.

    ⚠️ Reutiliza `severidad`, `avisos` y `etiquetas`, que ya saben lo que de verdad llega:
    `LOW_MEDIUM`, las dos lenguas, y las listas **separadas por comas** (`hoja.lista_de_celda`).
    """
    d = _dict(datos)
    motivos = []

    resumen = str(d.get("resumen") or d.get("executive_summary") or "").strip()
    if len(resumen) < MIN_RESUMEN:
        motivos.append(u"el resumen ejecutivo falta o es demasiado corto (%d caracteres): sin él "
                       u"no hay nada que archivar y el revisor decide sin leerlo"
                       % len(resumen))

    cruda = d.get("severidad", d.get("severity"))
    sev = severidad(cruda)
    if sev is None:
        motivos.append(u"la severidad %r no es un nivel reconocible: la tarjeta la dejaría en "
                       u"blanco y el revisor decidiría sin verla" % (cruda,))

    avs = avisos(d)
    etqs, m_etq = etiquetas(d.get("etiquetas", d.get("tags")))
    motivos.extend(m_etq)

    columnas = {
        "executive_summary": resumen,
        "quality_issues": json.dumps({"severity": sev, "issues": avs}, ensure_ascii=False),
        "tags_json": json.dumps(etqs, ensure_ascii=False),
    }
    # ⛔ La bandera va al final y SOLO con las dos cosas que el resto del pipeline da por hechas.
    if resumen and len(resumen) >= MIN_RESUMEN and sev is not None:
        columnas["analyzed"] = "TRUE"
    return columnas, motivos


if __name__ == "__main__":  # pragma: no cover
    print("La frontera con el modelo. Para probarla: python scripts/test_analisis.py")
