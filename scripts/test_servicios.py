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

import notion_api as NA
import servicios as S

# ⛔⛔ EL ENTORNO SE FIJA AQUÍ, ANTES DE NADA. Este banco leía `DOMINIO_EQUIPO` de la máquina:
#    verde con `uvigo.es` —lo que tenía exportado quien lo escribió— y **rojo con cualquier otro
#    valor y rojo sin la variable**, o sea rojo en el CI y rojo en el portátil de Daniel. Un banco
#    que depende del entorno de quien lo corre no mide el código: mide la máquina, y el día que se
#    pone rojo manda a buscar un fallo que no existe.
#    ⚠️ Va **antes de construir nada**, y el valor tiene que ser el mismo que devuelve el doble
#       de permisos de Drive: si no coinciden, `permiso_dominio` se planta al releer.
os.environ["DOMINIO_EQUIPO"] = "uvigo.es"

fallos = []
hechas = [0]


# ⛔⛔ LA PUERTA DE LECTURA DE NOTION, DOBLADA PARA TODO EL BANCO. Lo cantó el propio banco:
#    al hacer que `publicar` pidiera las opciones de «Etiquetas», empezó a pedir `NOTION_TOKEN`
#    — o sea que iba a hablar con Notion **de verdad**, que es lo único que un banco no puede
#    hacer. Es la **segunda vez** con esta forma: una llamada nueva dentro de un método ya
#    probado se lleva por delante los dobles de los casos de al lado.
#    ⚠️ Se sustituye **antes** de construir nada (`Servicios.__init__` resuelve
#       `notion_get or http_notion_get` al construirse) y **apunta en vez de lanzar**:
#       `opciones_etiquetas` se traga cualquier excepción a propósito —Notion caído no puede
#       impedir publicar—, así que un doble que lanzara saldría **verde igual**. Lo que lo
#       delata es el recuento, comprobado al final del fichero.
_intentos_red = []


def _sin_red(url, token=None):
    _intentos_red.append(url)
    return {}


S.http_notion_get = _sin_red


def _sin_red_patch(url, cuerpo, token=None):
    """El mismo tripwire para el PATCH: una puerta nueva necesita su propio doble, o el banco
    se va a la red por el hueco que acaba de abrirse."""
    _intentos_red.append(url)
    return {"results": []}


S.http_notion_patch = _sin_red_patch


def _esq(url, token=None):
    """El esquema de «Etiquetas», doblado: vacío."""
    return {}


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
srv = S.Servicios(notion_get=_esq, sheets=sh)
ok(srv.leer() == [["request_id"], ["R-1"]], u"`leer` no devuelve los valores crudos")
# ⛔⛔ ESTE CASO FIJABA `A1:BZ`, que es **78 columnas de las 104** de la hoja. O sea que
#    sostenía el fallo: con él verde, `revisor_field_pendiente` y los `annex_*` no llegaban al
#    código y sus guardas se quedaban sin datos. Se corrige con su motivo escrito, y lo que
#    de verdad vigila el rango es el caso de más abajo, que lo cruza con las columnas que los
#    módulos nombran — un literal copiado aquí no puede saber si llega o no llega.
ok(sh.diario[0][1]["range"] == S.RANGO_SOLICITUDES,
   u"`leer` no pide el rango que declara el módulo: %r" % (sh.diario[0][1],))
ok(sh.diario[0][1]["range"].endswith(":CZ"),
   u"el rango no llega al final de la hoja: %r" % (sh.diario[0][1]["range"],))
ok(sh.diario[0][1]["spreadsheetId"] == S.HOJA_SOLICITUDES, u"`leer` pide otra hoja")

# ⛔ El Libro se pide CON LA PESTAÑA ENTRECOMILLADA: «Base de Datos» lleva espacios y sin
#    comillas el rango no es válido — la lectura se pierde entera.
sh = Sheets({"get": {"values": [["Título", "Ubic", "Claves"], ["Informe_S-1_27", "x", "y"]]}})
srv = S.Servicios(notion_get=_esq, sheets=sh)
filas = srv.leer_libro()
ok(filas == [["Informe_S-1_27", "x", "y"]],
   u"`leer_libro` no quita la cabecera (es lo que espera `libro_datos`): %r" % (filas,))
ok(sh.diario[0][1]["range"].startswith(u"'Base de Datos'!"),
   u"⛔ el rango del Libro va sin comillas: %r" % (sh.diario[0][1]["range"],))

# ── 4. Releer ──────────────────────────────────────────────────────────────────────────────
sh = Sheets({"batchGet": {"valueRanges": [{"values": [["TRUE"]]}, {"values": [[""]]}]}})
srv = S.Servicios(notion_get=_esq, sheets=sh)
leidas = srv.releer(["AW2", "BX2"])
ok(leidas == {"AW2": "TRUE", "BX2": ""}, u"`releer` no devuelve el mapa esperado: %r" % (leidas,))
ok(sh.diario[0][1]["ranges"] == ["SOLICITUDES!AW2", "SOLICITUDES!BX2"],
   u"`releer` no pide los rangos de esas celdas: %r" % (sh.diario[0][1],))
# Sin claves no se molesta a nadie.
sh = Sheets({})
ok(S.Servicios(notion_get=_esq, sheets=sh).releer([]) == {} and sh.diario == [],
   u"releer sin claves no debería llamar al mundo")
# Una celda inválida no se pide: `sheets_api` ya dijo que no es una celda de datos.
sh = Sheets({"batchGet": {"valueRanges": [{"values": [["x"]]}]}})
S.Servicios(notion_get=_esq, sheets=sh).releer(["A1"])
ok(sh.diario == [], u"⛔ se pide releer la CABECERA: `A1` no es una celda de datos")

# ── 5. Escribir ────────────────────────────────────────────────────────────────────────────
sh = Sheets({})
S.Servicios(notion_get=_esq, sheets=sh).escribir([("AW2", "TRUE")])
ok(sh.diario[0][0] == "batchUpdate", u"`escribir` no usa batchUpdate")
cuerpo = sh.diario[0][1]["body"]
ok(cuerpo["valueInputOption"] == "USER_ENTERED",
   u"⛔ no escribe con USER_ENTERED: las columnas de banderas guardan BOOLEANOS, y con RAW "
   u"quedaría un texto entre ellos")
ok(cuerpo["data"][0]["range"] == "SOLICITUDES!AW2", u"el rango no es el esperado")

# ⛔ Y si el cuerpo no se puede construir, NO se llama a nadie.
sh = Sheets({})
try:
    S.Servicios(notion_get=_esq, sheets=sh).escribir([("A:A", "x")])
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

    def get(self, **kw):
        self.diario.append(("get", kw))
        return _Ejec(self.meta)

    def get_media(self, **kw):
        self.diario.append(("get_media", kw))
        return _Ejec(self.datos)

    def copy(self, **kw):
        self.diario.append(("copy", kw))
        # ⚠️ Cada copia devuelve un id DISTINTO, como Drive: un doble que devolviera siempre
        #    el mismo dejaría pasar un código que se queda con uno solo de los siete.
        self.copias = getattr(self, "copias", 0) + 1
        return _Ejec({"id": "C-%d" % self.copias})

    def update(self, **kw):
        self.diario.append(("update", kw))
        # ⚠️ El doble MUEVE de verdad: tras el update, `get` devuelve el padre nuevo. Un doble
        #    que no cambiara de estado dejaría la verificación roja sobre código correcto.
        self.meta = dict(self.meta, parents=[kw.get("addParents")])
        return _Ejec({"id": kw.get("fileId"), "parents": [kw.get("addParents")]})


class _Permisos(object):
    def __init__(self, diario, dominio="uvigo.es"):
        self.diario, self.dominio = diario, dominio

    def create(self, **kw):
        self.diario.append(("perm_create", kw))
        return _Ejec({"id": "perm-1"})

    def list(self, **kw):
        self.diario.append(("perm_list", kw))
        return _Ejec({"permissions": [{"type": "domain", "role": "reader",
                                       "domain": self.dominio}]})


