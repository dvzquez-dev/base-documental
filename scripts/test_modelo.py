#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Banco de `modelo.py`. Sin red, sin credenciales, sin lanzar un solo proceso.

⛔ Lo que se prueba aquí es **cómo se llama a Claude Code**, no qué contesta. Las cuatro
trampas que cubre están **medidas en Windows** por `rutinas/gate.py` del panel (`lanzar`, y su
banco `probar_gate_lanzar.py`), y las cuatro fallan **callando**:

1. `claude` a secas no se resuelve desde una **tarea programada**, que no hereda el `PATH`.
2. El hijo con la salida redirigida escribe en la **página de códigos local**: sin
   `PYTHONIOENCODING` los acentos llegan como `U+FFFD` y el `errors="replace"` lo hace en
   silencio. Y `env=` **sustituye** el entorno: pasar sólo la variable nueva deja al hijo sin
   `PATH` ni `SystemRoot`.
3. Al saltar el tope de tiempo, lo que dijo el hijo vive en `TimeoutExpired.stdout`, y tirarlo
   deja **el caso más difícil de diagnosticar como el único sin ninguna pista**.
4. Una sesión **caducada no falla: se queda esperando** — llega al timeout, no a un
   `returncode != 0`. Buscar las pistas sólo en la rama del código de salida es no buscarlas
   donde de verdad aparecen.

⚠️ El lanzador se inyecta (`correr=`), así que este banco **no arranca ningún proceso**.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding="utf-8")
    except Exception:
        pass

import modelo as M

fallos = []
hechas = [0]


def ok(cond, que):
    hechas[0] += 1
    if not cond:
        fallos.append(que)


class Hijo(object):
    """Lo que devuelve `subprocess.run`, con lo justo."""

    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def correr_que(resultado):
    """Un lanzador de mentira que apunta con qué lo llamaron."""
    visto = {}

    def correr(cmd, **kw):
        visto["cmd"] = list(cmd)
        visto["kw"] = dict(kw)
        if isinstance(resultado, Exception):
            raise resultado
        return resultado

    return correr, visto


BUENA = json.dumps({"resumen": u"Memoria técnica de la aviónica de EuRoC.",
                    "etiquetas": ["aviónica", "EuRoC"]}, ensure_ascii=False)


# ── 1. El ejecutable: ruta ABSOLUTA, no `claude` a secas ───────────────────────────────────
_exe = M.ejecutable()
ok(isinstance(_exe, str) and _exe, u"`ejecutable()` no devuelve nada")
# ⛔ Si el `claude.exe` del usuario existe, HAY que usarlo: una tarea programada no hereda el
#    PATH de la terminal, y `claude` a secas sale como «no encuentro el ejecutable».
_esperado = os.path.join(os.path.expanduser("~"), ".local", "bin", "claude.exe")
if os.path.exists(_esperado):
    ok(_exe == _esperado,
       u"⛔ no usa la ruta absoluta de `claude.exe` (%r): desde una tarea programada no se "
       u"resuelve y la rutina falla con «no encuentro el ejecutable»" % (_exe,))
else:
    ok(_exe == "claude", u"sin el .exe, el respaldo es el PATH: %r" % (_exe,))

# ⛔⛔ Y en LINUX el binario se llama `claude`, sin `.exe`. El destino declarado por Daniel es
#    **un minipc**, que puede ser Linux; mirando sólo el `.exe` la función se cae al respaldo del
#    `PATH`, que es justo lo que un `cron` o un `systemd` NO heredan. O sea: la protección se
#    desactivaba sola **en la máquina para la que se escribió**, y sin dar ningún error.
_casa = tempfile.mkdtemp()
_bin = os.path.join(_casa, ".local", "bin")
os.makedirs(_bin)
_orig_expand = os.path.expanduser
try:
    os.path.expanduser = lambda p: _casa if p == "~" else _orig_expand(p)
    ok(M.ejecutable() == "claude",
       u"sin ningún binario en ~/.local/bin, el respaldo es el PATH: %r" % (M.ejecutable(),))
    _linux = os.path.join(_bin, "claude")
    open(_linux, "w").close()
    ok(M.ejecutable() == _linux,
       u"⛔⛔ en Linux el binario se llama `claude` (sin .exe) y NO lo encuentra (%r): se cae al "
       u"PATH, que un cron no hereda — la protección se desactiva sola justo en el minipc"
       % (M.ejecutable(),))
    _win = os.path.join(_bin, "claude.exe")
    open(_win, "w").close()
    ok(M.ejecutable() == _win, u"con los dos, gana el .exe (es donde corre hoy): %r"
       % (M.ejecutable(),))
    # ⚠️ Un DIRECTORIO llamado `claude` no es un ejecutable: con `os.path.exists` colaría.
    os.remove(_win)
    os.remove(_linux)
    os.makedirs(os.path.join(_bin, "claude"))
    ok(M.ejecutable() == "claude",
       u"⛔ toma un DIRECTORIO por el ejecutable: %r" % (M.ejecutable(),))
