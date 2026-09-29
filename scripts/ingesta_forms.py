#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Paso 1 del pipeline documental: las respuestas del formulario entran en `SOLICITUDES`.

Por qué existe
--------------
Hasta hoy este paso lo hacía Cowork a mano. `check_pipeline_status.py` lo **detecta**
(«N filas del formulario sin ingerir todavía») pero no lo hace, así que las filas se quedaban
esperando a que alguien corriera una pasada. Medido el 28/09: una respuesta enviada a las 23:48
seguía sin ingerir a la mañana siguiente, y el caso peor registrado esperó **doce horas**.

No hay nada que juzgar en este paso: leer una fila, traducir dos etiquetas a una ruta, reservar
el siguiente número libre y escribir. Es contabilidad, y la contabilidad es código.

Lo que NO hace, a propósito
---------------------------
No analiza el documento, no lo resume, no lo mueve de sitio y no toca Notion. Sólo registra la
solicitud y reserva su identificador. Todo lo demás sigue igual.

Cómo se prueba
--------------
`python scripts/test_ingesta_forms.py` — las funciones de abajo son puras y se prueban sin red
ni credenciales. La parte que habla con Google va al final, aislada y fina a propósito.
"""
import hashlib
import os
import re
import sys
from datetime import datetime, timedelta, timezone

for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding="utf-8")
    except Exception:  # pragma: no cover - consolas antiguas
        pass

# ⚠️ Mismo patrón que el resto de scripts del repo: si el runner no trae tzdata, `None` y quien
#    lo use decide. No se inventa un desfase fijo, que en verano y en invierno no es el mismo.
try:
    from zoneinfo import ZoneInfo
    _MADRID_TZ = ZoneInfo("Europe/Madrid")
except Exception:  # pragma: no cover
    _MADRID_TZ = None


# ── 1 · la marca temporal del formulario ────────────────────────────────────────────────────
def fecha_form(valor):
    """La columna A de la hoja de respuestas: "DD/MM/AAAA HH:MM:SS", hora local de Madrid.

    ⛔ NO es ISO, y confundirlo ya costó una señal muerta: `form_responses_novedad` llevaba
    desde que se escribió devolviendo `False` siempre porque la parseaba con
    `datetime.fromisoformat`, que con este formato devuelve `None`. Aquí se intenta ISO primero
    por si la hoja cambia algún día, y se cae al formato de Forms después.

    Devuelve `None` si no lo entiende. `None` es «no lo sé», no «hoy».
    """
    v = str(valor or "").strip()
    if not v:
        return None
    try:
        iso = v[:-1] + "+00:00" if v.endswith("Z") else v
        d = datetime.fromisoformat(iso)
        return d if d.tzinfo else d.replace(tzinfo=_MADRID_TZ or timezone.utc)
    except Exception:  # noqa: BLE001
        pass
    try:
        naive = datetime.strptime(v, "%d/%m/%Y %H:%M:%S")
    except Exception:  # noqa: BLE001
        return None
    return naive.replace(tzinfo=_MADRID_TZ or timezone.utc)


# ── 2 · la temporada ────────────────────────────────────────────────────────────────────────
def temporada_de(fecha):
    """La temporada de una fecha: («2026/27», «27»). Corta el **1 de septiembre**.

    ⛔ Los dos dígitos son el año en que la temporada **ACABA**, no el año natural. No lo decía
    ningún documento; se midió con el caso que distingue las dos lecturas: `Tabla_S-4301_25`,
    creada el 29/10/2024 — año natural 24, sufijo 25. Confirmado después por Cowork.

    ⚠️ Del 1 de septiembre al 31 de diciembre las dos lecturas divergen. El resto del año
    coinciden, que es justo lo que hace que un error aquí no dé síntomas ocho meses de doce.
    """
    ini = fecha.year if fecha.month >= 9 else fecha.year - 1
    return ("%d/%02d" % (ini, (ini + 1) % 100), "%02d" % ((ini + 1) % 100))


# ── 3 · de las etiquetas del formulario a la ruta ───────────────────────────────────────────
_CIFRAS = re.compile(r"(\d+)")


def cifras_de_etiqueta(etiqueta):
    """Los números que lleva dentro una etiqueta del formulario.

    Las etiquetas están hechas para esto: «Propulsión (4)», «General - 0», «SRAD - 1»,
    «Actas - (3/4)». El número ES la traducción, así que no hay que adivinar nada por el
    nombre — y menos mal, porque los nombres NO coinciden: la opción «SRAD» del Form fue
    durante meses la ruta `informes_tecnicos` en `RUTAS`.
    """
    return [int(n) for n in _CIFRAS.findall(str(etiqueta or ""))]


def ruta_de(unidad_label, subcarpeta_label, rutas):
    """La fila de `RUTAS` que corresponde a lo que se marcó en el formulario, o `None`.

    ⛔ SE EMPAREJA POR EL RANGO, NUNCA POR LA SEGUNDA CIFRA. `uct/actas` va de 6301 a 6499 y
    el común de Aviónica de 2001 a 2199: **dos rutas ocupan dos dígitos cada una**, así que
    deducir la subcarpeta del dígito daría falsos justo en las actas, que son lo más frecuente.
    Se construye el número mínimo de la ruta (unidad + subcarpeta + 01) y se busca el rango
    activo que lo contenga.

    ⚠️ Devuelve `None` si no encuentra una sola candidata. Una ruta adivinada archiva el
    documento en el sitio equivocado sin dar error, que es el fallo caro de todo esto.
    """
    cu = cifras_de_etiqueta(unidad_label)
    cs = cifras_de_etiqueta(subcarpeta_label)
    if not cu or not cs:
        return None
    objetivo = cu[0] * 1000 + cs[0] * 100 + 1
    candidatas = [r for r in rutas
                  if str(r.get("active", "")).strip().upper() in ("TRUE", "VERDADERO", "1")
                  and _entero(r.get("range_start")) is not None
                  and _entero(r.get("range_start")) <= objetivo <= _entero(r.get("range_end"))]
    return candidatas[0] if len(candidatas) == 1 else None


def _entero(v):
    try:
        return int(str(v).strip())
    except Exception:  # noqa: BLE001
        return None


# ── 4 · el siguiente identificador libre ────────────────────────────────────────────────────
def siguiente_id(ruta, reservas, sufijo):
    """El primer número libre del rango de esa ruta para esa temporada, o `None` si se agotó.

    ⛔ SE AGOTA, NO SE DA LA VUELTA. Un rango lleno significa que hay que ampliarlo, no que se
    reutilice un número: dos documentos con la misma referencia son un upsert que se come al
    primero, y la referencia es la clave de todo el archivo.

    ⚠️ Cuenta sólo las reservas **de esa temporada** (`season_suffix`) y las que no están
    liberadas: los rangos se reparten por temporada, así que el 6301 del curso pasado no ocupa
    el 6301 de éste.
    """
    ini, fin = _entero(ruta.get("range_start")), _entero(ruta.get("range_end"))
    if ini is None or fin is None:
        return None
    ocupados = set()
    for r in reservas or []:
        if str(r.get("season_suffix", "")).strip() != str(sufijo):
            continue
        if str(r.get("released", "")).strip().upper() in ("TRUE", "VERDADERO", "1"):
            continue
        n = _entero(r.get("reserved_id"))
        if n is not None:
            ocupados.add(n)
    for n in range(ini, fin + 1):
        if n not in ocupados:
            return n
    return None


# ── 5 · la referencia ───────────────────────────────────────────────────────────────────────
_PALABRA = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]+")


def referencia(document_type, reserved_id, sufijo):
    """`<Tipo>_S-<NNNN>_<YY>`, la clave de upsert de todo el pipeline.

    ⚠️ El prefijo es la **primera palabra** del tipo: «Informe de Subsistema» da `Informe`.
    Y el tipo viene del formulario, que ofrece doce — no los cuatro que decía la documentación.
    """
    palabras = _PALABRA.findall(str(document_type or ""))
    if not palabras or reserved_id is None:
        return None
    return "%s_S-%s_%s" % (palabras[0], reserved_id, sufijo)


# ── 6 · el identificador de la solicitud ────────────────────────────────────────────────────
def request_id(fecha, semilla):
    """`SOL-DOC-<AAAAMMDD>-<HHMMSS>-<8 caracteres>`, como los que ya hay en la hoja.

    ⛔ La hora sale de la **fecha de la respuesta**, no del reloj de la pasada. Medido en las
    filas existentes: en 6 de 7 el `request_id` lleva la hora exacta del envío. Usar el reloj
    haría que una fila ingerida tarde pareciera enviada tarde, y ese es justo el dato con el
    que se mide si el pipeline va con retraso.
    """
    if fecha is None:
        return None
    h = hashlib.sha1(str(semilla).encode("utf-8")).hexdigest()[:8].upper()
    return "SOL-DOC-%s-%s-%s" % (fecha.strftime("%Y%m%d"), fecha.strftime("%H%M%S"), h)


# ── 7 · el fichero adjunto ──────────────────────────────────────────────────────────────────
_ID_DRIVE = re.compile(r"[?&]id=([A-Za-z0-9_-]{10,})")


def file_id_de(url):
    """El id de Drive que hay dentro del enlace que escribe Forms.

    Forms lo escribe como `https://drive.google.com/open?id=XXXX`. Se acepta también la forma
    `/file/d/XXXX/` por si cambia. Devuelve `None` si no hay ninguno: un enlace que no se
    entiende no es un fichero vacío.
    """
    s = str(url or "")
    m = _ID_DRIVE.search(s)
    if m:
        return m.group(1)
    m = re.search(r"/file/d/([A-Za-z0-9_-]{10,})", s)
    return m.group(1) if m else None


def ids_de_lista(texto):
    """Varios enlaces separados por comas (la columna de anexos). Lista, quizá vacía."""
    out = []
    for trozo in str(texto or "").split(","):
        fid = file_id_de(trozo)
        if fid:
            out.append(fid)
    return out


# ── 8 · la fila que se escribe ──────────────────────────────────────────────────────────────
COLUMNAS = [
    "request_id", "form_row", "received_at", "form_email", "author_name_raw",
    "author_notion_user_id", "author_email", "title_short", "document_type",
    "unit_key", "unit_label", "subfolder_key", "subfolder_label",
    "season_label", "season_suffix", "reserved_id", "reference", "technical_name",
    "source_drive_file_id", "source_drive_url", "source_filename",
]


# ⛔ Lo que el formulario acepta como «sí» en la pregunta de sustitución. Se mira **sin tildes
#    y sin caja**, porque la opción del Form se ha reescrito más de una vez y las respuestas
#    viejas conservan la grafía de entonces.
_SI = ("si", "sí", "yes", "true", "1")


def _plano(t):
    import unicodedata                                                   # noqa: PLC0415
    t = unicodedata.normalize("NFD", str(t or "").strip().lower())
    return u"".join(c for c in t if unicodedata.category(c) != "Mn")


# ⛔⛔ LA CABECERA REAL de la hoja de respuestas, medida el 29/09/2026
#    (`1lpyO2P4H39WB3T8Kw64PSHU-iiBozP1H1aK0SOuxwJQ`). El formulario **no escribe claves**:
#    escribe las preguntas tal cual, así que el mapeo va aquí y no se adivina.
#    ⚠️ Y **la subcarpeta son CINCO columnas**, una por unidad: la respuesta está en la que
#       corresponda y las otras cuatro vienen vacías. Leer «la» columna de subcarpeta no existe.
PREGUNTAS = {
    "Marca temporal": "marca_temporal",
    "Dirección de correo electrónico": "form_email",
    "Nombre y apellidos": "author_name_raw",
    "Título breve y descriptivo": "title_short",
    "Tipo de documento": "document_type",
    "Subsistema o unidad": "unit_label",
    "Adjunta aquí el documento": "source_drive_url",
    "Adjunta aquí los anexos": "annex_source_urls",
    "Contexto para la revisión": "context",
    "Anotaciones propuestas": "submitted_annotations",
    "¿Sustituye o revisa otro documento?": "sustituye",
    "Indica la referencia del archivo que deseas sustituir": "referencia_sustituida",
    "Motivo de la sustitución o revisión": "motivo_sustitucion",
}

_SUBCARPETA = "Elige la subcarpeta"


def respuesta_de(cabecera, fila, n_fila):
    """Una fila de la hoja de respuestas, traducida a las claves que usa el pipeline.

    ⚠️ `form_row` es **el número de fila de la hoja**, no una columna: es lo que ata la
    solicitud a su respuesta y lo que impide re-ingerir lo ya ingerido.
    ⛔ La subcarpeta sale de la **única** de las cinco columnas que venga rellena. Si vienen
    dos, no se elige una: se deja vacía y que lo mire una persona — archivar en la carpeta
    equivocada no da ningún error.
    """
    cab = [str(c or "").strip() for c in (cabecera or [])]
    vals = list(fila or []) + [""] * max(0, len(cab) - len(list(fila or [])))
    out = {"form_row": str(n_fila)}
    subs = []
    for c, v in zip(cab, vals):
        v = str(v or "").strip()
        if c.startswith(_SUBCARPETA):
            if v:
                subs.append(v)
            continue
        clave = PREGUNTAS.get(c)
        if clave:
            out[clave] = v
    out["subfolder_label"] = subs[0] if len(subs) == 1 else ""
    if len(subs) > 1:
        out["motivo_error"] = (u"la respuesta marca %d subcarpetas (%s): no se elige una a "
                               u"dedo, archivaría en la que no es sin dar ningún error"
                               % (len(subs), u", ".join(subs)))
    out["source_filename"] = out.get("source_filename") or ""
    return out


def sustitucion_de(respuesta, solicitudes):
    """Qué sustituye esta respuesta, o `None` si no sustituye nada.

    ⛔⛔ EL CAMINO QUE NO EXISTÍA. Daniel, 29/09: *«que se pueda poner la referencia ya utilizada
    y que se sustituya»*. El formulario lo pregunta desde siempre — «¿Sustituye o revisa otro
    documento?», «Indica la referencia del archivo que deseas sustituir» y «Motivo» — y nadie
    lo leía: `siguiente_id` coge siempre el siguiente libre, así que una reentrega se llevaba un
    **número nuevo** y quedaba como un documento distinto del que venía a sustituir.

    Devuelve `{reserved_id, replaces_document, replacement_reference, replacement_reason}` — y
    `motivo_error` cuando dice sustituir algo que **no se puede atar**.
    ⚠️ Con `motivo_error` **NO trae `reserved_id`**: no se inventa un número ni se deja pasar
    como documento nuevo. Reservar otro número para algo que dice ser una reentrega es
    exactamente cómo se acaba con dos expedientes del mismo documento.
    """
    respuesta = respuesta if isinstance(respuesta, dict) else {}
    if _plano(respuesta.get("sustituye")) not in _SI:
        return None

    ref = str(respuesta.get("referencia_sustituida") or "").strip()
    motivo = str(respuesta.get("motivo_sustitucion") or "").strip()
    if not ref:
        return {"motivo_error": u"dice sustituir otro documento y no dice cuál: sin la "
                                u"referencia no hay a qué atarlo, y darle número nuevo dejaría "
                                u"dos expedientes del mismo documento",
                "replacement_reason": motivo}

    for s_ in (solicitudes or []):
        if not isinstance(s_, dict):
            continue
        if str(s_.get("reference") or "").strip() != ref:
            continue
        return {"reserved_id": str(s_.get("reserved_id") or "").strip(),
                "replaces_document": str(s_.get("request_id") or "").strip(),
                "replacement_reference": ref,
                "replacement_reason": motivo}

    return {"motivo_error": u"dice sustituir a %r y no hay ningún expediente con esa "
                            u"referencia: o está mal escrita o el original no se ingirió nunca"
                            % ref,
            "replacement_reference": ref, "replacement_reason": motivo}


def fila_solicitud(respuesta, ruta, reserved_id, sufijo, season_label, fecha):
    """El diccionario que se vuelca en `SOLICITUDES`. Sin efectos: sólo construye.

    ⚠️ `received` y `id_reserved` NO se ponen aquí: los escribe quien confirma que la escritura
    fue bien. Marcar «recibido» en la misma operación que aún puede fallar es como se acaba con
    una fila que dice que está hecha algo que no se hizo.
    """
    ref = referencia(respuesta.get("document_type"), reserved_id, sufijo)
    return {
        "request_id": request_id(fecha, "%s|%s" % (respuesta.get("form_row"), ref)),
        "form_row": respuesta.get("form_row"),
        "received_at": fecha.isoformat() if fecha else "",
        "form_email": (respuesta.get("form_email") or "").strip().lower(),
        "author_name_raw": respuesta.get("author_name_raw") or "",
        "author_notion_user_id": "",
        "author_email": (respuesta.get("form_email") or "").strip().lower(),
        "title_short": respuesta.get("title_short") or "",
        "document_type": respuesta.get("document_type") or "",
        "unit_key": ruta.get("unit_key"),
        "unit_label": respuesta.get("unit_label") or "",
        "subfolder_key": ruta.get("subfolder_key"),
        "subfolder_label": respuesta.get("subfolder_label") or "",
        "season_label": season_label,
        "season_suffix": sufijo,
        "reserved_id": reserved_id,
        "reference": ref,
        "technical_name": ref,
        "source_drive_file_id": file_id_de(respuesta.get("source_drive_url")),
        "source_drive_url": respuesta.get("source_drive_url") or "",
        "source_filename": respuesta.get("source_filename") or "",
    }


def pendientes(respuestas, solicitudes):
    """Las respuestas cuyo `form_row` todavía no está en `SOLICITUDES`.

    ⚠️ Se compara como TEXTO y recortado: en la hoja los números llegan unas veces como `17` y
    otras como `'17 `, y una comparación estricta volvería a ingerir lo ya ingerido — que con
    un upsert por `ref` no se nota hasta que alguien cuenta las filas.
    """
    ya = set(str(s.get("form_row", "")).strip() for s in (solicitudes or []))
    return [r for r in (respuestas or []) if str(r.get("form_row", "")).strip() not in ya]


if __name__ == "__main__":  # pragma: no cover - la parte que habla con Google
    print("Este módulo es la lógica pura del Paso 1. El conector vive en el workflow;\n"
          "para probarlo: python scripts/test_ingesta_forms.py")
