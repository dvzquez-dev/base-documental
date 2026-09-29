#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""La capa que ejecuta lo que `pipeline.siguiente` decide. Seca por defecto.

Por qué el IO va inyectado
--------------------------
Este módulo **no importa una sola librería de Google**. Recibe un objeto `servicios` con las
funciones que tocan el mundo, y por eso el orden entero se puede probar sin credenciales, sin red
y sin escribir en la hoja de un equipo real.

⛔ Y no es comodidad de pruebas: es la regla que se aprendió por las malas. Un banco que habla con
el mundo **hace el daño que dice comprobar** — en este proyecto un banco subió un flag real a
producción y estuvo así tres semanas sin que nadie lo notara.

Por qué es seca por defecto
---------------------------
`aplicar=False` mientras nadie diga lo contrario. `SOLICITUDES` es la hoja de un pipeline en
marcha y **no hay deshacer**: si una pasada escribe mal 40 filas, se arreglan a mano una por una.
Una pasada seca dice exactamente qué haría, y eso se puede leer antes de soltarla.

Cómo se prueba
--------------
`python scripts/test_ejecutor.py` — sin red ni credenciales.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding="utf-8")
    except Exception:  # pragma: no cover
        pass

import evidencias as EV
import pipeline as P


# Qué función de `servicios` atiende cada acción, y qué banderas deja puestas al salir bien.
# ⚠️ Las acciones que NO están aquí son las que no se ejecutan por su cuenta: esperar una decisión,
#    esperar un reenvío, no hacer nada, y mirar a mano. Que no estén es la forma de que añadir una
#    acción nueva sin decidir qué la atiende falle en voz alta, en vez de no hacer nada callando.
ATIENDE = {
    P.ANALIZAR: ("analizar", ("analyzed",)),
    # ⛔⛔ SÓLO LA BANDERA QUE `servicios.publicar` HACE DE VERDAD (695.ª, 29/09).
    #    Aquí prometía las SIETE de publicación y el adaptador sólo crea la página de Notion:
    #    habría escrito «PDF embebido», «carpeta de Drive creada» y «permisos verificados» en
    #    TRUE **sin que nada de eso hubiera pasado**. Y con las siete puestas, `cierre` daría el
    #    expediente por publicado y lo cerraría: un documento **sin fichero en Drive**, marcado
    #    como cerrado, que **nadie vuelve a mirar**.
    #    ⚠️ Prometer de menos hace que el expediente se quede abierto y a la vista. Prometer de
    #    más lo entierra. No son simétricos.
    #    ✅ 29/09: entran las dos últimas. `drive_summary_created` porque el resumen ejecutivo
    #    ya se escribe como fichero en la carpeta — y va con prueba (`drive_summary_file_id`),
    #    así que si el expediente no trae resumen la bandera **no se pone** (ver `EV.con_prueba`).
    #    Y `drive_folder_created`, que no era una tarea: su propio código la define como «la
    #    publicación entera está completa», y `publicar` sólo vuelve si todo lo demás salió.
    P.PUBLICAR: ("publicar", ("notion_page_created", "notion_pdf_embedded",
                              "notion_embedding_verified", "drive_folder_created",
                              "drive_primary_file_verified", "drive_summary_created",
                              "domain_permission_verified")),
    P.REGISTRAR: ("registrar", ("base_database_registered",)),
    P.CERRAR: ("cerrar", ("closed",)),
}

# Las que se quedan quietas a propósito, cada una con por qué. Tenerlo escrito es lo que impide
# que alguien «complete» el mapa de arriba y ponga al pipeline a decidir cosas que no le tocan.
QUIETAS = {
    P.ESPERAR: u"la decisión es de una persona, desde la app",
    P.REENVIO: u"espera a que el autor reenvíe: no hay nada que hacer por él",
    P.NADA: u"ya está en regla",
    P.REVISAR: u"algo no cuadra y lo mira una persona",
}


class Resultado(object):
    """Lo que pasó con una fila. Se lee sin saber nada del módulo."""

    def __init__(self, n, request_id, accion, porque, hecho=False, seco=False,
                 banderas=(), error=None, extra=None):
        self.n = n
        self.request_id = request_id
        self.accion = accion
        self.porque = porque
        self.hecho = hecho
        self.seco = seco
        self.banderas = tuple(banderas)
        self.error = error
        # ⛔ Lo que el servicio DEVUELVE y hay que anotar: `notion_page_id`,
        #    `base_database_row`… No es información de adorno: es la PRUEBA de que el
        #    trabajo se hizo, y sin ella `evidencias` no puede impedir que la pasada
        #    siguiente cree una SEGUNDA página de Notion.
        self.extra = dict(extra or {})

    def __repr__(self):  # pragma: no cover
        estado = "error" if self.error else ("hecho" if self.hecho else
                                             ("seco" if self.seco else "quieta"))
        return "<%s fila %s %s %s>" % (estado, self.n, self.request_id, self.accion)


