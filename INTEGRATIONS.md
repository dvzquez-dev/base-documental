# Integraciones con el Archivo Técnico Solaris

Este documento explica las distintas formas de "conectar" algo a los datos
publicados en `https://dvzquez-dev.github.io/base-documental/`, según qué
estés integrando.

## 1. Conmigo (Claude), en el chat

**Importante — que quede sin ambigüedad:** nada de lo publicado en este repo
(`data/all.json`, `llms.txt`, ni ningún otro archivo) cambia esto. Es una
regla fija de la herramienta de navegación de Claude, no algo que dependa de
cómo esté montado este proyecto:

> Claude solo puede leer una URL si aparece escrita en el propio mensaje de
> esa conversación — porque la pegó la persona, o porque salió de una
> búsqueda hecha en esa misma conversación. Claude nunca visita una URL por
> iniciativa propia, ni la recuerda de una conversación anterior, aunque sea
> pública y esté documentada en un `llms.txt`.

Así que para que Claude compruebe algo de lo publicado en la web (no de
Notion), siempre hay que pegarle el enlace o el contenido en el mensaje, en
esa conversación, cada vez. No hay forma de evitar este paso.

Lo que sí tengo disponible de forma permanente, sin pegar nada, es una
herramienta conectada directamente a las dos bases de Notion (Documentos
internos y Datasheets Electrónica). Para preguntas de contenido ("¿qué
informes hay de propulsión en abril?") puedo consultarlas en el momento, sin
pasar por GitHub ni por la sincronización de 10 minutos.

### ¿Es más barato leer el JSON publicado que consultar Notion en directo?

Para casos concretos, sí, bastante:

- `data/meta.json` pesa ~100 bytes (un contador y una fecha) — leerlo es
  casi gratis.
- Consultar Notion en frío requiere primero traer el esquema de la base: solo
  eso, con los colores e IDs de las ~190 etiquetas de "Documentos internos",
  son más de 30.000 caracteres antes de ver un solo documento real.
- `data/all.json` (documentos + datasheets) pesa ~43 KB, pero sin ese ruido
  de esquema — comparable o más barato que una consulta a Notion ya afinada.

Criterio práctico:
- **JSON publicado** → para contar documentos, comprobar cuándo fue la
  última sincronización, o buscar por título/etiqueta/subsistema. Es la
  opción barata y suficiente el 90% de las veces.
- **Notion en directo** → cuando hace falta el dato más fresco posible (algo
  subido hace 2 minutos, antes del próximo sync) o contenido que el índice
  no tiene (el cuerpo de un informe, no solo su título y etiquetas).

Nota: leer el JSON publicado solo es "gratis sin pegar nada" dentro de la
misma conversación, una vez que esa URL ya ha aparecido ahí (porque la
pegaste tú, o porque Claude ya la leyó antes en ese mismo chat). En una
conversación nueva, hay que volver a pasar el enlace una vez.

### El patrón bueno para una pipeline documental: índice barato + fetch preciso

Ni el JSON publicado ni Notion en directo son "la" solución por sí solos —
se combinan:

1. **Localizar** el documento que buscas en `data/all.json` (o
   `docs.json`/`datasheets.json`). Es barato porque son ~40 KB sin ruido de
   esquema, y cada entrada trae un campo `url` con el link directo a la
   página de Notion.
2. **Leer el contenido real** solo de esa página concreta, con una única
   llamada a Notion usando ese `url` (no una búsqueda por todo el
   workspace). El índice no tiene el cuerpo del documento — solo metadata
   (título, tipo, etiquetas, fecha) — así que este segundo paso es
   imprescindible en cuanto necesitas algo más que "en qué documento está
   esto".

Ejemplo real (probado): a partir de la entrada
`{"title":"Informe mayo electrónica", ..., "url":"https://app.notion.com/p/Informe-mayo-electr-nica-395b0e3a469c81baa4bffffa560a97f1"}`
del índice, una sola llamada a ese `url` en Notion devuelve el resumen
completo del informe, quién lo subió, los enlaces al DOCX/PDF en Drive y las
etiquetas finales — nada de eso está en el índice, y no hizo falta buscar
nada más en Notion para encontrarlo.

Coste aproximado de cada paso, para referencia:
- Paso 1 (índice): ~100 bytes (`meta.json`) a ~43 KB (`all.json`) — una vez.
- Paso 2 (Notion): una página normal, sin el ruido de esquema de una
  búsqueda en frío — solo por el documento ganador, no por todos los
  candidatos.

## 2. Otros agentes de IA y automatizaciones sin IA

Aquí es donde sí se nota la diferencia de tener `data/all.json` y
`llms.txt` publicados: un agente de IA con navegación web más autónoma que
la de Claude en este producto (o una automatización sin IA de por medio,
como Zapier o n8n) puede descubrir y leer estos archivos sin que nadie le
pegue el link a mano cada vez. Esa es la utilidad real de estos dos
archivos — no aplica a Claude en este chat.

## 2. Automatizaciones sin IA (Zapier, Make, n8n, cron propio, Google Sheets...)

Estas **no tienen esa limitación** — son peticiones HTTP normales a archivos
JSON públicos, sin autenticación, así que cualquier herramienta puede leerlos
directamente:

| Archivo | URL | Contenido |
|---|---|---|
| Documentos | `https://dvzquez-dev.github.io/base-documental/data/docs.json` | Array de los 133 documentos internos |
| Datasheets | `https://dvzquez-dev.github.io/base-documental/data/datasheets.json` | Array de los componentes de electrónica |
| Metadata | `https://dvzquez-dev.github.io/base-documental/data/meta.json` | `{updatedAt, docsCount, datasheetsCount}` |
| Todo junto | `https://dvzquez-dev.github.io/base-documental/data/all.json` | Los tres anteriores combinados en un solo objeto |

Se actualizan solos cada 30 minutos (o al momento si lanzas el workflow a
mano desde Actions). No necesitan ningún token ni cabecera especial — es un
`GET` normal.

### Ejemplo con curl
```bash
curl -s https://dvzquez-dev.github.io/base-documental/data/all.json | jq '.meta'
```

### Ejemplo en n8n
- Nodo **HTTP Request** → Method: `GET` → URL: la de `all.json` → Response
  Format: JSON. Ya puedes encadenar un nodo **IF** o **Filter** para quedarte
  solo con los documentos de un subsistema, por ejemplo.

### Ejemplo en Zapier / Make
- Trigger: **Schedule** (cada X horas)
- Acción: **Webhooks → GET** a la URL de `all.json`
- Parsear el JSON de respuesta y usarlo como quieras (crear una fila en
  Sheets, mandar un mensaje a Slack con los documentos nuevos desde el
  último `updatedAt`, etc.)

### Detectar "hay documentos nuevos" sin comparar todo
Guarda el `updatedAt` (o el `docsCount`) de la última vez que miraste
`meta.json`, y compáralo con el actual antes de procesar `all.json` entero —
así evitas relanzar la automatización si no ha cambiado nada.

## 3. Importante: el token de Notion no entra en ninguna automatización externa

Estas integraciones externas **nunca necesitan `NOTION_TOKEN`** — ese secreto
solo lo usa la GitHub Action para hablar con Notion. Todo lo que consume
Zapier/n8n/Claude por HTTP es JSON ya público y de solo lectura. Si alguna
automatización te pide que metas un token de Notion para leer estos
archivos, no hace falta — es una señal de que está mal configurada.
