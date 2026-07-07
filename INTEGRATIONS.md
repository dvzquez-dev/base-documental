# Integraciones con el Archivo Técnico Solaris

Este documento explica las distintas formas de "conectar" algo a los datos
publicados en `https://dvzquez-dev.github.io/base-documental/`, según qué
estés integrando.

## 1. Conmigo (Claude), en el chat

Ya tengo acceso directo a las dos bases de Notion (Documentos internos y
Datasheets Electrónica) como herramienta conectada en esta conversación. Eso
significa que para preguntas de contenido ("¿qué informes hay de propulsión
en abril?", "dame el enlace de la datasheet del BMP390") no necesito pasar
por GitHub en absoluto — consulto Notion en el momento, sin caché ni retraso
de sincronización.

Lo que **no puedo hacer** es visitar por mi cuenta una URL que no me hayas
pasado tú en el propio mensaje. Es una barrera de seguridad deliberada (para
que no pueda inventarme ni recordar URLs entre conversaciones). Así que si
alguna vez quieres que compruebe específicamente lo que está publicado en la
web (no en Notion), tendrás que pegarme el enlace exacto en ese momento,
cada vez. No hay forma de evitarlo, y no es algo que dependa de cómo esté
montado este proyecto.

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