finally:
    os.path.expanduser = _orig_expand
    shutil.rmtree(_casa, ignore_errors=True)

# ── 2. La orden ────────────────────────────────────────────────────────────────────────────
_o = M.orden(u"dime algo", modelo="sonnet")
ok(_o[0] == M.ejecutable(), u"la orden no empieza por el ejecutable: %r" % (_o,))
ok("-p" in _o, u"⛔ falta `-p`: sin él `claude` abre una sesión interactiva y se cuelga")
ok("--model" in _o and _o[_o.index("--model") + 1] == "sonnet",
   u"el modelo no viaja en la orden: %r" % (_o,))
ok(_o[-1] == u"dime algo", u"el prompt va el último y entero: %r" % (_o[-1:],))
# ⚠️ Sin modelo no se inventa uno: que lo decida la configuración de Claude Code.
ok("--model" not in M.orden(u"x"), u"⛔ mete un `--model` que nadie pidió: %r" % (M.orden(u"x"),))
ok(M.orden(u"x")[-1] == u"x", u"sin modelo, el prompt sigue siendo el último")

# ── 3. El entorno ──────────────────────────────────────────────────────────────────────────
_e = M.entorno()
ok(_e.get("PYTHONIOENCODING") == "utf-8",
   u"⛔ sin `PYTHONIOENCODING` los acentos del hijo llegan como U+FFFD, y en silencio")
# ⛔⛔ `env=` SUSTITUYE el entorno. Con sólo la variable nueva el hijo se queda sin `PATH` ni
#    `SystemRoot`, y en Windows eso rompe el arranque — el fallo saldría como «la rutina no
#    arranca» y mandaría a mirar la rutina, no el entorno.
ok(len(_e) > 1, u"⛔ `entorno()` devuelve SÓLO la variable nueva: eso deja al hijo sin PATH")
for _v in ("PATH", "Path"):
    if _v in os.environ:
        ok(_e.get(_v) == os.environ[_v], u"⛔ `entorno()` no conserva %s del proceso" % _v)
        break
else:
    ok(True, u"(sin PATH en este entorno, nada que conservar)")
ok(M.entorno() is not os.environ, u"`entorno()` no debería devolver el propio `os.environ`")

# ── 4. La pasada buena ─────────────────────────────────────────────────────────────────────
_c, _v = correr_que(Hijo(0, BUENA))
r = M.preguntar(u"analiza esto", correr=_c)
ok(r["ok"] is True, u"una pasada buena no sale ok: %r" % (r,))
ok(r["datos"]["resumen"].startswith(u"Memoria técnica"),
   u"no devuelve lo que contestó el modelo: %r" % (r.get("datos"),))
ok(r["sesion_caducada"] is False, u"una pasada buena no es una sesión caducada")
ok(_v["kw"].get("timeout"), u"⛔ se lanza SIN tope de tiempo: un cuelgue para el pipeline entero")
ok(_v["kw"].get("env", {}).get("PYTHONIOENCODING") == "utf-8",
   u"⛔ el entorno con la codificación no llega a `subprocess`: %r" % (_v["kw"].get("env"),))
ok(_v["kw"].get("encoding") == "utf-8", u"no lee la salida como utf-8: %r" % (_v["kw"],))
ok(_v["kw"].get("capture_output") is True, u"⛔ sin capturar la salida no hay diagnóstico")
ok(_v["cmd"][-1] == u"analiza esto", u"el prompt no llega al proceso: %r" % (_v["cmd"][-1:],))

# ── 5. Lo que contesta el modelo, leído sin fiarse ─────────────────────────────────────────
# ⚠️ Claude Code escribe prosa alrededor del JSON más veces de las que uno quiere. Se busca el
#    objeto, no se hace `json.loads` de la salida entera.
_c, _ = correr_que(Hijo(0, u"Claro, aquí tienes:\n```json\n" + BUENA + u"\n```\nEspero que sirva."))
r = M.preguntar(u"x", correr=_c)
ok(r["ok"] is True and r["datos"].get("etiquetas") == ["aviónica", "EuRoC"],
   u"⛔ no encuentra el JSON entre la prosa: %r" % (r,))
