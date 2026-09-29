#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""El paso 2 del pipeline —el análisis— preguntándole a **Claude Code en local**.

Por qué no es la API
--------------------
⛔ **Decisión de Daniel, de julio de 2026**, escrita en `ARRANQUE.md` §3.6 del panel y en
`rutinas/README.md`: *«NADA de `ANTHROPIC_API_KEY` ni de GitHub Action ejecutando Claude (la API
cobra por token). Las rutinas corren como sesiones de Claude Code, sobre la SUSCRIPCIÓN, igual
que la pipeline documental (Cowork)»*. Y el destino es **un minipc con una tarea programada**,
no GitHub Actions.

Qué hay aquí y qué NO
---------------------
⛔ **Aquí NO está cómo se lanza Claude Code.** Eso vive en `claude_local.py`, que es **el mismo
fichero** que usa `rutinas/gate.py` del panel —copiado tal cual, y el banco comprueba que no ha
divergido—. Estuvo escrito dos veces unas horas y lo cortó Daniel: *«ni se te ocurra andar
repitiendo código en lugar de reutilizarlo»*. Dos copias de un criterio no dan **ningún síntoma**
hasta el día que una cambia.

Aquí está sólo lo que el pipeline añade encima: **leer lo que contestó el modelo sin fiarse**.

⚠️ **`analisis.py` sigue siendo determinista y no se toca.** La severidad y los avisos de calidad
se calculan con reglas; lo que necesita un modelo es el **resumen ejecutivo** y la propuesta de
**etiquetas**. Mezclarlos sería hacer que un dato que hoy es reproducible dependa de una llamada
que puede no contestar.

Cómo se prueba
--------------
`python scripts/test_modelo.py` — sin red, sin credenciales y **sin arrancar ningún proceso**.
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

import claude_local

# Se re-exportan a propósito: quien llame a `modelo` no tiene por qué saber dónde vive el
# lanzador, y así no hay dos nombres para lo mismo.
PISTAS_SESION = claude_local.PISTAS_SESION
ejecutable = claude_local.ejecutable
orden = claude_local.orden
entorno = claude_local.entorno
caducada = claude_local.caducada

# ⚠️ 10 min: un análisis es UNA pregunta con un documento dentro, no una sesión de trabajo. El
#    gate del panel usa 30 porque allí Claude edita código.
TIMEOUT_S = 10 * 60

_VUELVE = u"la sesión de Claude Code ha caducado: vuelve a iniciar sesión (`claude`)"


def leer_json(salida):
    """El objeto JSON que trae la salida, o `None`.

    ⛔ **No es `json.loads` de la salida entera.** Claude Code escribe prosa alrededor del JSON
    más veces de las que uno quiere, y vallas de ``` ```. Se busca el objeto.
    ⛔ Y **una lista no es el objeto del análisis**: aceptarla no revienta aquí, revienta luego
    al leer una clave, lejos de este fichero y sin decir por qué.
    """
    s = claude_local.texto_hijo(salida).strip()
    if not s:
        return None
    try:
        v = json.loads(s)
        if isinstance(v, dict):
            return v
    except Exception:
        pass
    i, j = s.find("{"), s.rfind("}")
    while i != -1 and j > i:
        try:
            v = json.loads(s[i:j + 1])
            if isinstance(v, dict):
                return v
        except Exception:
            pass
        j = s.rfind("}", i, j)
    return None


def preguntar(prompt, modelo=None, correr=None):
    """Le pregunta a Claude Code y devuelve un resultado. **Nunca lanza.**

    `{ok, codigo, sesion_caducada, motivo, salida[, datos]}`. `salida` va SIEMPRE: es lo único
    que se lee cuando algo falla.
    """
    estado, salida, extra = claude_local.lanzar_crudo(
        prompt, TIMEOUT_S, modelo=modelo, correr=correr)

    if estado == "timeout":
        # ⛔⛔ La pista de sesión se busca TAMBIÉN aquí: una sesión caducada no falla, se queda
        #    esperando, así que llega por esta rama y no por la del código de salida.
        ses = claude_local.caducada(salida)
        corte = u"se pasó de %d min y la corté" % (TIMEOUT_S / 60)
        # ⚠️ Los DOS hechos, no uno: qué hacer (volver a iniciar sesión) y qué pasó (se quedó
        #    esperando hasta el tope). Quedarse sólo con el primero esconde que estuvo colgado.
        return {"ok": False, "codigo": "timeout", "sesion_caducada": ses,
                "motivo": (_VUELVE + u" — " + corte) if ses else corte,
                "salida": salida}

    if estado == "sin_claude":
        return {"ok": False, "codigo": "sin_claude", "sesion_caducada": False,
                "motivo": u"no encuentro Claude Code (%s): sin él el análisis no puede correr"
                          % (salida,),
                "salida": salida}

    if estado == "error":
        return {"ok": False, "codigo": "error", "sesion_caducada": False,
                "motivo": salida, "salida": salida}

    if estado == "codigo":
        ses = claude_local.caducada(salida)
        return {"ok": False, "codigo": extra.get("codigo"), "sesion_caducada": ses,
                "motivo": _VUELVE if ses
                          else u"Claude Code salió con código %s" % (extra.get("codigo"),),
                "salida": salida}

    datos = leer_json(salida)
    if datos is None:
        return {"ok": False, "codigo": 0, "sesion_caducada": False,
                "motivo": u"no encontré un objeto JSON en lo que contestó el modelo",
                "salida": salida}
    return {"ok": True, "codigo": 0, "sesion_caducada": False, "datos": datos,
            "motivo": u"", "salida": salida}


if __name__ == "__main__":  # pragma: no cover
    print(u"El paso 2 sobre Claude Code local. Pruébalo: python scripts/test_modelo.py")
    print(u"Ejecutable: %s" % ejecutable())
