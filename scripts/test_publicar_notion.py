#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Banco de `publicar_notion.py`. Sin red, sin credenciales, sin reloj.

⛔ Las tres listas de opciones se comprueban **por igualdad contra un literal medido**, nunca
iterando la constante que se está probando. Esta misma noche un banco iteró `DECIDIDOS` — la
constante bajo prueba — y al vaciarla las comprobaciones **desaparecieron** (55 → 50) con el
banco en verde. Una comprobación que se borra sola cuando el fallo ocurre no es una comprobación.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding="utf-8")
    except Exception:
        pass

import publicar_notion as PN

fallos = []
hechas = [0]


def ok(cond, que):
    hechas[0] += 1
    if not cond:
        fallos.append(que)


def base(**kw):
    """Un expediente que pasa entero. Cada caso rompe UNA cosa."""
    d = {"title_short": "Informe de ensayo estático", "unit_key": "propulsion",
         "document_type": "Informe", "season_label": "2026/27",
         "reference": "Informe_S-4012_27"}
    d.update(kw)
    return d


# ── 1. Las listas, contra lo medido del esquema vivo el 29/09/2026 ──────────────────────────
# 📏 Salen de `one of [...]` del esquema de la base «Documentos internos»
#    (11eb0e3a-469c-80b9-969f-f0d0e88e2f36). Si Notion cambia, este banco se pone rojo, que es
#    exactamente lo que tiene que pasar: la traducción dejaría de ser cierta.
UNIDADES_MEDIDAS = ("Solaris", "Subsistema de Propulsión", "Subsistema de Estructuras&Aerodinámica",
                    "Subsistema de Dinámica&Control", "Subsistema de Electrónica",
                    "Unidad de Coordinación Técnica", "Unidad de Recovery",
                    "Unidad de Seguridad y Verificación",
                    "Unidad de Patrocinios y Relaciones Externas", "Unidad de Logística")

ok(PN.TIPOS_NOTION == ("txt", "Cuestionario", "Carpeta", "Informe", "Imagen", "Tabla", "Pieza",
                       "Simulación", "Manual", "SinTipo", "Informe de Subsistema", "Memoria",
                       "Acta"),
   "TIPOS_NOTION no es la lista medida del esquema vivo")
ok(PN.TEMPORADAS_NOTION == ("2024/25", "2025/26", "2026/27"),
   "TEMPORADAS_NOTION no es la lista medida")

# ⛔ Toda unidad traducida tiene que ser una opción que Notion REALMENTE tiene. Si no, la API no
#    da error: **crea una opción nueva** y parte la base en dos sin que nadie se entere.
for clave, opcion in sorted(PN.UNIDAD_NOTION.items()):
    ok(opcion in UNIDADES_MEDIDAS,
       "la unidad %r traduce a %r, que NO es una opción de Notion" % (clave, opcion))

# ── 2. Las 9 `unit_key`, contra lo medido de la pestaña RUTAS ───────────────────────────────
# 📏 Leídas de `RUTAS` (hoja 1EL5luW…, worksheetId 1506532352) el 29/09/2026: 18 filas, 9 claves.
CLAVES_RUTAS = ("dinamica_control", "electronica", "estructuras_aerodinamica", "logistica",
                "patrocinios_relaciones_externas", "propulsion", "recovery",
                "seguridad_verificacion", "uct")
ok(tuple(sorted(PN.UNIDAD_NOTION)) == CLAVES_RUTAS,
   "UNIDAD_NOTION no cubre exactamente las 9 unit_key de RUTAS")

ok(PN.unidad_de("propulsion") == "Subsistema de Propulsión", "propulsion mal traducida")
ok(PN.unidad_de("uct") == "Unidad de Coordinación Técnica", "uct mal traducida")
ok(PN.unidad_de("electronica") == "Subsistema de Electrónica", "electronica mal traducida")
ok(PN.unidad_de("estructuras_aerodinamica") == "Subsistema de Estructuras&Aerodinámica",
   "estructuras_aerodinamica mal traducida")
