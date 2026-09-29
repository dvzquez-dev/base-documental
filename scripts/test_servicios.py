#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Banco de `servicios.py` — las manos. **No abre una sola conexión.**

⛔ Todo el transporte va doblado: un banco que hable con Sheets o con Notion **hace el daño que
dice vigilar**, y en este proyecto ya pasó (un banco subió un flag real a producción y estuvo
tres semanas así). Lo que se comprueba aquí es **qué se le pide al mundo**, no el mundo.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding="utf-8")
    except Exception:
        pass

import servicios as S

fallos = []
hechas = [0]


def ok(cond, que):
    hechas[0] += 1
    if not cond:
        fallos.append(que)


# ── Los dobles: apuntan lo que se les pide, y nada sale de la máquina ──────────────────────
class _Ejec(object):
    def __init__(self, resp):
        self._r = resp

    def execute(self):
        return self._r


class _Valores(object):
    def __init__(self, diario, resp):
        self.diario = diario
        self.resp = resp

    def get(self, **kw):
        self.diario.append(("get", kw))
        return _Ejec(self.resp.get("get", {}))

    def batchGet(self, **kw):
        self.diario.append(("batchGet", kw))
        return _Ejec(self.resp.get("batchGet", {}))

    def batchUpdate(self, **kw):
        self.diario.append(("batchUpdate", kw))
        return _Ejec(self.resp.get("batchUpdate", {}))

    def append(self, **kw):
        self.diario.append(("append", kw))
        return _Ejec(self.resp.get("append", {}))


class _Hojas(object):
    def __init__(self, diario, resp):
        self._v = _Valores(diario, resp)

    def values(self):
        return self._v


class Sheets(object):
    def __init__(self, resp=None):
        self.diario = []
        self._h = _Hojas(self.diario, resp or {})

    def spreadsheets(self):
        return self._h


# ── 1. Los secretos NO salen por pantalla ──────────────────────────────────────────────────
# ⛔ Un token en una traza acaba en el registro de una acción de GitHub, y un secreto que se ha
#    visto una vez hay que rotarlo.
for crudo in (u"Bearer ntn_abc123", u"secret_XYZ", u'{"private_key": "-----BEGIN"}',
              u"ya29.a0AfB_x"):
    ok(u"███" in S.sin_secretos(crudo),
       u"⛔ %r no se tacha al salir por pantalla" % crudo)
ok(S.sin_secretos(u"no se pudo leer la fila 4") == u"no se pudo leer la fila 4",
   u"un mensaje normal no debería tacharse: un aviso ilegible se deja de leer")
ok(S.sin_secretos(None) == u"", u"None no debería reventar")

# ── 2. Las constantes, contra lo medido ────────────────────────────────────────────────────
ok(S.HOJA_SOLICITUDES == "1EL5luWUYD5_3onxaDUSHmexzzQZEkPNLW1Y4QzzRg20",
   u"la hoja de SOLICITUDES ya no es la medida")
ok(S.PESTANA_LIBRO == "Base de Datos",
   u"la pestaña del Libro ya no es la medida (lleva espacios: por eso se entrecomilla)")
# ⚠️ Drive entero además de Sheets: hay que CREAR la carpeta del expediente. Es el mismo par
#    que ya piden `publish_temp_pdfs.py` y `fix_docx_publication_date.py` — no se inventa un
#    alcance nuevo, que es como se acaba pidiendo más permiso del que hace falta.
ok(S.ALCANCES == ["https://www.googleapis.com/auth/drive",
                  "https://www.googleapis.com/auth/spreadsheets"],
   u"el alcance de Google ya no es el del repo")
ok("readonly" not in " ".join(S.ALCANCES),
   u"con `drive.readonly` no se puede crear la carpeta, y el fallo llegaría en producción")

# ── 3. Leer ────────────────────────────────────────────────────────────────────────────────
sh = Sheets({"get": {"values": [["request_id"], ["R-1"]]}})
srv = S.Servicios(sheets=sh)
ok(srv.leer() == [["request_id"], ["R-1"]], u"`leer` no devuelve los valores crudos")
ok(sh.diario[0][1]["range"] == "SOLICITUDES!A1:BZ",
   u"`leer` no pide el rango medido: %r" % (sh.diario[0][1],))
ok(sh.diario[0][1]["spreadsheetId"] == S.HOJA_SOLICITUDES, u"`leer` pide otra hoja")