class _Medio(object):
    """El doble de `MediaInMemoryUpload`: guarda los bytes para poder LEERLOS en el caso.

    ⚠️ Si sólo guardara que se llamó, un resumen con el texto equivocado saldría verde.
    """
    def __init__(self, datos, tipo):
        self.datos, self.tipo = datos, tipo


class Drive(object):
    def __init__(self, resp=None, meta=None, datos=b"PDFDATA", dominio="uvigo.es"):
        self.diario = []
        self._p = _Permisos(self.diario, dominio)
        self._f = _Files(self.diario, resp if resp is not None else {"id": "F-nueva"})
        # ⚠️ Con `mimeType`, como el Drive de verdad cuando se le pide: sin él, el doble era
        #    más pobre que el real y `mover_a_carpeta` daba el PDF por no-PDF.
        self._f.meta = meta if meta is not None else {"name": "doc.pdf", "size": "1024",
                                                      "mimeType": "application/pdf",
                                                      "parents": ["F-bandeja"]}
        self._f.datos = datos

    def files(self):
        return self._f

    def permissions(self):
        return self._p
_pedidos = []


def _notion_ok(url, cuerpo, token=None):
    _pedidos.append((url, cuerpo))
    return {"id": "1a2b3c", "url": "https://notion/x"}


srv = S.Servicios(notion_get=_esq, sheets=Sheets({}), notion=_notion_ok)
devuelto = srv.publicar(FILA)
ok(devuelto == {"notion_page_id": "1a2b3c", "notion_page_url": "https://notion/x"},
   u"⛔ `publicar` no devuelve el id: sin él, si falla anotar la bandera la pasada siguiente "
   u"crea una SEGUNDA página del mismo documento — y nada las marca como duplicadas")
ok(_pedidos and _pedidos[0][0] == S.NOTION_CREAR, u"no llama al endpoint de crear página")
ok(_pedidos[0][1]["parent"]["data_source_id"] == "ds-1", u"no manda la base correcta")

# ⛔ Si Notion no devuelve id, se para: no se puede anotar que existe.
srv = S.Servicios(notion_get=_esq, sheets=Sheets({}), notion=lambda u, c, token=None: {"url": "x"})
try:
    srv.publicar(FILA)
    _paro = False
except SystemExit as e:
    _paro = u"id" in str(e)
ok(_paro, u"⛔ sin id de vuelta debería pararse y decirlo")

# Un expediente incompleto no llega a llamar a Notion.
_pedidos2 = []
srv = S.Servicios(notion_get=_esq, sheets=Sheets({}),
                  notion=lambda u, c, token=None: _pedidos2.append(1) or {"id": "x"})
try:
    srv.publicar(dict(FILA, unit_key="inventada"))
except SystemExit:
    pass
ok(_pedidos2 == [], u"⛔ se llamó a Notion con un expediente que no se puede publicar")