ok(PN.unidad_de("dinamica_control") == "Subsistema de Dinámica&Control",
   "dinamica_control mal traducida")
ok(PN.unidad_de("logistica") == "Unidad de Logística", "logistica mal traducida")
ok(PN.unidad_de("recovery") == "Unidad de Recovery", "recovery mal traducida")
ok(PN.unidad_de("seguridad_verificacion") == "Unidad de Seguridad y Verificación",
   "seguridad_verificacion mal traducida")
ok(PN.unidad_de("patrocinios_relaciones_externas") == "Unidad de Patrocinios y Relaciones Externas",
   "patrocinios mal traducida")

# ⚠️ «Solaris» es opción de Notion pero NO hay ninguna ruta que lleve a ella: no se alcanza desde
#    el formulario. Se comprueba para que, si algún día aparece una ruta general, esto se ponga
#    rojo y alguien decida a conciencia, en vez de que la unidad caiga en `None` calladamente.
ok("Solaris" not in PN.UNIDAD_NOTION.values(),
   "alguna unit_key traduce a Solaris: RUTAS no tiene ruta general, revisar")

ok(PN.unidad_de("avionica") is None, "una unidad inventada debería dar None")
ok(PN.unidad_de("GNC") is None, "el nombre nuevo del equipo no es una unit_key")
ok(PN.unidad_de(None) is None, "None debería dar None")
ok(PN.unidad_de("") is None, "la cadena vacía debería dar None")
ok(PN.unidad_de("  propulsion  ") == "Subsistema de Propulsión", "no recorta espacios")

# ── 3. Tipo ────────────────────────────────────────────────────────────────────────────────
# ⛔ `Acta` fue durante meses el tipo que NO existía en Notion, y por eso Cowork mandaba cada
#    acta a intervención manual. Se midió el 29/09 y **ya existe**. Esta comprobación es la que
#    impide que esa creencia vuelva a colarse.
ok(PN.tipo_de("Acta") == "Acta", "Acta debería ser un tipo válido: se midió que ya existe")
ok(PN.tipo_de("Informe") == "Informe", "Informe debería valer")
ok(PN.tipo_de("Informe de Subsistema") == "Informe de Subsistema", "el tipo con espacios falla")
ok(PN.tipo_de("Simulación") == "Simulación", "el tipo con tilde falla")
ok(PN.tipo_de("  Tabla  ") == "Tabla", "no recorta espacios en el tipo")
ok(PN.tipo_de("Memoria") == "Memoria", "Memoria debería valer")
ok(PN.tipo_de("acta") is None, "el tipo distingue mayúsculas: Notion también")
ok(PN.tipo_de("Presupuesto") is None, "un tipo inventado debería dar None")
ok(PN.tipo_de(None) is None, "None debería dar None")
# ⚠️ El que más importa: NO caer a SinTipo por su cuenta.
ok(PN.tipo_de("Presupuesto") != "SinTipo",
   "un tipo desconocido cae a SinTipo: eso convierte «no lo reconozco» en un dato")

# ── 4. Temporada ───────────────────────────────────────────────────────────────────────────
ok(PN.temporada_de("2026/27") == "2026/27", "la temporada en curso debería valer")
ok(PN.temporada_de("2025/26") == "2025/26", "la temporada pasada debería valer")
ok(PN.temporada_de("2027/28") is None,
   "2027/28 aún no existe en la base: debe avisar, no inventarla")
ok(PN.temporada_de("2026-27") is None, "con guion no es el formato de Notion")
ok(PN.temporada_de("26/27") is None, "la forma corta no es la de Notion")
ok(PN.temporada_de(None) is None, "None debería dar None")