# ⛔ Y una salida SIN JSON no se inventa: se dice que no se pudo leer.
_c, _ = correr_que(Hijo(0, u"No he podido analizar el documento."))
r = M.preguntar(u"x", correr=_c)
ok(r["ok"] is False, u"⛔ da por bueno un análisis que no trae datos: %r" % (r,))
ok("json" in (r.get("motivo") or "").lower(),
   u"el motivo no dice que el problema fue leer la respuesta: %r" % (r.get("motivo"),))
# ⛔ Un JSON que no es un objeto tampoco vale: `datos["resumen"]` reventaría más abajo.
_c, _ = correr_que(Hijo(0, u'["a", "b"]'))
ok(M.preguntar(u"x", correr=_c)["ok"] is False,
   u"⛔ acepta una lista como si fuera el objeto del análisis")
# ⚠️ La salida entera se conserva pase lo que pase: es lo único que se lee cuando algo falla.
ok(M.preguntar(u"x", correr=_c).get("salida"), u"no conserva la salida del hijo")

# ── 6. El código de salida ─────────────────────────────────────────────────────────────────
_c, _ = correr_que(Hijo(2, u"", u"boom"))
r = M.preguntar(u"x", correr=_c)
ok(r["ok"] is False and r["codigo"] == 2, u"un código != 0 no se refleja: %r" % (r,))
ok("boom" in (r.get("salida") or ""), u"⛔ se pierde lo que dijo `stderr`: %r" % (r.get("salida"),))
ok(r["sesion_caducada"] is False, u"un fallo cualquiera no es una sesión caducada")

# ── 7. La sesión caducada, en LAS DOS ramas ────────────────────────────────────────────────
# ⛔ Es el fallo que más cuesta: la rutina «corre» y no hace nada.
_c, _ = correr_que(Hijo(1, u"", u"Invalid API key · Please run /login"))
r = M.preguntar(u"x", correr=_c)
ok(r["sesion_caducada"] is True,
   u"⛔ no reconoce la sesión caducada por el código de salida: %r" % (r,))
ok("sesión" in (r.get("motivo") or "").lower() or "login" in (r.get("motivo") or "").lower(),
   u"el motivo no dice QUÉ HACER (volver a iniciar sesión): %r" % (r.get("motivo"),))
# ⛔⛔ Y ÉSTA es la que se olvida: una sesión atascada en el login **no falla, espera**. Llega
#    al timeout, no al `returncode != 0`. Si la pista sólo se busca arriba, la única frase que
#    dice qué hacer no sale justo cuando es la causa.
_t = subprocess.TimeoutExpired(["claude"], 60)
_t.stdout = u"Please log in to continue"
_t.stderr = u""
_c, _ = correr_que(_t)
r = M.preguntar(u"x", correr=_c)
ok(r["ok"] is False and r["codigo"] == "timeout", u"el timeout no se refleja: %r" % (r,))
ok(r["sesion_caducada"] is True,
   u"⛔⛔ una sesión caducada que se queda ESPERANDO no se reconoce: es la rama donde de "
   u"verdad aparece, y sin ella el aviso no dice que hay que volver a iniciar sesión")
# ⛔ Y la salida del hijo NO se tira en esta rama: es el caso más difícil de diagnosticar.
ok("Please log in" in (r.get("salida") or ""),
   u"⛔ tira `TimeoutExpired.stdout`: el caso más difícil se queda sin ninguna pista: %r"
   % (r.get("salida"),))
ok("min" in (r.get("motivo") or "") or "tiempo" in (r.get("motivo") or "").lower(),
   u"el motivo del timeout no dice que se cortó por tiempo: %r" % (r.get("motivo"),))
# ⚠️ Un timeout SIN nada capturado no revienta al leer `None`.
_t2 = subprocess.TimeoutExpired(["claude"], 60)
_c, _ = correr_que(_t2)
r = M.preguntar(u"x", correr=_c)
ok(r["ok"] is False and r["sesion_caducada"] is False,
   u"un timeout sin salida no debería reventar ni inventarse una sesión caducada: %r" % (r,))