# ⛔ El Libro se pide CON LA PESTAÑA ENTRECOMILLADA: «Base de Datos» lleva espacios y sin
#    comillas el rango no es válido — la lectura se pierde entera.
sh = Sheets({"get": {"values": [["Título", "Ubic", "Claves"], ["Informe_S-1_27", "x", "y"]]}})
srv = S.Servicios(sheets=sh)
filas = srv.leer_libro()
ok(filas == [["Informe_S-1_27", "x", "y"]],
   u"`leer_libro` no quita la cabecera (es lo que espera `libro_datos`): %r" % (filas,))
ok(sh.diario[0][1]["range"].startswith(u"'Base de Datos'!"),
   u"⛔ el rango del Libro va sin comillas: %r" % (sh.diario[0][1]["range"],))

# ── 4. Releer ──────────────────────────────────────────────────────────────────────────────
sh = Sheets({"batchGet": {"valueRanges": [{"values": [["TRUE"]]}, {"values": [[""]]}]}})
srv = S.Servicios(sheets=sh)
leidas = srv.releer(["AW2", "BX2"])
ok(leidas == {"AW2": "TRUE", "BX2": ""}, u"`releer` no devuelve el mapa esperado: %r" % (leidas,))
ok(sh.diario[0][1]["ranges"] == ["SOLICITUDES!AW2", "SOLICITUDES!BX2"],
   u"`releer` no pide los rangos de esas celdas: %r" % (sh.diario[0][1],))
# Sin claves no se molesta a nadie.
sh = Sheets({})
ok(S.Servicios(sheets=sh).releer([]) == {} and sh.diario == [],
   u"releer sin claves no debería llamar al mundo")
# Una celda inválida no se pide: `sheets_api` ya dijo que no es una celda de datos.
sh = Sheets({"batchGet": {"valueRanges": [{"values": [["x"]]}]}})
S.Servicios(sheets=sh).releer(["A1"])
ok(sh.diario == [], u"⛔ se pide releer la CABECERA: `A1` no es una celda de datos")

# ── 5. Escribir ────────────────────────────────────────────────────────────────────────────
sh = Sheets({})
S.Servicios(sheets=sh).escribir([("AW2", "TRUE")])
ok(sh.diario[0][0] == "batchUpdate", u"`escribir` no usa batchUpdate")
cuerpo = sh.diario[0][1]["body"]
ok(cuerpo["valueInputOption"] == "USER_ENTERED",
   u"⛔ no escribe con USER_ENTERED: las columnas de banderas guardan BOOLEANOS, y con RAW "
   u"quedaría un texto entre ellos")
ok(cuerpo["data"][0]["range"] == "SOLICITUDES!AW2", u"el rango no es el esperado")

# ⛔ Y si el cuerpo no se puede construir, NO se llama a nadie.
sh = Sheets({})
try:
    S.Servicios(sheets=sh).escribir([("A:A", "x")])
    _paro = False
except SystemExit:
    _paro = True
ok(_paro, u"⛔ escribe contra un rango que no es una celda (A:A es la columna entera)")
ok(sh.diario == [], u"⛔ …y además llegó a llamar al mundo")

# ── 6. Publicar: devuelve la PRUEBA ────────────────────────────────────────────────────────
FILA = {"title_short": u"Informe de ensayo", "unit_key": "propulsion",
        "document_type": u"Informe", "season_label": "2026/27",
        "reference": "Informe_S-4012_27", "notion_data_source_id": "ds-1",
        "subfolder_key": "general", "reserved_id": "4012",
        # ⚠️ Con la carpeta YA creada: así este caso mide la página de Notion y no arrastra
        #    también el camino de Drive. El caso de la carpeta va aparte, abajo.
        "drive_folder_id": "F-ya-existe"}

RUTAS_VALORES = [["unit_key", "subfolder_key", "range_start", "range_end",
                  "drive_folder_id", "active"],
                 ["propulsion", "general", "4001", "4099", "F-prop-gen", "TRUE"]]


class _Files(object):
    def __init__(self, diario, resp):
        self.diario, self.resp = diario, resp

    def create(self, **kw):
        self.diario.append(("create", kw))
        return _Ejec(self.resp)


class Drive(object):
    def __init__(self, resp=None):
        self.diario = []
        self._f = _Files(self.diario, resp if resp is not None else {"id": "F-nueva"})

    def files(self):
        return self._f
_pedidos = []


def _notion_ok(url, cuerpo, token=None):
    _pedidos.append((url, cuerpo))
    return {"id": "1a2b3c", "url": "https://notion/x"}


srv = S.Servicios(sheets=Sheets({}), notion=_notion_ok)
devuelto = srv.publicar(FILA)
ok(devuelto == {"notion_page_id": "1a2b3c", "notion_page_url": "https://notion/x"},
   u"⛔ `publicar` no devuelve el id: sin él, si falla anotar la bandera la pasada siguiente "
   u"crea una SEGUNDA página del mismo documento — y nada las marca como duplicadas")