def ejecutar_una(fila, servicios, n=0, aplicar=False):
    """Hace lo que toque con UNA fila. Nunca lanza: un fallo se devuelve, no se propaga.

    ⛔ Que no lance es parte del diseño, no descuido. Una pasada recorre decenas de expedientes y
    que el número 3 reviente **no puede** dejar sin tocar los 40 siguientes: el modo de fallo sería
    «el pipeline va lento» cuando en realidad está parado.
    """
    rid = u"(sin request_id)"
    if isinstance(fila, dict):
        rid = str(fila.get("request_id") or "").strip() or rid

    accion, porque = P.siguiente(fila)

    # ⛔ ANOTAR no llama a nadie: el trabajo ya está hecho y lo único que falta es la marca.
    #    Por eso va ANTES del mapa de servicios y no tiene entrada en él: no hay nada que ejecutar,
    #    y darle un servicio sería invitar a que alguien lo hiciera dos veces.
    if accion == P.ANOTAR:
        banderas = EV.ya_hecho(fila)
        if not banderas:
            return Resultado(n, rid, accion, porque,
                             error=u"nada que anotar: la fila no trae ninguna prueba")
        if not aplicar:
            return Resultado(n, rid, accion, porque, seco=True, banderas=banderas)
        return Resultado(n, rid, accion, porque, hecho=True, banderas=banderas)

    if accion in QUIETAS:
        return Resultado(n, rid, accion, u"%s (%s)" % (porque, QUIETAS[accion]))

    if accion not in ATIENDE:
        # Una acción nueva que nadie atiende. Se dice en voz alta en vez de pasar por quieta.
        return Resultado(n, rid, accion, porque,
                         error=u"no hay quién atienda la acción %r" % accion)

    nombre, banderas = ATIENDE[accion]
    fn = getattr(servicios, nombre, None)
    if not callable(fn):
        return Resultado(n, rid, accion, porque,
                         error=u"`servicios.%s` no existe o no se puede llamar" % nombre)

    if not aplicar:
        return Resultado(n, rid, accion, porque, seco=True, banderas=banderas)

    try:
        _devuelto = fn(fila)
    # ⛔⛔ `SystemExit` VA AQUÍ EXPLÍCITAMENTE, y no es paranoia: es lo que lanza
    #    `servicios.analizar` cuando no puede hacer el análisis —a propósito, para no dar por
    #    analizado lo que no lo está—, y cuelga de `BaseException`, así que un `except Exception`
    #    **no lo caza**. Con él fuera, la promesa de arriba («nunca lanza») era falsa justo en el
    #    único sitio donde hoy se usa: la pasada moría en ese expediente y los 40 siguientes se
    #    quedaban sin tocar, con pinta de «el pipeline va lento» cuando está parado.
    #    ⚠️ Misma familia que el `bajar` que prometía «no lanza NUNCA» con un `except Exception`
    #    mientras `cli` lanzaba `SystemExit`.
    # ⚠️ Y `KeyboardInterrupt` NO entra: si alguien corta la pasada a mano, tragárselo la dejaría
    #    corriendo sin forma de pararla. No todo `BaseException` se trata igual.
    except (Exception, SystemExit) as e:
        return Resultado(n, rid, accion, porque,
                         error=u"%s: %s" % (type(e).__name__, e))

    # ⛔ Y la promesa se contrasta con la PRUEBA. `ATIENDE` es una lista escrita a mano, y una
    #    lista escrita a mano envejece: el día que el servicio deje de hacer algo, la promesa
    #    sigue ahí. Lo que decide es el identificador que el servicio devuelve.
    #    ⚠️ Sólo al APLICAR: en seco no hay servicio que haya devuelto nada, y filtrar ahí
    #       dejaría la pasada seca enseñando de menos justo cuando se lee para decidir.
    _extra = _devuelto if isinstance(_devuelto, dict) else {}
    return Resultado(n, rid, accion, porque, hecho=True,
                     banderas=EV.con_prueba(banderas, fila, _extra), extra=_extra or None)


def pasada(filas, servicios, aplicar=False):
    """Recorre las filas y devuelve un `Resultado` por cada una, en el mismo orden.

    ⚠️ Devuelve **uno por fila**, también por las que no hacen nada. Un informe que sólo trae lo
    que se tocó no deja distinguir «no había nada que hacer» de «esta fila ni se miró».
    """
    return [ejecutar_una(f, servicios, n=i + 2, aplicar=aplicar)
            for i, f in enumerate(filas)]


def resumen(resultados):
    """`(hechas, secas, quietas, errores)`. Los cuatro suman siempre el total."""
    hechas = sum(1 for r in resultados if r.hecho)
    secas = sum(1 for r in resultados if r.seco)
    errores = sum(1 for r in resultados if r.error)
    quietas = len(resultados) - hechas - secas - errores
    return hechas, secas, quietas, errores


if __name__ == "__main__":  # pragma: no cover
    print("Ejecutor con IO inyectado. Para probarlo: python scripts/test_ejecutor.py")