# ── 5. El número de la referencia ──────────────────────────────────────────────────────────
ok(PN.id_de_referencia("Informe_S-4012_27") == 4012, "no saca el número de una referencia buena")
ok(PN.id_de_referencia("Acta_S-6301_27") == 6301, "no saca el número de un acta")
ok(PN.id_de_referencia("Simulación_S-1001_27") == 1001, "el prefijo con tilde rompe la referencia")
ok(PN.id_de_referencia("Informe de Subsistema_S-4001_27") is None,
   "un prefijo con espacios NO es canónico: la referencia lleva el tipo sin espacios")
ok(PN.id_de_referencia("Informe_S-401_27") == 401, "una referencia de 3 cifras debería valer")
ok(PN.id_de_referencia("Informe_S-4012_2027") is None, "el sufijo son DOS cifras, no cuatro")
ok(PN.id_de_referencia("Informe-S-4012_27") is None, "el separador es guion bajo")
ok(PN.id_de_referencia("") is None, "la cadena vacía no es referencia")
ok(PN.id_de_referencia(None) is None, "None no es referencia")
# ⛔ El cero a la izquierda: `int()` lo come, y la página quedaría con un número que no es el
#    que lleva impreso el documento.
ok(PN.id_de_referencia("Informe_S-0412_27") == 412,
   "un cero a la izquierda debería dar el entero 412")

# ── 6. El expediente entero ────────────────────────────────────────────────────────────────
props, motivos = PN.propiedades(base())
ok(motivos == [], "un expediente completo no debería dar motivos: %r" % (motivos,))
ok(props is not None, "un expediente completo debería dar propiedades")
ok(props.get("Título") == "Informe de ensayo estático", "el título no viaja")
ok(props.get("ID (XXXX)") == 4012, "el ID no viaja")
ok(props.get("Subsistema o Unidad") == "Subsistema de Propulsión", "la unidad no viaja")
ok(props.get("Tipo Aerotech") == "Informe", "el tipo no viaja")
ok(props.get("Temporada") == "2026/27", "la temporada no viaja")
ok("Etiquetas" not in props, "sin etiquetas no debería crearse la propiedad")
ok(sorted(props) == ["ID (XXXX)", "Subsistema o Unidad", "Temporada", "Tipo Aerotech", "Título"],
   "las propiedades no son exactamente las cinco esperadas: %r" % (sorted(props),))

props2, _ = PN.propiedades(base(tags=["ensayo", "  motor  ", "", None]))
ok(props2.get("Etiquetas") == ["ensayo", "motor"],
   "las etiquetas no se limpian: %r" % (props2.get("Etiquetas"),))

# ⛔ Cada fallo por separado: que dé motivos NO basta, porque el motivo podría venir del vecino.
#    Se comprueba QUÉ motivo salta.
for campo, valor, trozo in (
        ("title_short", "", "sin título"),
        ("unit_key", "avionica", "no tiene opción en Notion"),
        ("document_type", "Presupuesto", "Tipo Aerotech"),
        ("season_label", "2027/28", "no existe en la base"),
        ("reference", "chusta", "no es canónica")):
    p, m = PN.propiedades(base(**{campo: valor}))
    ok(p is None, "con %s malo no debería devolver propiedades" % campo)
    ok(len(m) == 1, "con %s malo debería haber UN motivo, hay %d: %r" % (campo, len(m), m))
    ok(m and trozo in m[0], "el motivo de %s no explica la causa: %r" % (campo, m))

# Y varios a la vez se acumulan: no se para en el primero.
p, m = PN.propiedades({"title_short": "", "unit_key": "x", "document_type": "y",
                       "season_label": "z", "reference": "w"})
ok(p is None, "con todo malo no debería devolver propiedades")
ok(len(m) == 5, "con los cinco campos malos deberían salir 5 motivos, salen %d" % len(m))

# Un expediente vacío no revienta.
p, m = PN.propiedades({})
ok(p is None and len(m) == 5, "un expediente vacío debería dar 5 motivos sin reventar")

print("%d comprobaciones" % hechas[0])
if fallos:
    print("\n%d ROJO(S):" % len(fallos))
    for f in fallos:
        print("  - %s" % f)
    sys.exit(1)
print("verde")