ok(_pedidos and _pedidos[0][0] == S.NOTION_CREAR, u"no llama al endpoint de crear página")
ok(_pedidos[0][1]["parent"]["data_source_id"] == "ds-1", u"no manda la base correcta")

# ⛔ Si Notion no devuelve id, se para: no se puede anotar que existe.
srv = S.Servicios(sheets=Sheets({}), notion=lambda u, c, token=None: {"url": "x"})
try:
    srv.publicar(FILA)
    _paro = False
except SystemExit as e:
    _paro = u"id" in str(e)
ok(_paro, u"⛔ sin id de vuelta debería pararse y decirlo")

# Un expediente incompleto no llega a llamar a Notion.
_pedidos2 = []
srv = S.Servicios(sheets=Sheets({}),
                  notion=lambda u, c, token=None: _pedidos2.append(1) or {"id": "x"})
try:
    srv.publicar(dict(FILA, unit_key="inventada"))
except SystemExit:
    pass
ok(_pedidos2 == [], u"⛔ se llamó a Notion con un expediente que no se puede publicar")

# ── 7. Registrar en el Libro ───────────────────────────────────────────────────────────────
sh = Sheets({"append": {"updates": {"updatedRange": "'Base de Datos'!A45:C45"}}})
srv = S.Servicios(sheets=sh)
d = srv.registrar({"reference": "Informe_S-4012_27", "drive_filename": "x.pdf",
                   "keywords": "informe, ensayo"})
# ⛔ UN NÚMERO, no el rango A1 que devuelve `append`. Medido en `SOLICITUDES`: las filas
#    reales llevan ahí `169`, `171`, `172`. Y no es cosmética: `evidencias` usa esa columna como
#    PRUEBA de que la fila del Libro se escribió.
ok(d == {"base_database_row": 45},
   u"`registrar` no devuelve el NÚMERO de fila: %r" % (d,))
# Y si el Libro no dice dónde quedó, se para: sin prueba, la pasada siguiente lo registraría
# otra vez y quedarían dos filas del mismo documento.
try:
    S.Servicios(sheets=Sheets({"append": {}})).registrar(
        {"reference": "Informe_S-4012_27", "keywords": "x"})
    _paro = False
except SystemExit:
    _paro = True
ok(_paro, u"⛔ sin saber la fila debería pararse, no dar por registrado")
ok(S.SA.fila_de_rango(u"'Base de Datos'!A45:C45") == 45, u"no saca la fila de un rango con comillas")
ok(S.SA.fila_de_rango(u"SOLICITUDES!AW2") == 2, u"no saca la fila de un rango simple")
# ⛔ Una pestaña con NÚMEROS en el nombre — y existen, `2026-27` sin ir más lejos. Sin este
#    caso, coger «el primer número que aparezca» da lo mismo que coger la fila, y la
#    mutación sale ciega: el fixture no podía plantear la pregunta.
ok(S.SA.fila_de_rango(u"'2026-27'!A45:C45") == 45,
   u"coge un número del NOMBRE de la pestaña en vez de la fila")
ok(S.SA.fila_de_rango(u"'Base 2 de Datos'!B7") == 7,
   u"…y lo mismo con un número suelto en medio del nombre")
ok(S.SA.fila_de_rango(u"") is None and S.SA.fila_de_rango(None) is None,
   u"un rango vacío no debe inventarse una fila")
ok(sh.diario[0][0] == "append", u"no usa append")
ok(sh.diario[0][1]["body"]["values"][0][0] == "Informe_S-4012_27",
   u"la fila del Libro no es la que construye `libro_datos`")
ok(sh.diario[0][1]["spreadsheetId"] == S.HOJA_LIBRO, u"registra en la hoja equivocada")

sh = Sheets({})
try:
    S.Servicios(sheets=sh).registrar({"reference": "chusta"})
    _paro = False
except SystemExit:
    _paro = True
ok(_paro and sh.diario == [],
   u"⛔ con una referencia no canónica no se escribe nada en el Libro")

# ── 8. Los dos pasos que NO se fingen ──────────────────────────────────────────────────────
# ⛔ `analizar` es el paso del modelo: se niega en voz alta. Devolver sin hacer nada dejaría la
#    bandera puesta y el expediente dado por analizado SIN análisis.
try:
    S.Servicios(sheets=Sheets({})).analizar(FILA)
    _paro = False
except SystemExit as e:
    _paro = u"modelo" in str(e)
ok(_paro, u"⛔ `analizar` debería negarse y decir por qué, no devolver sin hacer nada")

