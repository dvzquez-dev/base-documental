# Solaris Document Console

[![GitHub Pages](https://img.shields.io/badge/GitHub%20Pages-static%20site-222?logo=github)](https://dvzquez-dev.github.io/base-documental/)
[![Notion Sync](https://img.shields.io/badge/Notion-sync%20automático-000?logo=notion)](#sincronización-desde-notion)
[![Public JSON](https://img.shields.io/badge/API-JSON%20público-blue)](#endpoints-públicos)
[![No Backend](https://img.shields.io/badge/backend-no%20serverless%2C%20no%20API-green)](#arquitectura)

Consola documental estática para el archivo técnico del equipo **Solaris Rocketry Team · UVigo Aerotech**.

La aplicación reúne en una sola web los documentos internos y los datasheets de electrónica mantenidos en Notion. El navegador no accede directamente a Notion: GitHub Actions sincroniza las bases privadas, genera JSON estático y GitHub Pages publica la interfaz y los endpoints de consulta.

**Web pública:**

```text
https://dvzquez-dev.github.io/base-documental/
```

---

## Índice

- [Qué es](#qué-es)
- [Arquitectura](#arquitectura)
- [Sincronización desde Notion](#sincronización-desde-notion)
- [Endpoints públicos](#endpoints-públicos)
- [Estructura de datos](#estructura-de-datos)
- [Publicación temporal de PDFs](#publicación-temporal-de-pdfs)
- [Secretos necesarios](#secretos-necesarios)
- [Desarrollo local](#desarrollo-local)
- [Estructura del repositorio](#estructura-del-repositorio)
- [Limitaciones](#limitaciones)
- [Mantenimiento](#mantenimiento)

---

## Qué es

Este repositorio actúa como un **espejo público de solo lectura** de parte del archivo técnico de Solaris.

La web permite consultar:

- informes,
- memorias,
- manuales,
- tablas,
- carpetas documentales,
- datasheets y componentes de electrónica.

La fuente de verdad sigue siendo **Notion**. Este repositorio solo publica una copia ligera de metadatos en formato JSON para que la consulta sea rápida, barata y usable desde navegador, agentes o automatizaciones externas.

---

## Arquitectura

```text
Notion privado
  ├─ Base: Documentos internos
  └─ Base: Datasheets Electrónica
        │
        │ GitHub Actions
        ▼
scripts/sync-notion.mjs
        │
        ▼
data/docs.json
data/datasheets.json
data/meta.json
data/all.json
        │
        │ GitHub Pages
        ▼
index.html
        │
        ▼
Web pública + endpoints JSON
```

La clave del diseño es esta:

> El token de Notion nunca llega al navegador ni a ningún cliente externo.

Solo GitHub Actions tiene acceso al secreto `NOTION_TOKEN`. La web pública consume archivos JSON ya generados.

---

## Interfaz web

La interfaz principal está en:

```text
index.html
```

Es una web estática, sin framework y sin backend propio. Al cargar, hace `fetch()` de:

```text
data/docs.json
data/datasheets.json
data/meta.json
```

Con esos datos renderiza:

- buscador unificado de documentos,
- filtros por temporada,
- filtros por tipo documental,
- filtros por etiquetas,
- agrupación por subsistema,
- tarjetas de datasheets,
- enlaces a Notion,
- enlaces a datasheets externos cuando existen,
- gráfico de actividad documental mensual.

---

## Sincronización desde Notion

El workflow principal está en:

```text
.github/workflows/sync.yml
```

Se ejecuta de dos formas:

1. Automáticamente mediante `schedule`.
2. Manualmente o desde un cron externo mediante `workflow_dispatch`.

El flujo real es:

```text
GitHub Actions
  ↓
checkout del repositorio
  ↓
setup de Node LTS
  ↓
node scripts/sync-notion.mjs
  ↓
regeneración de data/*.json
  ↓
commit automático si hay cambios
  ↓
push a main
  ↓
GitHub Pages sirve la nueva versión
```

El script encargado es:

```text
scripts/sync-notion.mjs
```

Ese script:

- lee `NOTION_TOKEN` desde los secrets del repositorio,
- consulta la base de documentos internos,
- consulta la base de datasheets de electrónica,
- pagina resultados de Notion con `page_size: 100`,
- normaliza las propiedades relevantes,
- ordena documentos por fecha descendente,
- ordena datasheets por nombre,
- genera los JSON finales en `data/`.

Los archivos que se commitean automáticamente son:

```text
data/docs.json
data/datasheets.json
data/meta.json
data/all.json
```

---

## Endpoints públicos

Los datos publicados se pueden leer con una petición `GET` normal, sin autenticación.

```text
https://dvzquez-dev.github.io/base-documental/data/docs.json
https://dvzquez-dev.github.io/base-documental/data/datasheets.json
https://dvzquez-dev.github.io/base-documental/data/meta.json
https://dvzquez-dev.github.io/base-documental/data/all.json
```

Ejemplo:

```bash
curl -s https://dvzquez-dev.github.io/base-documental/data/meta.json | jq
```

Uso recomendado:

| Archivo | Uso |
|---|---|
| `meta.json` | Comprobar última sincronización y contadores |
| `docs.json` | Buscar documentos internos |
| `datasheets.json` | Buscar componentes y datasheets |
| `all.json` | Consumir todo en una sola petición |

Estos endpoints son útiles para:

- n8n,
- Zapier,
- Make,
- scripts propios,
- Google Sheets,
- agentes de IA con navegación web,
- paneles externos,
- automatizaciones de documentación.

---

## Estructura de datos

### `data/docs.json`

Array de documentos internos.

Ejemplo aproximado:

```json
{
  "id": 2009,
  "docCode": "Informe_S-2009_26",
  "subsystem": "elec",
  "title": "Informe mayo electrónica",
  "tipo": "Informe",
  "season": "2025/26",
  "tags": ["Electrónica", "EuRoC"],
  "date": "2026-07-06",
  "uploadedAt": "2026-07-06T18:23:00.000Z",
  "url": "https://app.notion.com/..."
}
```

Campos importantes:

| Campo | Descripción |
|---|---|
| `id` | ID numérico interno. No debe asumirse único entre temporadas. |
| `docCode` | Código documental único cuando existe. Es el identificador recomendado. |
| `subsystem` | Código corto del subsistema. |
| `title` | Título visible del documento. Puede repetirse. |
| `tipo` | Tipo documental. |
| `season` | Temporada o curso. |
| `tags` | Etiquetas libres de Notion. |
| `date` | Fecha de subida en formato `YYYY-MM-DD`. |
| `uploadedAt` | Fecha y hora exactas en ISO 8601. |
| `url` | Enlace a la página original de Notion. |

Códigos de subsistema usados por el front-end:

| Código | Subsistema |
|---|---|
| `general` | Solaris |
| `prop` | Propulsión |
| `struct` | Estructuras y Aerodinámica |
| `dyn` | Dinámica y Control |
| `elec` | Electrónica |
| `coord` | Coordinación Técnica |

---

### `data/datasheets.json`

Array de componentes y datasheets de electrónica.

Ejemplo aproximado:

```json
{
  "name": "BNO055",
  "tipo": "IMU",
  "fabricante": "Bosch",
  "desc": "Sensor inercial",
  "uso": "Aviónica",
  "proyectos": ["Solaris"],
  "interfaces": ["I2C", "UART"],
  "enlace": "https://...",
  "url": "https://app.notion.com/..."
}
```

Campos:

| Campo | Descripción |
|---|---|
| `name` | Nombre del componente. |
| `tipo` | Tipo de componente. |
| `fabricante` | Fabricante. |
| `desc` | Descripción o notas. |
| `uso` | Uso dentro del proyecto o placa. |
| `proyectos` | Proyectos asociados. |
| `interfaces` | Interfaces eléctricas o de comunicación. |
| `enlace` | Datasheet externo, normalmente del fabricante. |
| `url` | Página original en Notion. |

---

### `data/meta.json`

Metadatos de sincronización.

```json
{
  "updatedAt": "2026-07-08T10:36:19.274Z",
  "docsCount": 133,
  "datasheetsCount": 11,
  "source": "notion-sync"
}
```

Sirve para saber si el índice ha cambiado sin descargar todo `all.json`.

---

### `data/all.json`

Archivo combinado para automatizaciones.

```json
{
  "meta": {},
  "docs": [],
  "datasheets": []
}
```

Está pensado para consumidores externos que prefieren una sola petición HTTP.

---

## `llms.txt`

El archivo:

```text
llms.txt
```

documenta los endpoints públicos para agentes de IA y herramientas automáticas.

Su función es explicar:

- qué datos existen,
- dónde están los JSON,
- qué esquema tienen,
- qué limitaciones tiene el índice,
- cuándo conviene leer el JSON público,
- cuándo hace falta consultar Notion directamente.

Importante:

> `llms.txt` no concede permisos especiales. Solo documenta recursos públicos.

---

## Publicación temporal de PDFs

Además del índice documental, este repositorio contiene un flujo secundario para publicar PDFs temporales en GitHub Pages.

Workflow:

```text
.github/workflows/publish-temp-pdfs.yml
```

Script:

```text
scripts/publish_temp_pdfs.py
```

Este flujo se usa para exponer temporalmente PDFs que deben ser procesados o embebidos por herramientas externas.

Arquitectura:

```text
Google Sheet: COLA_PUBLICACION_TEMPORAL_PDF
        │
        │ GitHub Actions
        ▼
scripts/publish_temp_pdfs.py
        │
        ├─ lee filas pendientes
        ├─ descarga PDF desde Google Drive staging
        ├─ escribe el PDF en pdfs/
        ├─ marca la fila como PUBLICADO
        ├─ genera public_url
        └─ retira PDFs expirados o ya embebidos
```

La URL pública base de los PDFs es:

```text
https://dvzquez-dev.github.io/base-documental/pdfs
```

Por defecto, los PDFs caducan tras:

```text
48 horas
```

---

## Estados del flujo de PDFs

La hoja de control usa estos estados:

| Estado | Significado |
|---|---|
| `PENDIENTE` | El PDF debe publicarse. |
| `PUBLICADO` | El PDF está servido públicamente desde GitHub Pages. |
| `EMBEBIDO_CONFIRMADO` | La herramienta externa ya terminó de usar el PDF. |
| `EXPIRADO` | El PDF ya fue retirado. |
| `ERROR` | Hubo un fallo durante publicación o limpieza. |

### `PENDIENTE`

El script:

1. descarga el PDF desde Drive,
2. lo guarda en `pdfs/`,
3. escribe la URL pública en la hoja,
4. calcula `fecha_expira`,
5. cambia el estado a `PUBLICADO`.

### `PUBLICADO`

El PDF sigue accesible por URL pública.

Si `fecha_expira` ya pasó, el script:

1. borra el PDF de `pdfs/`,
2. cambia el estado a `EXPIRADO`.

### `EMBEBIDO_CONFIRMADO`

La herramienta externa ya terminó de usar el PDF.

El script:

1. borra el PDF del repo,
2. mueve la copia de staging en Drive a la papelera,
3. cambia el estado a `EXPIRADO`.

### `ERROR`

Indica que la publicación o limpieza falló. La columna `notas` debe contener el motivo.

---

## Secretos necesarios

### `NOTION_TOKEN`

Usado por `scripts/sync-notion.mjs`.

Debe ser el secret interno de una integración de Notion con acceso de lectura a:

- Documentos internos,
- Datasheets Electrónica.

Configúralo en:

```text
Settings → Secrets and variables → Actions → Repository secrets
```

Nombre exacto:

```text
NOTION_TOKEN
```

---

### `GDRIVE_SA_KEY`

Usado por `scripts/publish_temp_pdfs.py`.

Debe contener el JSON de una Google Service Account, como texto plano o base64.

Nombre exacto:

```text
GDRIVE_SA_KEY
```

La service account necesita:

- acceso de edición a la Google Sheet de cola,
- acceso de editor a la carpeta staging de Drive,
- permisos para leer PDFs,
- permisos para actualizar filas,
- permisos para mover archivos a papelera.

---

## Desarrollo local

### Sincronizar Notion localmente

Requisitos:

- Node 18 o superior,
- variable `NOTION_TOKEN`.

```bash
export NOTION_TOKEN=secret_xxx
node scripts/sync-notion.mjs
```

Esto regenera:

```text
data/docs.json
data/datasheets.json
data/meta.json
data/all.json
```

---

### Servir la web localmente

No abras `index.html` con doble clic. El navegador puede bloquear los `fetch()` locales.

Usa un servidor HTTP:

```bash
python3 -m http.server 8000
```

Después abre:

```text
http://localhost:8000
```

---

### Probar publicación temporal de PDFs

Requisitos:

- Python 3.11,
- `google-api-python-client`,
- `google-auth`,
- variable `GDRIVE_SA_KEY`.

```bash
pip install google-api-python-client google-auth
```

```bash
export GDRIVE_SA_KEY='{"type":"service_account",...}'
python scripts/publish_temp_pdfs.py
```

---

## Estructura del repositorio

```text
.
├── .github/
│   └── workflows/
│       ├── sync.yml
│       └── publish-temp-pdfs.yml
├── data/
│   ├── docs.json
│   ├── datasheets.json
│   ├── meta.json
│   └── all.json
├── pdfs/
├── scripts/
│   ├── sync-notion.mjs
│   └── publish_temp_pdfs.py
├── index.html
├── llms.txt
├── INTEGRATIONS.md
└── README.md
```

---

## Concurrencia y commits automáticos

Este repositorio tiene workflows que pueden commitear a `main`.

El sync de Notion modifica:

```text
data/*.json
```

El flujo de PDFs modifica:

```text
pdfs/
```

El script de PDFs incluye reintentos de `git push` con `fetch + rebase` para evitar fallos cuando otro workflow acaba de commitear en la misma rama.

Recomendación para el workflow de Notion si se dispara con mucha frecuencia:

```yaml
concurrency:
  group: solaris-sync
  cancel-in-progress: true
```

También es recomendable definir un timeout razonable:

```yaml
jobs:
  sync:
    timeout-minutes: 5
```

---

## Limitaciones

### No es tiempo real estricto

La web muestra el último JSON commiteado.

Si alguien cambia Notion, la web se actualiza cuando se ejecuta el workflow y GitHub Pages sirve el nuevo commit.

---

### No contiene el cuerpo completo de los documentos

`docs.json` es un índice de metadatos.

Sirve para localizar documentos por:

- título,
- código documental,
- temporada,
- tipo,
- subsistema,
- etiquetas,
- fecha.

Si necesitas el contenido completo de un informe, hay que abrir la página de Notion indicada en `url`.

---

### Los datos publicados son públicos

Todo lo que esté en:

```text
data/*.json
pdfs/
```

queda servido por GitHub Pages.

No publiques ahí información que no pueda ser visible públicamente.

---

### Los PDFs temporales también son públicos

Mientras un PDF exista dentro de `pdfs/`, cualquiera con la URL puede acceder a él.

Por eso el flujo incluye:

- expiración automática,
- retirada tras confirmación de embebido,
- limpieza de la copia de staging en Drive.

---

## Mantenimiento

### Cambiar la interfaz

Editar:

```text
index.html
```

---

### Cambiar qué campos se leen desde Notion

Editar:

```text
scripts/sync-notion.mjs
```

Revisar especialmente los nombres de propiedades hardcodeados:

```text
Título
Etiquetas
Subsistema o Unidad
Tipo Aerotech
Temporada
Nombre en Drive de Aerotech
Nombre
Fabricante
Descripción/Notas
Uso / placa
Proyectos
Interfaces
Enlace
```

Si se renombra una propiedad en Notion, el script puede dejar de leerla correctamente.

---

### Cambiar frecuencia de sincronización

Editar:

```text
.github/workflows/sync.yml
```

O ajustar el cron externo que dispare `workflow_dispatch`.

Si cambias la frecuencia, revisa también cualquier documentación que mencione la frescura de datos, especialmente:

```text
llms.txt
INTEGRATIONS.md
```

---

### Cambiar expiración de PDFs

Editar en:

```text
scripts/publish_temp_pdfs.py
```

Constante:

```python
EXPIRY_HOURS = 48
```

---

### Cambiar las bases de datos de Notion

Editar en:

```text
scripts/sync-notion.mjs
```

Constantes:

```js
DOCS_DB_ID
DATASHEETS_DB_ID
```

También pueden pasarse como variables de entorno:

```text
DOCS_DB_ID
DATASHEETS_DB_ID
```

---

## Resumen operativo

### Flujo documental

```text
Notion
  ├─ Documentos internos
  └─ Datasheets Electrónica
        ↓
GitHub Actions: sync.yml
        ↓
scripts/sync-notion.mjs
        ↓
data/*.json
        ↓
GitHub Pages
        ↓
index.html + endpoints públicos
```

### Flujo de PDFs temporales

```text
Google Sheet + Drive staging
        ↓
GitHub Actions: publish-temp-pdfs.yml
        ↓
scripts/publish_temp_pdfs.py
        ↓
pdfs/<archivo>.pdf
        ↓
GitHub Pages temporal
        ↓
expiración / confirmación / limpieza
```

---

## Licencia y uso

Este repositorio publica una consola documental estática para Solaris Rocketry Team / UVigo Aerotech.

Antes de reutilizarlo en otro equipo, revisa:

- qué datos se publican en `data/*.json`,
- si los enlaces de Notion deben ser visibles,
- si los PDFs temporales pueden exponerse por GitHub Pages,
- qué secretos están configurados en GitHub Actions,
- qué automatizaciones externas dependen de estos endpoints.

