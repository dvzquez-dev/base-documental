#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cómo se lanza **Claude Code en local**, en un solo sitio.

Por qué existe
--------------
⛔ **Decisión de Daniel, de julio de 2026 y escrita en `ARRANQUE.md` §3.6 y en
`rutinas/README.md`**: *«NADA de `ANTHROPIC_API_KEY` ni de GitHub Action ejecutando Claude (la
API cobra por token). Las rutinas corren como sesiones de Claude Code, sobre la SUSCRIPCIÓN,
igual que la pipeline documental (Cowork)»*. Y el destino es **un minipc con una tarea
programada**.

⛔ **Y existe como fichero aparte porque ya había DOS sitios que necesitaban lo mismo**:
`rutinas/gate.py:lanzar` (las rutinas del panel) y el **paso 2 del pipeline documental**
(`base-documental/scripts/modelo.py`, el análisis que hasta ahora hacía Cowork a mano). Las
piezas de abajo estuvieron **copiadas** unas horas, y Daniel lo cortó en cuanto lo vio:
*«ni se te ocurra andar repitiendo código en lugar de reutilizarlo»*. Dos copias de un criterio
**no dan ningún síntoma** hasta el día que una cambia — es la avería de
`[[feedback_el_criterio_duplicado_que_coincide_por_casualidad]]`.

Las cuatro trampas, todas MEDIDAS y todas silenciosas
-----------------------------------------------------
1. ⛔ **La ruta al ejecutable va ABSOLUTA.** Una tarea programada **no hereda el `PATH`**, así
   que `claude` a secas sale como «no encuentro el ejecutable» — y sólo en el minipc, nunca
   cuando lo pruebas a mano.
2. ⛔ **`PYTHONIOENCODING=utf-8`, y sobre una COPIA del entorno.** Un hijo con la salida
   redirigida escribe en la página de códigos local y cada acento llega como `U+FFFD`; el
   `errors="replace"` lo hace en silencio (📏 **54 de 31.443 líneas** de la bitácora viva ya
   están así). Y `env=` **sustituye** el entorno: con sólo la variable nueva el hijo se queda
   sin `PATH` ni `SystemRoot`, y en Windows eso rompe el arranque del intérprete.
3. ⛔ **Lo que dijo el hijo al saltar el tope NO se tira.** Vive en `TimeoutExpired.stdout`
   —en Windows recogido con un `communicate()` posterior al `kill()`— y descartarlo deja **el
   caso más difícil de diagnosticar como el único sin ninguna pista**.
4. ⛔⛔ **Una sesión caducada no falla: ESPERA.** Atascada en el login llega al **timeout**, no
   a un `returncode != 0`. Buscar las pistas sólo en la rama del código de salida es no
   buscarlas donde de verdad aparecen.

Quién lo usa
------------
- `rutinas/gate.py` — `PISTAS_SESION`, `CLAUDE_EXE`, `texto_hijo`, `entorno`.
- `base-documental/scripts/modelo.py` — el mismo fichero, **copiado tal cual** por
  `rutinas/vendorizar_claude_local.py`, que además **comprueba que no ha divergido**.