# ⚠️ Y en bytes: `TimeoutExpired` se rellena por un camino que NO decodifica.
_t3 = subprocess.TimeoutExpired(["claude"], 60)
_t3.stdout = b"please log in"
_c, _ = correr_que(_t3)
ok(M.preguntar(u"x", correr=_c)["sesion_caducada"] is True,
   u"⛔ con la salida en BYTES no reconoce la sesión caducada")

# ── 8. Que no exista el ejecutable ─────────────────────────────────────────────────────────
_c, _ = correr_que(FileNotFoundError("claude"))
r = M.preguntar(u"x", correr=_c)
ok(r["ok"] is False and r["codigo"] == "sin_claude",
   u"⛔ sin Claude Code instalado no lo dice con claridad: %r" % (r,))
ok("Claude Code" in (r.get("motivo") or ""),
   u"el motivo no nombra lo que falta: %r" % (r.get("motivo"),))
# ⚠️ Nunca lanza: el pipeline tiene que poder seguir con los expedientes que no dependan de esto.
try:
    M.preguntar(u"x", correr=correr_que(RuntimeError("cualquier cosa"))[0])
    _lanzo = False
except Exception:
    _lanzo = True
ok(_lanzo is False, u"⛔ `preguntar` lanza: un fallo del modelo tumbaría la pasada entera")

# ── 9. Que la copia del lanzador NO haya divergido ─────────────────────────────────────────
# ⛔ `claude_local.py` es **el mismo fichero** que `rutinas/claude_local.py` del panel: los dos
#    repositorios lo necesitan y Daniel cortó la segunda copia en cuanto la vio. Copiar es lo
#    único que se puede hacer entre dos repos, pero una copia que nadie compara **deja de ser
#    una copia** en cuanto alguien arregla un lado — y eso no da ningún síntoma.
_AQUI = os.path.join(os.path.dirname(os.path.abspath(__file__)), "claude_local.py")
ok(os.path.exists(_AQUI), u"⛔ falta `claude_local.py`: el lanzador no está copiado")
# ⚠️ Se mira también en los worktrees: el panel trabaja en ramas, y buscar sólo en la copia
#    principal deja la comprobación muda justo mientras se está tocando el fichero — que es
#    cuando hace falta.
_RAIZ = os.path.join(os.path.expanduser("~"), "Desktop", "Sanciones Solaris")
_CANDIDATOS = [os.path.join(_RAIZ, "rutinas", "claude_local.py")]
_WT = os.path.join(_RAIZ, ".claude", "worktrees")
if os.path.isdir(_WT):
    for _d in sorted(os.listdir(_WT)):
        _CANDIDATOS.append(os.path.join(_WT, _d, "rutinas", "claude_local.py"))
_PANEL = next((c for c in _CANDIDATOS if os.path.exists(c)), _CANDIDATOS[0])
if os.path.exists(_PANEL):
    import hashlib

    def _huella(p):
        """⛔ Los finales de línea se NORMALIZAN antes de comparar.

        Los dos repositorios tienen `core.autocrlf` distinto: el panel guarda LF y aquí git
        avisa de que los convertirá a CRLF en el próximo checkout. Comparando bytes, esta
        comprobación se pondría **roja sobre dos ficheros idénticos**, en cuanto alguien
        clonara el repo — y un guardia que regaña por trabajo bien hecho se acaba apagando,
        y con él se pierde lo que sí vigilaba. Lo que importa es el contenido.
        """
        with open(p, "rb") as f:
            crudo = f.read()
        return hashlib.sha256(crudo.replace(b"\r\n", b"\n")).hexdigest()

    ok(_huella(_AQUI) == _huella(_PANEL),
       u"⛔⛔ la copia de `claude_local.py` HA DIVERGIDO de la del panel (%s):\n"
       u"     vuelve a copiarla, o el arreglo de un lado no llega al otro y nadie se entera"
       % (_PANEL,))
else:
    # ⚠️ Se dice en voz alta: una comprobación que no puede correr y calla se lee igual que una
    #    que pasó. En CI o en el minipc sin el panel al lado, esto es lo normal.
    print(u"  (no está el panel en %s: no se puede comparar la copia)" % _PANEL)
    ok(True, u"(sin panel, nada que comparar)")

print("%d comprobaciones" % hechas[0])
if fallos:
    print("\n%d ROJO(S):" % len(fallos))
    for f_ in fallos:
        print("  - %s" % f_)
    sys.exit(1)
print("verde")
