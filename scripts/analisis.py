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
import sys

for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding="utf-8")
    except Exception:  # pragma: no cover
        pass


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
    motivos = []
    brutas = valor
    if isinstance(valor, (str, bytes)):
        crudo = valor.decode("utf-8", "replace") if isinstance(valor, bytes) else valor
        txt = crudo.strip()
        if not txt:
            return [], []
        try:
            brutas = json.loads(txt)
        except Exception:
            # ⛔⛔ La columna se llama `tags_json` y **miente en una fila de quince**. Medido en
            #    `SOLICITUDES` el 29/09/2026: 14 filas traen una lista JSON y la 8
            #    (`SOL-DOC-20260706-202210-1I8XUUNL`) trae las etiquetas **separadas por comas**.
            #    Con el lector estricto esa fila se publicaba con **0 etiquetas de 19**: el
            #    documento queda archivado y **no sale en ninguna búsqueda**. Se lee lo que hay.
            #    ⚠️ Pero un JSON **roto** sigue siendo un error: leerlo «como se pueda»
            #       convertiría `["a", "b"` en etiquetas llamadas `["a"` y `"b"`.
            if txt[:1] in ("[", "{"):
                return [], [u"`tags_json` empieza como JSON y no lo es: %r" % (crudo,)]
            brutas = txt.split(",")
            motivos.append(u"`tags_json` no venía en JSON sino separado por comas; se han leído "
                           u"%d etiquetas" % len([x for x in brutas if x.strip()]))
    if brutas is None:
        return [], []
    if not isinstance(brutas, list):
        return [], [u"`tags_json` no es una lista, es %s" % type(brutas).__name__]

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


if __name__ == "__main__":  # pragma: no cover
    print("La frontera con el modelo. Para probarla: python scripts/test_analisis.py")