"""
import os
import subprocess

# ⛔ Pistas de que la sesión de Claude Code caducó: el fallo más traicionero, porque la rutina
#    "corre" y no hace nada. Si aparecen, el aviso lo dice con todas las letras.
PISTAS_SESION = ("not logged in", "please log in", "authentication", "unauthorized",
                 "invalid api key", "credit balance", "/login")


def ejecutable():
    """El binario de Claude Code, por RUTA ABSOLUTA cuando existe.

    ⛔ Ruta absoluta a propósito: una tarea programada no hereda el `PATH` de tu terminal y
    `claude` a secas fallaría con «no encuentro el ejecutable». El respaldo existe para la
    terminal de quien lo prueba, no para el minipc.

    ⛔⛔ **Y se buscan los DOS nombres, `claude.exe` y `claude`.** Esto nació mirando sólo el
    `.exe`, que es lo que hay en el PC de Daniel — y el destino declarado es **un minipc, que
    puede ser Linux**. Allí el `.exe` no existe, así que caía al respaldo del `PATH`… que es
    justo lo que un `cron` o un `systemd` **tampoco** heredan. O sea: la protección se
    desactivaba sola **exactamente en la máquina para la que se escribió**, y sin dar ningún
    error — el fallo saldría como «no encuentro el ejecutable» el día del despliegue.
    ⚠️ El orden no importa para acertar (sólo existe uno de los dos), pero el `.exe` va primero
    porque es donde corre hoy.
    """
    base = os.path.join(os.path.expanduser("~"), ".local", "bin")
    for nombre in ("claude.exe", "claude"):
        exe = os.path.join(base, nombre)
        if os.path.isfile(exe):
            return exe
    return "claude"


def orden(prompt, modelo=None):
    """La línea de órdenes. `-p` es lo que lo hace headless: sin él abre sesión y se cuelga.

    ⚠️ Sin `modelo` **no se inventa uno**: que lo decida la configuración de Claude Code, que
    es de Daniel. Ponerlo aquí sería una segunda opinión que envejece sola.
    """
    cmd = [ejecutable(), "-p"]
    if modelo:
        cmd += ["--model", modelo]
    return cmd + [prompt]


def entorno():
    """El entorno del hijo: el de este proceso **más** la codificación.

    ⛔⛔ `dict(os.environ, ...)` y no `{...}`: `env=` SUSTITUYE el entorno. Con sólo la
    variable nueva el hijo se queda sin `PATH` ni `SystemRoot` y en Windows no arranca ni el
    intérprete — el fallo saldría como «la rutina no arranca» y mandaría a mirar la rutina.
    """
    return dict(os.environ, PYTHONIOENCODING="utf-8")


def texto_hijo(x):
    """Lo que dijo el hijo, venga como venga.

    ⚠️ En modo texto `subprocess` ya decodifica, pero `TimeoutExpired` se rellena por un camino
    que **no**: ahí puede llegar en bytes. Sin esto, buscar las pistas sobre `bytes` no casa con
    nada y una sesión caducada pasa por un cuelgue cualquiera.
    """
    if x is None:
        return u""
    if isinstance(x, bytes):
        return x.decode("utf-8", "replace")
    return x


def caducada(salida):
    """¿Huele esta salida a sesión caducada? Acepta texto o bytes."""
    return any(p in texto_hijo(salida).lower() for p in PISTAS_SESION)


def salida_de(r):
    """`stdout` + `stderr` de un resultado o de un `TimeoutExpired`, en texto y sin `None`."""
    return (texto_hijo(getattr(r, "stdout", None)) + u"\n"
            + texto_hijo(getattr(r, "stderr", None))).strip()


def lanzar_crudo(prompt, timeout_s, modelo=None, correr=None):
    """Lanza Claude Code y devuelve `(estado, salida, extra)`. **Nunca lanza una excepción.**

    `estado` es uno de: `"ok"` · `"codigo"` · `"timeout"` · `"sin_claude"` · `"error"`.
    `extra` trae `{"codigo": …}` en el fallo por código de salida.

    ⛔ **`timeout_s` NO tiene valor por defecto, a propósito.** Lo tuvo (600) y era **igual** al
    que le pasaba su único consumidor, así que quitar el argumento en la llamada daba
    exactamente lo mismo: la mutación que dejaba el pipeline **sin tope de tiempo** salía
    **CIEGA**. Un defecto que coincide con lo que manda quien llama esconde si el valor viaja.
    Sin defecto, omitirlo no compila el día que alguien lo omita.

    ⚠️ Devuelve lo crudo a propósito: quién lo llama decide qué es un éxito. El gate escribe una
    línea de bitácora; el pipeline quiere un JSON. Meter aquí esa decisión sería el criterio
    duplicado otra vez, al revés.
    """
    correr = correr or subprocess.run
    cmd = orden(prompt, modelo)
    try:
        r = correr(cmd, capture_output=True, text=True, encoding="utf-8",
                   errors="replace", timeout=timeout_s, env=entorno())
    except subprocess.TimeoutExpired as e:
        return "timeout", salida_de(e), {}
    except FileNotFoundError:
        return "sin_claude", u"no encuentro el ejecutable %r" % (cmd[0],), {}
    except Exception as e:  # ⛔ Nunca lanza: tumbaría la pasada entera.
        return "error", u"fallo al lanzar Claude Code: %s" % (e,), {}
    salida = salida_de(r)
    codigo = getattr(r, "returncode", 0)
    if codigo != 0:
        return "codigo", salida, {"codigo": codigo}
    return "ok", salida, {"codigo": 0}


if __name__ == "__main__":  # pragma: no cover
    print(u"Claude Code en local, en un solo sitio.")
    print(u"Ejecutable: %s" % ejecutable())