# ── 7. Registrar en el Libro ───────────────────────────────────────────────────────────────
sh = Sheets({"append": {"updates": {"updatedRange": "'Base de Datos'!A45:C45"}}})
srv = S.Servicios(notion_get=_esq, sheets=sh)
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
    S.Servicios(notion_get=_esq, sheets=Sheets({"append": {}})).registrar(
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
    S.Servicios(notion_get=_esq, sheets=sh).registrar({"reference": "chusta"})
    _paro = False
except SystemExit:
    _paro = True
ok(_paro and sh.diario == [],
   u"⛔ con una referencia no canónica no se escribe nada en el Libro")

# ── 8. Los dos pasos que NO se fingen ──────────────────────────────────────────────────────
# ⛔ `analizar` es el paso del modelo: se niega en voz alta. Devolver sin hacer nada dejaría la
#    bandera puesta y el expediente dado por analizado SIN análisis.
try:
    S.Servicios(notion_get=_esq, sheets=Sheets({})).analizar(FILA)
    _paro = False
except SystemExit as e:
    _paro = u"modelo" in str(e)
ok(_paro, u"⛔ `analizar` debería negarse y decir por qué, no devolver sin hacer nada")

# ⚠️ `cerrar` existe y está vacío a propósito: sin el método, el ejecutor diría que no existe y
#    ningún expediente se cerraría nunca.
ok(S.Servicios(notion_get=_esq, sheets=Sheets({})).cerrar(FILA) == {},
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
srv = S.Servicios(notion_get=_esq, sheets=Sheets({"get": {"values": RUTAS_VALORES}}), notion=_notion_ok, drive=dr)
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
    S.Servicios(notion_get=_esq, sheets=Sheets({"get": {"values": RUTAS_VALORES}}),
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
S.Servicios(notion_get=_esq, sheets=Sheets({"get": {"values": RUTAS_VALORES}}), notion=_notion_ok,
            drive=dr).publicar(FILA)
ok(dr.diario == [], u"⛔ crea una SEGUNDA carpeta teniendo ya `drive_folder_id`")

# Y si la ruta no da carpeta, no se crea nada ni se publica: colgaría de la raíz de Drive.
dr = Drive()
_ped = []
try:
    S.Servicios(notion_get=_esq, sheets=Sheets({"get": {"values": [RUTAS_VALORES[0]]}}),
                notion=lambda u, c, token=None: _ped.append(1) or {"id": "x"},
                drive=dr).publicar(_sin_carpeta)
    _paro = False
except SystemExit:
    _paro = True
ok(_paro and dr.diario == [] and _ped == [],
   u"⛔ sin carpeta-ruta debería pararse antes de tocar Drive y Notion")

# ── El fichero se sube ANTES de crear la página ──────────────────────────────
# ⛔ Si se crea primero y la subida falla, queda una página SIN documento y marcada como creada:
#    el caso que nadie vuelve a mirar.
_CON_FICHERO = dict(FILA, source_drive_file_id="D-1")
_subidas = []


def _subir_ok(url, datos, nombre, token=None):
    _subidas.append((url, datos, nombre))
    return {"status": "uploaded"}


def _leer_bloques_ok(url, token=None):
    return {"results": [{"file": {"file_upload": {"id": "up-1"}}}]}


def _leer_bloques_vacio(url, token=None):
    return {"results": []}


def _notion_subida(url, cuerpo, token=None):
    _pedidos.append((url, cuerpo))
    if url.endswith("/file_uploads"):
        return {"id": "up-1", "upload_url": "https://notion/up/1"}
    return {"id": "1a2b3c", "url": "https://notion/x"}


_pedidos = []
dr = Drive()
srv = S.Servicios(sheets=Sheets({"get": {"values": RUTAS_VALORES}}), notion=_notion_subida,
                  drive=dr, subir=_subir_ok, notion_get=_leer_bloques_ok)
_dev = srv.publicar(_CON_FICHERO)
ok([u for u, _c in _pedidos][0].endswith("/file_uploads"),
   "⛔ pide el hueco de subida DESPUÉS de crear la página: %r" % ([u for u, _c in _pedidos],))
ok(_subidas and _subidas[0][1] == b"PDFDATA", "no manda el contenido bajado de Drive")
ok(_subidas[0][2] == "doc.pdf", "no manda el nombre que dio Drive")
_crear = [c for u, c in _pedidos if u == S.NOTION_CREAR][0]
ok(_crear["children"][0]["file"]["file_upload"]["id"] == "up-1",
   "la página no lleva el fichero subido: %r" % (_crear.get("children"),))
ok([d[0] for d in dr.diario].count("get_media") == 1, "no baja el fichero de Drive una vez")

# ⛔ El tamaño se mira ANTES de descargar.
dr = Drive(meta={"name": "gordo.pdf", "size": str(21 * 1024 * 1024)})
try:
    S.Servicios(sheets=Sheets({"get": {"values": RUTAS_VALORES}}), notion=_notion_subida,
                drive=dr, subir=_subir_ok, notion_get=_leer_bloques_ok).publicar(_CON_FICHERO)
    _paro = False
except SystemExit as e:
    _paro = "20 MiB" in str(e)
ok(_paro, "⛔ un fichero de 21 MiB debería pararse y decir el tope")
ok("get_media" not in [d[0] for d in dr.diario],
   "⛔ …y NO haberse bajado: 40 MB para descubrir que no caben es tiempo y RAM tirados")

# ⛔ Si Notion no da hueco (falta `id` o `upload_url`), se para antes de bajar el fichero.
#    Sin este caso la guarda salía CIEGA: el doble siempre daba los dos.
for _hueco in ({"id": "up-1"}, {"upload_url": "u"}, {}):
    _dr = Drive()
    try:
        S.Servicios(notion_get=_esq, sheets=Sheets({"get": {"values": RUTAS_VALORES}}),
                    notion=lambda u, c, token=None, _h=_hueco: (
                        _h if u.endswith("/file_uploads") else {"id": "p"}),
                    drive=_dr, subir=_subir_ok).publicar(_CON_FICHERO)
        _paro = False
    except SystemExit as e:
        _paro = "hueco" in str(e)
    ok(_paro, u"⛔ con el hueco de subida a medias (%r) debería pararse" % (_hueco,))
    ok("get_media" not in [x[0] for x in _dr.diario],
       u"⛔ …y no haberse bajado el fichero de Drive")

# ⛔ Si la subida no termina, no se crea la página.
_ped2 = []
try:
    S.Servicios(notion_get=_esq, sheets=Sheets({"get": {"values": RUTAS_VALORES}}),
                notion=lambda u, c, token=None: (_ped2.append(u) or
                                                 ({"id": "up", "upload_url": "u"}
                                                  if u.endswith("/file_uploads")
                                                  else {"id": "p"})),
                drive=Drive(), subir=lambda *a, **k: {"status": "pending"}).publicar(_CON_FICHERO)
    _paro = False
except SystemExit as e:
    _paro = "sin documento" in str(e)
ok(_paro, "⛔ una subida a medias debería parar antes de crear la página")
ok(S.NOTION_CREAR not in _ped2, "⛔ …y no haber creado la página")

# ⚠️ Sin fichero de origen, la página se crea igual: no todo expediente trae adjunto.
_pedidos = []
dr = Drive()
_d = S.Servicios(sheets=Sheets({"get": {"values": RUTAS_VALORES}}), notion=_notion_subida,
                 drive=dr, subir=_subir_ok, notion_get=_leer_bloques_ok).publicar(FILA)
ok(_d.get("notion_page_id") == "1a2b3c", "sin fichero debería crearse la página igual")
ok("get_media" not in [x[0] for x in dr.diario], "sin fichero no debería bajarse nada")

# ── Subir NO es verificar: se relee la página ─────────────────────────────────
# ⛔ Que la subida diga `uploaded` prueba que el fichero llegó a Notion, NO que haya quedado
#    colgado de la página. Es la misma distinción que tumbó `drive_primary_file_verified`.
ok(S.Servicios(notion_get=_leer_bloques_ok).verificar_embebido("p-1", "up-1") is True,
   "no ve el fichero que SÍ está en la página")
ok(S.Servicios(notion_get=_leer_bloques_vacio).verificar_embebido("p-1", "up-1") is False,
   "⛔ da por embebido un fichero que NO está en la página")
ok(S.Servicios(notion_get=_leer_bloques_ok).verificar_embebido("p-1", "OTRO") is False,
   "⛔ da por bueno un bloque con OTRA subida dentro")
ok(S.Servicios(notion_get=_leer_bloques_ok).verificar_embebido("", "up-1") is False,
   "sin id de página no hay nada que verificar")

# ⛔ Y si tras crear la página el fichero no está, se dice: la página ya existe y no se puede
#    deshacer, pero sí impedir que se marque como embebida.
try:
    S.Servicios(sheets=Sheets({"get": {"values": RUTAS_VALORES}}), notion=_notion_subida,
                drive=Drive(), subir=_subir_ok,
                notion_get=_leer_bloques_vacio).publicar(_CON_FICHERO)
    _paro = False
except SystemExit as e:
    _paro = "NO está dentro" in str(e) or "no est" in str(e).lower()
ok(_paro, "⛔ la página se creó sin el fichero y se dio por buena")

# ── El fichero se ARCHIVA en la carpeta del expediente ─────────────────────────
# ⛔ MOVER, no copiar: copiar deja dos ficheros iguales — el de la bandeja del formulario y el
#    archivado — y nadie sabe cuál es el bueno ni cuál se corrige.
dr = Drive()
_d = S.Servicios(sheets=Sheets({"get": {"values": RUTAS_VALORES}}), notion=_notion_subida,
                 drive=dr, subir=_subir_ok, notion_get=_leer_bloques_ok).publicar(_CON_FICHERO)
_upd = [k for a, k in dr.diario if a == "update"]
ok(len(_upd) == 1, "no mueve el fichero a la carpeta del expediente: %r" % ([a for a, _ in dr.diario],))
ok(_upd[0]["addParents"] == "F-ya-existe" or _upd[0]["addParents"] == "F-nueva",
   "no lo mueve a la carpeta del expediente: %r" % (_upd[0],))
ok(_upd[0]["removeParents"] == "F-bandeja",
   "⛔ no lo SACA de la bandeja: quedaría colgando de las dos carpetas")
ok("copy" not in [a for a, _ in dr.diario], "⛔ COPIA en vez de mover: dos ficheros iguales")
ok(_d.get("drive_primary_file_id") == "D-1", "no devuelve el id del fichero archivado")
ok(_upd[0].get("supportsAllDrives") is True, "sin supportsAllDrives fallaría en unidad compartida")

# ⛔ Llamado sin carpeta o sin fichero, se para: mover «a ninguna parte» sacaría el fichero de
#    la bandeja sin meterlo en ningún sitio. Sin este caso la guarda salía CIEGA — `publicar`
#    sólo la llama cuando tiene las dos cosas.
for _f, _c in ((_CON_FICHERO, ""), (FILA, "F-x"), ({}, "")):
    _dr = Drive()
    try:
        S.Servicios(notion_get=_esq, drive=_dr).mover_a_carpeta(_f, _c)
        _paro = False
    except SystemExit:
        _paro = True
    ok(_paro, u"⛔ mover con origen %r y destino %r debería pararse"
       % (_f.get("source_drive_file_id"), _c))
    ok(_dr.diario == [], u"⛔ …y no haber tocado Drive")

# ⚠️ Sin fichero de origen no se mueve nada, y la página se crea igual.
dr = Drive()
S.Servicios(sheets=Sheets({"get": {"values": RUTAS_VALORES}}), notion=_notion_subida,
            drive=dr, subir=_subir_ok, notion_get=_leer_bloques_ok).publicar(FILA)
ok("update" not in [a for a, _ in dr.diario], "mueve algo sin haber fichero de origen")

# ── Mover no es verificar, y compartir se relee ───────────────────────────────
_dr = Drive(meta={"name": "d.pdf", "size": "10", "parents": ["F-buena"]})
ok(S.Servicios(notion_get=_esq, drive=_dr).verificar_en_carpeta("D-1", "F-buena") is True,
   "no ve el fichero que SÍ está en la carpeta")
ok(S.Servicios(notion_get=_esq, drive=_dr).verificar_en_carpeta("D-1", "F-otra") is False,
   "⛔ da por archivado un fichero que está en OTRA carpeta")
ok(S.Servicios(notion_get=_esq, drive=_dr).verificar_en_carpeta("", "F-buena") is False, "sin fichero no verifica")

# ⛔ Si tras mover no consta en la carpeta, no se da por archivado.
class _NoMueve(Drive):
    def __init__(self):
        Drive.__init__(self, meta={"name": "d.pdf", "size": "10", "parents": ["F-bandeja"]})

    def files(self):
        _f = Drive.files(self)
        _f.update = lambda **kw: (self.diario.append(("update", kw)) or _Ejec({}))
        return _f

try:
    S.Servicios(sheets=Sheets({"get": {"values": RUTAS_VALORES}}), notion=_notion_subida,
                drive=_NoMueve(), subir=_subir_ok,
                notion_get=_leer_bloques_ok).publicar(_CON_FICHERO)
    _paro = False
except SystemExit as e:
    _paro = "carpeta" in str(e)
ok(_paro, "⛔ el fichero no se movió y se dio por archivado")

# ⛔ Y `publicar` lo comparte: sin el permiso, el documento queda archivado y **nadie del
#    equipo puede abrirlo**, con la página de Notion diciendo que está publicado. Sin este
#    caso la llamada salía CIEGA — se probaba el método suelto, no que `publicar` lo use.
_dr = Drive()
S.Servicios(sheets=Sheets({"get": {"values": RUTAS_VALORES}}), notion=_notion_subida,
            drive=_dr, subir=_subir_ok, notion_get=_leer_bloques_ok).publicar(_CON_FICHERO)
ok("perm_create" in [a for a, _ in _dr.diario],
   u"⛔ publica sin compartir: el equipo no podría abrir el documento")

# ── El permiso de dominio se CREA y se RELEE ───────────────────────────────
_dr = Drive()
ok(S.Servicios(notion_get=_esq, drive=_dr).permiso_dominio("D-1") is True, "no comparte con el dominio")
_pc = [k for a, k in _dr.diario if a == "perm_create"][0]
ok(_pc["body"] == {"type": "domain", "role": "reader", "domain": "uvigo.es"},
   "el permiso no es de lectura para el dominio: %r" % (_pc.get("body"),))
ok(_pc.get("sendNotificationEmail") is False,
   "⚠️ manda correo a todo el dominio por cada documento")
ok("perm_list" in [a for a, _ in _dr.diario],
   "⛔ no RELEE el permiso: crear no es comprobar")

# ⛔ Si el permiso no consta tras crearlo, se dice: el equipo no podría abrir el documento.
_dr = Drive(dominio="otro.es")
try:
    S.Servicios(notion_get=_esq, drive=_dr).permiso_dominio("D-1")
    _paro = False
except SystemExit as e:
    _paro = "no consta" in str(e)
ok(_paro, "⛔ el permiso no quedó y se dio por bueno")

# Sin dominio configurado se para: compartir con "" no comparte con nadie.
_g = os.environ.pop("DOMINIO_EQUIPO", None)
try:
    S.Servicios(notion_get=_esq, drive=Drive()).permiso_dominio("D-1")
    _paro = False
except SystemExit as e:
    _paro = "DOMINIO_EQUIPO" in str(e)
finally:
    # ⚠️ Se restaura al valor DEL BANCO, no al de la máquina: si no, los casos de después
    #    heredan lo que hubiera fuera y vuelven a medir el entorno.
    os.environ["DOMINIO_EQUIPO"] = "uvigo.es"
ok(_paro, "⛔ sin `DOMINIO_EQUIPO` debería pararse diciendo cuál falta")

# ── El resumen ejecutivo, como fichero dentro de la carpeta ────────────
# ⛔ El resumen YA EXISTE — lo genera el paso 2 y viaja en `executive_summary`. Aquí sólo se
#    archiva. Lo que se prueba es que no se invente, que no se escriba vacío y que no se duplique.
_RES = u"El informe recoge el ensayo estático del 12/09 con tres anomalías."
_dr = Drive()
_d = S.Servicios(notion_get=_esq, drive=_dr, medio=_Medio).crear_resumen(dict(FILA, executive_summary=_RES), "F-exp")
_cr = [k for a_, k in _dr.diario if a_ == "create"]
ok(len(_cr) == 1, u"no crea el fichero del resumen: %r" % (_dr.diario,))
ok(_cr and _cr[0]["body"]["parents"] == ["F-exp"],
   u"⛔ el resumen no cuelga de la carpeta del expediente: %r" % (_cr[0]["body"],))
ok(_cr and _cr[0]["body"]["name"].startswith("Informe_S-4012_27"),
   u"el resumen no lleva la referencia en el nombre: nadie sabrá de qué documento es: %r"
   % (_cr[0]["body"].get("name"),))
ok(_cr and _cr[0].get("supportsAllDrives") is True,
   u"sin `supportsAllDrives` fallaría en una unidad compartida")
ok(_cr and "mimeType" not in _cr[0]["body"],
   u"⚠️ un `mimeType` de carpeta ahí crearía una carpeta en vez de un fichero")
ok(_d == {"drive_summary_file_id": "F-nueva"},
   u"no devuelve el id del resumen, que es la PRUEBA de la bandera: %r" % (_d,))
# El contenido es el resumen que vino, no otro texto.
_med = _cr[0].get("media_body") if _cr else None
_bytes = _med.datos if _med is not None else b""
ok(_med is not None and _med.tipo == "text/plain",
   u"el resumen no se sube como texto plano: %r" % (getattr(_med, "tipo", None),))
ok(_bytes.decode("utf-8") == _RES,
   u"⛔ el fichero no lleva el resumen que generó el paso 2: %r" % (_bytes[:60],))

# ⛔ SIN resumen NO se crea un fichero vacío: quien lo abra creería que ya está mirado.
for _vacio in (u"", u"   ", None):
    _dr = Drive()
    _d = S.Servicios(notion_get=_esq, drive=_dr, medio=_Medio).crear_resumen(dict(FILA, executive_summary=_vacio), "F-exp")
    ok(_d == {} and _dr.diario == [],
       u"⛔ con `executive_summary`=%r crea un fichero de resumen VACÍO" % (_vacio,))
# Sin carpeta tampoco: colgaría de la raíz de Drive.
_dr = Drive()
ok(S.Servicios(notion_get=_esq, drive=_dr, medio=_Medio).crear_resumen(dict(FILA, executive_summary=_RES), "") == {}
   and _dr.diario == [], u"⛔ sin carpeta el resumen colgaría de la raíz de Drive")

# ⛔ Si Drive no devuelve el id, se para: sin él la pasada siguiente crearía un segundo resumen.
try:
    S.Servicios(notion_get=_esq, drive=Drive({}), medio=_Medio).crear_resumen(dict(FILA, executive_summary=_RES), "F-exp")
    _paro = False
except SystemExit as e:
    _paro = "resumen" in str(e)
ok(_paro, u"⛔ Drive sin devolver id debería pararse y decirlo")

# ── Y `publicar` lo usa ───────────────────────────────────────────
# ⚠️ Probar el método suelto deja CIEGA la línea que lo llama: ya pasó con `verificar_en_carpeta`.
_dr = Drive()
_d = S.Servicios(notion_get=_esq, sheets=Sheets({"get": {"values": RUTAS_VALORES}}), notion=_notion_ok,
                 drive=_dr, medio=_Medio).publicar(dict(FILA, executive_summary=_RES))
ok(_d.get("drive_summary_file_id") == "F-nueva",
   u"⛔ `publicar` no archiva el resumen ejecutivo: %r" % (_d,))
_cr = [k for a_, k in _dr.diario if a_ == "create"]
ok(_cr and _cr[0]["body"]["parents"] == ["F-ya-existe"],
   u"⛔ el resumen no va a la carpeta que YA tenía la fila: %r" % (_cr[0]["body"] if _cr else None,))
# ⚠️ Y no depende de que haya fichero que mover: una fila sin `source_drive_file_id` tiene
#    resumen igual, y sin este caso el resumen se colgaba de esa rama.
ok("source_drive_file_id" not in FILA or not FILA.get("source_drive_file_id"),
   u"el caso de arriba ya trae fichero: no prueba lo que dice")

# ⚠️ Con el resumen ya archivado no se crea un segundo.
_dr = Drive()
_d = S.Servicios(notion_get=_esq, sheets=Sheets({"get": {"values": RUTAS_VALORES}}), notion=_notion_ok,
                 drive=_dr, medio=_Medio).publicar(dict(FILA, executive_summary=_RES,
                                          drive_summary_file_id="F-ya"))
ok([k for a_, k in _dr.diario if a_ == "create"] == [],
   u"⛔ crea un SEGUNDO resumen teniendo ya `drive_summary_file_id`")

# ── `drive_primary_file_id` ES EL PDF, Y SI LO MOVIDO ES UN DOCX NO LO ES ──
# ⛔⛔ `mover_a_carpeta` escribía en `drive_primary_file_id` **lo que hubiera movido**, y lo que
#    mueve es el adjunto del formulario — que en casi todos los expedientes reales es un **DOCX**.
#    Esa columna significa **el PDF** (comprobado con la fila 12: sus propias notas dicen que el
#    PDF bueno es `13A2NAK…`, justo lo que trae). Escribir ahí un DOCX no da ningún error y deja
#    la columna significando **dos cosas según quién la escribió**, que es la peor clase de dato.
class _ConMime(Drive):
    def __init__(self, mime):
        Drive.__init__(self)
        self._mime = mime

    def files(self):
        f = Drive.files(self)
        _u = f.update

        def _get(**kw):
            return _Ejec({"parents": ["F-bandeja"], "mimeType": self._mime, "name": "x"})
        f.get = _get
        return f


_d = S.Servicios(notion_get=_esq, drive=_ConMime("application/pdf")).mover_a_carpeta(
    {"source_drive_file_id": "D-1"}, "F-exp")
ok(_d == {"drive_primary_file_id": "D-1"},
   u"un PDF movido SÍ es el fichero principal: %r" % (_d,))

_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_d = S.Servicios(notion_get=_esq, drive=_ConMime(_DOCX)).mover_a_carpeta(
    {"source_drive_file_id": "D-1"}, "F-exp")
ok(_d.get("drive_primary_file_id") is None,
   u"⛔ llama «fichero principal» a un DOCX: esa columna es el PDF, y así significa dos cosas "
   u"según quién la escribió: %r" % (_d,))
ok(_d.get("drive_docx_file_id") == "D-1",
   u"el DOCX movido debería quedar anotado en su columna: %r" % (_d,))
# ⛔⛔ Y `publicar` ENTERO con un DOCX: el caso que faltaba. Sin él, la línea que busca el id
#    del fichero movido salía **ciega** — con `drive_primary_file_id` a `None`, la verificación
#    miraba un `None` y el expediente se plantaba en «no consta en la carpeta», que es el
#    mensaje que manda a buscar un problema de Drive que no existe.
class _DriveDocx(_ConMime):
    def __init__(self):
        _ConMime.__init__(self, _DOCX)

    def files(self):
        f = _ConMime.files(self)
        _g = f.get

        def _get(**kw):
            m = dict(_g(**kw).execute())
            # Tras el `update`, el doble mueve de verdad: si no, la verificación saldría roja
            # sobre código correcto.
            m["parents"] = self._f.meta.get("parents", ["F-bandeja"])
            m["size"], m["name"] = "1024", "informe.docx"
            return _Ejec(m)
        f.get = _get
        return f


_dd = _DriveDocx()
def _notion_docx(url, cuerpo, token=None):
    """Contesta lo que toca a cada endpoint: el hueco de subida y la creación de la página."""
    if url.endswith("/file_uploads"):
        return {"id": "up-9", "upload_url": "https://notion/sube"}
    return {"id": "1a2b3c", "url": "https://notion/x"}


_d = S.Servicios(sheets=Sheets({"get": {"values": RUTAS_VALORES}}), notion=_notion_docx,
                 notion_get=lambda u, token=None: {"results": [
                     {"file": {"file_upload": {"id": "up-9"}}}]},
                 subir=_subir_ok,
                 drive=_dd).publicar(dict(FILA, source_drive_file_id="D-docx"))
ok(_d.get("drive_docx_file_id") == "D-docx",
   u"⛔ publicando un DOCX no queda anotado dónde fue: %r" % (_d,))
ok("drive_primary_file_id" not in _d,
   u"⛔ un DOCX publicado se anota como el PDF principal: %r" % (_d,))
ok([k for a_, k in _dd.diario if a_ == "perm_create"],
   u"⛔ el DOCX archivado no se comparte con el dominio: se archiva y nadie puede abrirlo")

# ⚠️ Un mimeType que no se entiende NO se da por PDF: fallaría hacia mentir.
_d = S.Servicios(notion_get=_esq, drive=_ConMime("")).mover_a_carpeta(
    {"source_drive_file_id": "D-1"}, "F-exp")
ok(_d.get("drive_primary_file_id") is None,
   u"⛔ sin saber qué es, lo da por PDF: %r" % (_d,))

# ── A NOTION SUBE EL PDF, NO EL DOCX QUE MANDÓ EL AUTOR ───────────
# ⛔⛔ Medido el 29/09: de los 15 expedientes con fichero, **casi todos llegan en DOCX** y el
#    pipeline de Cowork **genera un PDF** — y ese PDF es el que vive en `drive_primary_file_id`.
#    Comprobado con dos filas: la 12 dice en sus propias notas que el PDF bueno es
#    `13A2NAKagBGH4LXQI6rGasDhr3SFo2LNX`, y eso es exactamente lo que trae su
#    `drive_primary_file_id`. `source_drive_file_id` es **el adjunto del formulario**, o sea el
#    DOCX.
#    ⚠️ Subir el DOCX no da error: Notion lo acepta y crea un bloque de fichero **que no se
#       puede leer en la página**. Quien abra el documento verá un adjunto para descargar, que
#       es justo lo que la página existe para evitar.
_subidas_pdf = []


def _subir_mira(url, datos, nombre, token=None):
    _subidas_pdf.append(nombre)
    return {"status": "uploaded"}


class _DosFicheros(Drive):
    """Un doble que distingue los dos ficheros: el DOCX del formulario y el PDF generado."""
    NOMBRES = {"D-docx": "Informe_S-2010_26.docx", "D-pdf": "Informe_S-2010_26.pdf"}

    def files(self):
        f = Drive.files(self)
        f.get = lambda **kw: _Ejec({"name": self.NOMBRES.get(kw.get("fileId"), "?"),
                                    "size": "1024", "parents": ["F-bandeja"]})
        return f


_srv = S.Servicios(notion_get=_esq, drive=_DosFicheros(), subir=_subir_mira,
                   notion=lambda u, c, token=None: {"id": "up-1", "upload_url": "http://x"})
_srv._subir_fichero({"source_drive_file_id": "D-docx",
                     "drive_primary_file_id": "D-pdf"})
ok(_subidas_pdf and _subidas_pdf[-1].endswith(".pdf"),
   u"⛔ sube a Notion el DOCX del formulario en vez del PDF generado: %r" % (_subidas_pdf,))

# ⚠️ Y si no hay PDF generado, se sube lo que haya: quedarse sin documento por esperar un
#    fichero que nadie va a generar es peor que un adjunto sin previsualización.
_subidas_pdf[:] = []
_srv = S.Servicios(notion_get=_esq, drive=_DosFicheros(), subir=_subir_mira,
                   notion=lambda u, c, token=None: {"id": "up-1", "upload_url": "http://x"})
_srv._subir_fichero({"source_drive_file_id": "D-docx"})
ok(_subidas_pdf and _subidas_pdf[-1].endswith(".docx"),
   u"sin PDF generado debería subirse el original: %r" % (_subidas_pdf,))
ok(_srv._subir_fichero({}) is None, u"sin ningún fichero no hay nada que subir")

# ── LOS ANEXOS SE COPIAN A LA CARPETA DEL EXPEDIENTE ────────────
# ⛔⛔ Un expediente puede traer anexos y el pipeline **no los miraba**. La fila 18 real trae
#    SIETE. Publicar sin ellos **no da ningún error**: el documento queda archivado, la página
#    creada y el expediente cerrado, sin los siete ficheros que lo acompañan.
# ⛔ **Copiar, no mover**: el origen es el adjunto del formulario, que es de quien lo subió.
#    Moverlo se lo quita de su Drive. El documento principal sí se mueve; un anexo se copia.
_dr = Drive()
_d = S.Servicios(notion_get=_esq, drive=_dr).copiar_anexos(
    {"annex_drive_file_ids_json": "a1, a2, a3"}, "F-exp")
_copias = [k for a_, k in _dr.diario if a_ == "copy"]
ok(len(_copias) == 3, u"⛔ no copia los tres anexos: %r" % (_dr.diario,))
ok([k["fileId"] for k in _copias] == ["a1", "a2", "a3"],
   u"no copia los ids que trae la fila: %r" % ([k.get("fileId") for k in _copias],))
ok(all(k["body"]["parents"] == ["F-exp"] for k in _copias),
   u"⛔ los anexos no van a la carpeta del expediente: %r" % (_copias[0]["body"],))
ok(all(k.get("supportsAllDrives") is True for k in _copias),
   u"sin `supportsAllDrives` fallaría en una unidad compartida")
ok("update" not in [a_ for a_, _ in _dr.diario],
   u"⛔ MUEVE un anexo en vez de copiarlo: se lo quita del Drive de quien lo subió")
ok(_d.get("annex_copied_count") == 3, u"no devuelve cuántos copió: %r" % (_d,))
ok(_d.get("annex_final_file_ids_json") == '["C-1", "C-2", "C-3"]',
   u"no devuelve los ids de las copias, que es la prueba: %r" % (_d,))

# ⚠️ Los ya copiados no se vuelven a copiar: cada pasada dejaría siete duplicados más.
_dr = Drive()
_d = S.Servicios(notion_get=_esq, drive=_dr).copiar_anexos(
    {"annex_drive_file_ids_json": "a1, a2", "annex_final_file_ids_json": '["C-1","C-2"]',
     "annex_copied_count": "2"}, "F-exp")
ok(_dr.diario == [] and _d == {},
   u"⛔ vuelve a copiar unos anexos ya copiados: cada pasada duplicaría los ficheros")

# Sin anexos, ni sin carpeta, no se toca nada.
ok(S.Servicios(notion_get=_esq, drive=Drive()).copiar_anexos({}, "F-exp") == {},
   u"sin anexos no hay nada que copiar")
_dr = Drive()
ok(S.Servicios(notion_get=_esq, drive=_dr).copiar_anexos(
    {"annex_drive_file_ids_json": "a1"}, "") == {} and _dr.diario == [],
   u"⛔ sin carpeta, las copias colgarían de la raíz de Drive")

# ⛔ Si Drive no devuelve el id de una copia, se para: sin él no queda constancia y la pasada
#    siguiente la volvería a copiar.
class _SinId(Drive):
    def files(self):
        f = Drive.files(self)
        f.copy = lambda **kw: _Ejec({})
        return f


try:
    S.Servicios(notion_get=_esq, drive=_SinId()).copiar_anexos(
        {"annex_drive_file_ids_json": "a1"}, "F-exp")
    _paro = False
except SystemExit as e:
    _paro = "anexo" in str(e)
ok(_paro, u"⛔ Drive sin devolver el id de una copia debería pararse y decirlo")

# ── Y `publicar` los copia ────────────────────────────────
# ⚠️ Probar el método suelto deja ciega la línea que lo llama: es la TERCERA vez hoy.
# ⚠️ Los dobles saben enseñar los marcadores ya puestos: si no, `publicar` se plantaría al
#    releer la página y el caso saldría rojo por un doble pobre, no por el código.
_ANEXOS_PUESTOS = {"results": [
    {"type": "bookmark", "bookmark": {"url": "https://drive.google.com/file/d/C-1/view"}},
    {"type": "bookmark", "bookmark": {"url": "https://drive.google.com/file/d/C-2/view"}}]}
_dr = Drive()
_d = S.Servicios(sheets=Sheets({"get": {"values": RUTAS_VALORES}}), notion=_notion_ok,
                 notion_get=lambda u, token=None: _ANEXOS_PUESTOS,
                 notion_patch=lambda u, c, token=None: {}, drive=_dr).publicar(
                     dict(FILA, annex_drive_file_ids_json="a1, a2"))
ok(_d.get("annex_copied_count") == 2,
   u"⛔ `publicar` no copia los anexos del expediente: %r" % (_d,))
ok([k["body"]["parents"] for a_, k in _dr.diario if a_ == "copy"] == [["F-ya-existe"]] * 2,
   u"los anexos no van a la carpeta del expediente: %r" % (_dr.diario,))

# ⚠️ Y `publicar` los enlaza: probar el método suelto deja ciega la línea que lo llama.
_par = []
_dr = Drive()
S.Servicios(sheets=Sheets({"get": {"values": RUTAS_VALORES}}), notion=_notion_ok,
            notion_get=lambda u, token=None: {"results": [
                {"type": "bookmark",
                 "bookmark": {"url": "https://drive.google.com/file/d/C-1/view"}},
                {"type": "bookmark",
                 "bookmark": {"url": "https://drive.google.com/file/d/C-2/view"}}]},
            notion_patch=lambda u, c, token=None: _par.append(c) or {},
            drive=_dr).publicar(dict(FILA, annex_drive_file_ids_json="a1, a2"))
ok(len(_par) == 1 and len(_par[0]["children"]) == 2,
   u"⛔ `publicar` copia los anexos a Drive y NO los enlaza en la página: %r" % (_par,))

# ── LOS ANEXOS SE ENLAZAN EN LA PÁGINA, Y SE RELEE ──────────────
# ⛔ Copiarlos a Drive no es enlazarlos: un anexo archivado que la página no menciona **no
#    existe** para quien lee el documento en Notion, que es donde el equipo lo lee.
# ⚠️ Y se añaden con **PATCH**, no con POST: `append block children` de Notion es un PATCH, y
#    mandarlo por POST contesta 405 — o sea que los siete anexos se quedarían fuera.
_parches = []


def _patch_ok(url, cuerpo, token=None):
    _parches.append((url, cuerpo))
    return {"results": [{"type": "bookmark", "bookmark": {"url": u}}
                        for u in [b["bookmark"]["url"] for b in cuerpo["children"]]]}


def _hijos_con_anexos(url, token=None):
    return {"results": [{"type": "bookmark",
                         "bookmark": {"url": "https://drive.google.com/file/d/C-1/view"}},
                        {"type": "bookmark",
                         "bookmark": {"url": "https://drive.google.com/file/d/C-2/view"}}]}


_srv = S.Servicios(notion_get=_hijos_con_anexos, notion_patch=_patch_ok)
ok(_srv.enlazar_anexos("p-1", ["C-1", "C-2"]) is True, u"no enlaza los anexos")
ok(len(_parches) == 1, u"debería mandarse UN parche con los dos, no uno por anexo: %r"
   % (len(_parches),))
ok("p-1" in _parches[0][0] and "children" in _parches[0][0],
   u"no pide los hijos de la página: %r" % (_parches[0][0],))
ok(len(_parches[0][1]["children"]) == 2, u"no viajan los dos bloques: %r" % (_parches[0][1],))
ok(_parches[0][1]["children"][0]["type"] == "bookmark", u"el bloque no es un marcador")

# ⛔ Y se RELEE: que el parche conteste bien no prueba que los bloques hayan quedado.
_leidos = []


def _hijos_vacios(url, token=None):
    _leidos.append(url)
    return {"results": []}


try:
    S.Servicios(notion_get=_hijos_vacios, notion_patch=_patch_ok).enlazar_anexos("p-1", ["C-1"])
    _paro = False
except SystemExit as e:
    _paro = "anexo" in str(e)
ok(_paro, u"⛔ el parche contestó bien y los bloques NO están: se da por bueno")
ok(_leidos, u"⛔ no RELEE la página: mandar no es comprobar")

ok(S.Servicios(notion_get=_hijos_con_anexos, notion_patch=_patch_ok)
  .enlazar_anexos("", ["C-1"]) is False, u"sin página no hay dónde enlazar")
ok(S.Servicios(notion_get=_hijos_con_anexos, notion_patch=_patch_ok)
  .enlazar_anexos("p-1", []) is False, u"sin anexos no hay nada que enlazar")

# ── EL RANGO TIENE QUE LLEGAR A TODAS LAS COLUMNAS QUE ALGUIEN LEE ────
# ⛔⛔ El rango era `A1:BZ` — **78 columnas de las 104 que tiene la hoja**. Todo lo de `CA` en
#    adelante no llegaba nunca al código: `replaces_document`, los `annex_*`, `range_end` y
#    **`revisor_field_pendiente`**. Las guardas estaban escritas, probadas y **sin datos**: en la
#    primera pasada real contra Google, la fila 18 salió como «lista para cerrar» — la que existe
#    una guarda entera para NO cerrar — y con `--aplicar` se habría cerrado.
#    ⚠️ El rango y las columnas que se leen viven en ficheros distintos, que es donde nadie mira.
#       Este caso los junta: se descubren por `ast` las cadenas que el código usa como columna y
#       se exige que **todas** caigan dentro del rango, contra la cabecera REAL.
import ast as _ast2
import io as _io2
import re as _re2

# 📏 La cabecera entera de `SOLICITUDES`, leída el 29/09/2026 (`A1:CZ1`): **104 columnas**.
CABECERA_REAL = [
    "request_id", "form_row", "received_at", "form_email", "author_name_raw",
    "author_notion_user_id", "author_email", "title_short", "document_type", "unit_key",
    "unit_label", "subfolder_key", "subfolder_label", "season_label", "season_suffix",
    "reserved_id", "reference", "technical_name", "source_drive_file_id", "source_drive_url",
    "source_filename", "sha256_original", "sha256_corrected", "text_fingerprint",
    "duplicate_status", "duplicate_matches_json", "analysis_json", "executive_summary",
    "quality_issues", "tags_json", "received", "analyzed", "id_reserved",
    "approval_email_sent", "reported", "approved", "rejected", "changes_requested",
    "notion_page_created", "notion_pdf_embedded", "notion_embedding_verified",
    "drive_folder_created", "drive_primary_file_verified", "drive_summary_created",
    "domain_permission_verified", "base_database_registered", "author_confirmation_sent",
    "thread_confirmation_sent", "closed", "approval_thread_id", "approval_message_id",
    "reviewer_public_annotations", "reviewer_internal_annotations",
    "reviewer_discord_instructions", "first_reported_at", "last_reported_at",
    "next_reminder_at", "reminder_count", "notion_page_id", "notion_page_url",
    "drive_folder_id", "drive_folder_url", "drive_primary_file_id", "drive_summary_file_id",
    "base_database_row", "last_error", "retry_count", "updated_at", "decision_at",
    "approved_at", "rejected_at", "changes_requested_at", "partial_alerted_at",
    "next_partial_alert_at", "partial_alert_count", "drive_docx_file_id", "author_name",
    "unit_label", "subfolder_label", "range_start", "range_end", "drive_route_folder_id",
    "context", "submitted_annotations", "replaces_document", "replacement_reference",
    "replacement_reason", "annex_drive_file_ids_json", "annex_source_urls",
    "annex_copied_count", "annex_final_file_ids_json", "source_mime_type",
    "source_size_bytes", "source_md5_drive", "form_response_key", "notion_docx_attached",
    "notion_annex_link_verified", "author_decision_notification_sent",
    "author_decision_notification_message_id", "revisor_field_pendiente",
    "revisor_field_valor", "publication_title_source", "publication_title_review_status",
    "base_database_chip_verified"]
ok(len(CABECERA_REAL) == 104, u"la cabecera medida no son 104: %d" % len(CABECERA_REAL))

_m = _re2.search(r"![A-Z]+\d*:([A-Z]+)", S.RANGO_SOLICITUDES)
ok(_m is not None, u"el rango no tiene forma de rango: %r" % (S.RANGO_SOLICITUDES,))


def _n_col(letras):
    n = 0
    for c in letras:
        n = n * 26 + (ord(c) - 64)
    return n


_hasta = _n_col(_m.group(1)) if _m else 0
ok(_hasta >= 104,
   u"⛔ el rango llega a la columna %d de 104: todo lo de más allá no llega al código, y las "
   u"guardas que lo miran se quedan sin datos" % _hasta)

# ⛔ Y las columnas que el código NOMBRA tienen que existir en esa cabecera y caer dentro.
_COLS = set()
for _mod in ("cierre", "anexos", "sustitucion", "hoja", "evidencias", "pasada"):
    _arb = _ast2.parse(_io2.open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                           _mod + ".py"), encoding="utf-8").read())
    for _n in _ast2.walk(_arb):
        if isinstance(_n, _ast2.Constant) and isinstance(_n.value, str):
            if _n.value in CABECERA_REAL:
                _COLS.add(_n.value)
ok(len(_COLS) >= 25, u"el descubridor ve muy pocas columnas (%d): mediría de mentira" % len(_COLS))
_fuera = sorted(c for c in _COLS if CABECERA_REAL.index(c) + 1 > _hasta)
ok(_fuera == [],
   u"⛔ el código lee columnas que el rango NO trae: %r — la guarda existe y no recibe nada"
   % (_fuera,))

# ── LA FUENTE DE DATOS SE DEDUCE, NO SE PIDE ───────────────────
# ⛔⛔ `NOTION_DATA_SOURCE_ID` era un secreto más que alguien tenía que ir a buscar — y para
#    pedirlo hace falta el token, que GitHub **no devuelve nunca**, así que sacarlo obligaba a
#    rotar una credencial para leer un identificador **que no es secreto**.
#    ✅ El id de la BASE ya está a la vista en el repo (`sync-notion.mjs`), y el de la fuente se
#    deduce de él con la misma llamada que ya se hace para leer las opciones de «Etiquetas».
_ESQ_BASE = {"data_sources": [{"id": "ds-deducida", "name": "Documentos internos"}]}
_pedidas = []


def _get_base(url, token=None):
    _pedidas.append(url)
    return _ESQ_BASE


_g = os.environ.pop("NOTION_DATA_SOURCE_ID", None)
try:
    _srv = S.Servicios(notion_get=_get_base)
    ok(_srv.fuente_de_datos() == "ds-deducida",
       u"⛔ no deduce la fuente a partir del id de la base: %r" % (_srv.fuente_de_datos(),))
    # ⛔ El id va ESCRITO AQUÍ, no leído de la constante: comparar la constante consigo misma
    #    sale verde aunque alguien la cambie por otra base — lo dijo la mutación, que salió ciega.
    #    Este es el de «Documentos internos», el mismo que lleva `sync-notion.mjs` desde antes.
    ok(_pedidas and "11eb0e3a469c80b9969ff0d0e88e2f36" in _pedidas[0],
       u"no pregunta por la base de «Documentos internos»: %r" % (_pedidas,))
    # ⚠️ Una sola vez: una pasada de 40 expedientes no puede preguntarlo 40 veces.
    _antes = len(_pedidas)
    _srv.fuente_de_datos()
    ok(len(_pedidas) == _antes, u"⚠️ lo vuelve a preguntar en cada llamada")

    # ⛔ Con VARIAS fuentes no se adivina: publicar en la que no es reparte la base en dos.
    _srv2 = S.Servicios(notion_get=lambda u, token=None: {"data_sources": [
        {"id": "a", "name": "una"}, {"id": "b", "name": "otra"}]})
    try:
        _srv2.fuente_de_datos()
        _paro = False
    except SystemExit as e:
        _paro = "2" in str(e) and "NOTION_DATA_SOURCE_ID" in str(e)
    ok(_paro, u"⛔ con dos fuentes elige una a dedo en vez de pedir que se diga cuál")

    # ⛔ Y si Notion no contesta lo que se espera, se para: publicar sin saber en qué base
    #    crea la página donde no toca, y eso no se deshace.
    for _malo in ({}, {"data_sources": []}, {"object": "error", "code": "unauthorized"}):
        try:
            S.Servicios(notion_get=lambda u, token=None, _m=_malo: _m).fuente_de_datos()
            _paro = False
        except SystemExit:
            _paro = True
        ok(_paro, u"⛔ con la respuesta %r debería pararse y decirlo" % (_malo,))
finally:
    if _g is not None:
        os.environ["NOTION_DATA_SOURCE_ID"] = _g

    # ⚠️ Y `publicar` la deduce sola: sin este caso, la línea que la llama sale CIEGA — el
    #    fixture trae `notion_data_source_id` y nunca se llegaba a preguntar.
    _dr = Drive()
    _vistos = []

    def _get_pub(url, token=None):
        _vistos.append(url)
        return _ESQ_BASE if "/databases/" in url else {}

    _fila_sin = dict(FILA)
    _fila_sin.pop("notion_data_source_id", None)
    _cuerpos = []
    S.Servicios(sheets=Sheets({"get": {"values": RUTAS_VALORES}}),
                notion=lambda u, c, token=None: _cuerpos.append(c) or {"id": "p", "url": "u"},
                notion_get=_get_pub, drive=_dr).publicar(_fila_sin)
    ok(_cuerpos and _cuerpos[0]["parent"]["data_source_id"] == "ds-deducida",
       u"⛔ `publicar` no deduce la fuente: publicaría sin saber en qué base: %r"
       % (_cuerpos[0].get("parent") if _cuerpos else None,))

# ⚠️ Y la variable, si está puesta, MANDA: es la salida de emergencia si algún día la base
#    tiene dos fuentes o hay que publicar en otra.
os.environ["NOTION_DATA_SOURCE_ID"] = "ds-a-mano"
try:
    _pedidas2 = []
    ok(S.Servicios(notion_get=lambda u, token=None: _pedidas2.append(u) or _ESQ_BASE)
       .fuente_de_datos() == "ds-a-mano", u"la variable debería mandar sobre lo deducido")
    ok(_pedidas2 == [], u"⚠️ con la variable puesta no hace falta preguntarle nada a Notion")
finally:
    del os.environ["NOTION_DATA_SOURCE_ID"]

# ── LA VERSIÓN DE LA API Y LA FORMA DEL CUERPO TIENEN QUE CUADRAR ─────
# ⛔⛔ `notion_api.cuerpo_pagina` manda `parent = {"type": "data_source_id", …}`, que es la
#    forma de las bases **multi-fuente**; esa forma **no existe** en `2022-06-28`, donde el
#    padre es `database_id`. Con las dos en desacuerdo, el primer documento que se publique se
#    va con un **400** — y no había dónde notarlo, porque el cuerpo se construye en un módulo
#    y la cabecera se pone en otro. Este caso lee **las dos cosas a la vez**.
# ⚠️ `scripts/sync-notion.mjs` se queda en `2022-06-28` a propósito: consulta
#    `/v1/databases/{id}/query`, que es de esa época. Dos clientes, dos trabajos.
_c, _ = NA.cuerpo_pagina("ds-1", {"Título": u"x"})
ok(_c["parent"]["type"] == "data_source_id",
   u"si el padre deja de ser `data_source_id`, esta comprobación cambia de tema: %r"
   % (_c["parent"],))
ok(S.NOTION_VERSION >= "2025-09-03",
   u"⛔ el cuerpo usa `data_source_id` y la cabecera dice %r: el primer documento que se "
   u"publique se va con un 400" % (S.NOTION_VERSION,))
ok("2022-06-28" < "2025-09-03" < "2026-01-01",
   u"la comparación de versiones por texto no ordena: hace falta otra forma")

# ── LAS OPCIONES QUE YA EXISTEN, PARA NO DUPLICARLAS ──────────────
# ⛔⛔ `casar_etiquetas` sabe reusar la opción que ya hay ignorando caja y tildes —medido:
#    **7 de 48** etiquetas del modelo duplicaban una existente así—, pero sólo si alguien le
#    pasa la lista. `publicar` no se la pasaba: la máquina entera estaba **escrita y muerta**,
#    y cada `Python` habría creado una opción al lado de `python` en una propiedad que ya
#    tiene **183**.
_ESQUEMA = {"properties": {"Etiquetas": {"type": "multi_select", "multi_select": {
    "options": [{"name": u"python"}, {"name": u"informe"}, {"name": u"simulacion"}]}}}}
_leidas = []


def _get_esquema(url, token=None):
    _leidas.append(url)
    return _ESQUEMA


_srv = S.Servicios(notion_get=_get_esquema)
ok(_srv.opciones_etiquetas("ds-1") == [u"python", u"informe", u"simulacion"],
   u"no saca las opciones que ya tiene «Etiquetas»: %r" % (_srv.opciones_etiquetas("ds-1"),))
ok(_leidas and "ds-1" in _leidas[0] and "data_sources" in _leidas[0],
   u"no pide el esquema de la fuente de datos: %r" % (_leidas,))
# ⚠️ Se pide UNA vez: una pasada de 40 expedientes no puede leer el esquema 40 veces.
_antes = len(_leidas)
_srv.opciones_etiquetas("ds-1")
ok(len(_leidas) == _antes, u"⚠️ relee el esquema en cada llamada: %d lecturas" % len(_leidas))


def _get_revienta(url, token=None):
    raise RuntimeError("Notion no contesta")


ok(S.Servicios(notion_get=_get_revienta).opciones_etiquetas("ds-1") == [],
   u"⛔ un fallo leyendo el esquema no debe impedir publicar")
ok(S.Servicios(notion_get=lambda u, token=None: {}).opciones_etiquetas("ds-1") == [],
   u"un esquema sin propiedades debería dar lista vacía, no reventar")
ok(S.Servicios(notion_get=_get_esquema).opciones_etiquetas("") == [],
   u"sin id de fuente no hay a quién preguntar")

# ⚠️ Y `publicar` se las PASA: probar el método suelto deja ciega la línea que lo llama.
_ped_etq = []


def _notion_mira(url, cuerpo, token=None):
    _ped_etq.append(cuerpo)
    return {"id": "p-1", "url": "https://notion/x"}


S.Servicios(sheets=Sheets({"get": {"values": RUTAS_VALORES}}), notion=_notion_mira,
            notion_get=_get_esquema, drive=Drive()).publicar(
                dict(FILA, tags_json=u'["Python","CFD"]'))
_etq = [x["name"] for x in _ped_etq[0]["properties"]["Etiquetas"]["multi_select"]]
ok(_etq == [u"python", u"CFD"],
   u"⛔ `publicar` no casa las etiquetas con las opciones que ya hay: %r" % (_etq,))

# ⛔⛔ Y LO ÚLTIMO: que el banco no haya intentado hablar con Notion ni una vez. Va al final
#    porque tiene que ver **todas** las llamadas, y es lo que impide que la próxima vez que
#    alguien meta una lectura dentro de un método ya probado, el banco se vaya a la red callando.
ok(_intentos_red == [], u"⛔ el banco ha intentado LEER de Notion %d vez/veces: %r"
   % (len(_intentos_red), _intentos_red[:3]))

print("%d comprobaciones" % hechas[0])
if fallos:
    print("\n%d ROJO(S):" % len(fallos))
    for f_ in fallos:
        print("  - %s" % f_)
    sys.exit(1)
print("verde")