# ⚠️ `cerrar` existe y está vacío a propósito: sin el método, el ejecutor diría que no existe y
#    ningún expediente se cerraría nunca.
ok(S.Servicios(sheets=Sheets({})).cerrar(FILA) == {},
   u"`cerrar` debería existir y no hacer nada en el mundo: el cierre ES la bandera")

# ── 9. Sin credenciales se para, y se dice ─────────────────────────────────────────────────
_g = os.environ.pop("GDRIVE_SA_KEY", None)
try:
    S.credenciales_google()
    _paro = False
except SystemExit as e:
    _paro = u"GDRIVE_SA_KEY" in str(e)
finally:
    if _g is not None:
        os.environ["GDRIVE_SA_KEY"] = _g
ok(_paro, u"⛔ sin `GDRIVE_SA_KEY` debería pararse diciendo cuál falta, no reventar con una traza")

# ── La carpeta del expediente: se crea ANTES de la página, y sólo si no la hay ─────────
# ⛔ Nombre = la referencia y padre = la carpeta-ruta que sale de `RUTAS` por RANGO. Y **no se
#    toca `drive_folder_created`**: su propio código dice que esa bandera la decide el paso final
#    «cuando el resto de la publicación esté completa». Aquí sólo se devuelve el id, que es cierto.
_sin_carpeta = dict(FILA)
_sin_carpeta.pop("drive_folder_id")
dr = Drive()
srv = S.Servicios(sheets=Sheets({"get": {"values": RUTAS_VALORES}}), notion=_notion_ok, drive=dr)
_dev = srv.publicar(_sin_carpeta)
ok(dr.diario and dr.diario[0][0] == "create", u"no crea la carpeta del expediente")
_cuerpo = dr.diario[0][1]["body"]
ok(_cuerpo["name"] == "Informe_S-4012_27", u"la carpeta no se llama como la referencia: %r" % _cuerpo)
ok(_cuerpo["parents"] == ["F-prop-gen"],
   u"la carpeta no cuelga de la carpeta-ruta que sale de RUTAS: %r" % _cuerpo)
ok(dr.diario[0][1].get("supportsAllDrives") is True,
   u"sin `supportsAllDrives` fallaría en una unidad compartida")
ok(_dev.get("drive_folder_id") == "F-nueva", u"no devuelve el id de la carpeta: %r" % (_dev,))
ok(_dev.get("drive_folder_url", "").endswith("F-nueva"), u"no devuelve la URL de la carpeta")
ok("drive_folder_created" not in _dev,
   u"⛔ devuelve la BANDERA `drive_folder_created`: crear la carpeta NO es publicar, y su propio "
   u"código dice que esa bandera la decide el paso final")
ok(_dev.get("notion_page_id") == "1a2b3c", u"no devuelve también el id de la página")

# ⛔ Si Drive no devuelve el id, se para: sin él no queda constancia de la carpeta y la pasada
#    siguiente crearía otra con el mismo nombre. Sin este caso la guarda salía CIEGA — el doble
#    siempre devolvía un id.
_ped3 = []
try:
    S.Servicios(sheets=Sheets({"get": {"values": RUTAS_VALORES}}),
                notion=lambda u, c, token=None: _ped3.append(1) or {"id": "x"},
                drive=Drive({})).publicar(_sin_carpeta)
    _paro = False
except SystemExit as e:
    _paro = u"carpeta" in str(e)
ok(_paro, u"⛔ Drive sin devolver id debería pararse y decirlo")
ok(_ped3 == [], u"⛔ …y no llegar a crear la página de Notion")

# ⚠️ Con la carpeta ya creada NO se crea otra: dos carpetas con el mismo nombre y nadie sabe
#    cuál es la buena.
dr = Drive()
S.Servicios(sheets=Sheets({"get": {"values": RUTAS_VALORES}}), notion=_notion_ok,
            drive=dr).publicar(FILA)
ok(dr.diario == [], u"⛔ crea una SEGUNDA carpeta teniendo ya `drive_folder_id`")

# Y si la ruta no da carpeta, no se crea nada ni se publica: colgaría de la raíz de Drive.
dr = Drive()
_ped = []
try:
    S.Servicios(sheets=Sheets({"get": {"values": [RUTAS_VALORES[0]]}}),
                notion=lambda u, c, token=None: _ped.append(1) or {"id": "x"},
                drive=dr).publicar(_sin_carpeta)
    _paro = False
except SystemExit:
    _paro = True
ok(_paro and dr.diario == [] and _ped == [],
   u"⛔ sin carpeta-ruta debería pararse antes de tocar Drive y Notion")

print("%d comprobaciones" % hechas[0])
if fallos:
    print("\n%d ROJO(S):" % len(fallos))
    for f_ in fallos:
        print("  - %s" % f_)
    sys.exit(1)
print("verde")
