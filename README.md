# Solaris Document Console

Buscador de documentos internos y datasheets de electrónica del equipo Solaris,
con los datos sincronizados automáticamente desde Notion.

## Cómo funciona

- `index.html` es la web (sin frameworks, un solo archivo). Carga los datos desde
  `data/docs.json` y `data/datasheets.json`.
- `.github/workflows/sync.yml` ejecuta cada 30 minutos (y también cuando lo
  lances a mano) el script `scripts/sync-notion.mjs`, que pregunta a la API de
  Notion por las dos bases de datos y **sobrescribe** esos dos JSON. Si hay
  cambios, los commitea al repo automáticamente.
- GitHub Pages sirve el contenido del repo tal cual, así que la web siempre
  muestra el último JSON commiteado.

Esto **no es instantáneo al cargar la página** (eso requeriría un backend que
guarde el secreto de Notion y lo mantenga fuera de un repo público). Es
"casi en vivo": como máximo 30 minutos de desfase, y puedes forzar una
actualización inmediata desde la pestaña *Actions* cuando quieras.

## Puesta en marcha (una sola vez)

### 1. Crear una integración de Notion
1. Ve a [notion.so/my-integrations](https://www.notion.so/my-integrations) →
   **New integration**.
2. Ponle un nombre (p. ej. "Solaris Console"), asóciala a tu workspace, y
   guarda. Copia el **Internal Integration Secret** (empieza por `secret_` o
   `ntn_`).
3. Solo necesita permiso de lectura de contenido (no actives capacidades de
   escritura ni de usuarios).

### 2. Compartir las dos bases de datos con la integración
En Notion, abre cada una de estas páginas y en el menú `•••` de arriba a la
derecha → **Connections** → añade la integración que acabas de crear:
- **Documentos internos**
- **Datasheets Electrónica**

Si no le das acceso, el script fallará con un error 403/404.

### 3. Subir este proyecto a GitHub
Crea un repositorio nuevo (puede ser público o privado; si quieres GitHub
Pages gratis en un repo privado necesitas plan GitHub Pro) y sube todos estos
archivos tal cual, manteniendo la estructura de carpetas.

### 4. Añadir el secreto en GitHub
En el repo → **Settings → Secrets and variables → Actions → New repository
secret**:
- Name: `NOTION_TOKEN`
- Value: el secreto que copiaste en el paso 1

### 5. Activar GitHub Pages
**Settings → Pages → Source: Deploy from a branch → Branch: `main` / `root`.**
Al cabo de un minuto tendrás la web en
`https://<tu-usuario>.github.io/<tu-repo>/`.

### 6. Lanzar la primera sincronización
Pestaña **Actions** → workflow "Sync Notion data" → **Run workflow**. Tarda
unos segundos y deja `data/*.json` frescos. A partir de ahí se repite solo
cada 30 minutos.

## Actualizar el diseño o añadir más bases

- Los nombres de columnas que lee el script están hardcodeados en
  `scripts/sync-notion.mjs` (`Título`, `Etiquetas`, `Subsistema o Unidad`,
  etc.). Si renombras una propiedad en Notion, actualiza el script.
- Si en algún momento duplicas o mueves las bases de datos, los IDs cambian:
  actualiza las constantes `DOCS_DB_ID` / `DATASHEETS_DB_ID` al principio del
  script (o pásalos como secrets/variables adicionales en vez de tocar el
  código).

## Probarlo en local antes de subirlo

```bash
export NOTION_TOKEN=secret_xxx
node scripts/sync-notion.mjs      # regenera data/*.json con datos frescos
python3 -m http.server 8000       # sirve la carpeta (index.html no funciona
                                   # bien con doble-clic porque hace fetch())
# abre http://localhost:8000
```
