# Parche `lastSyncRunAt` para `base-documental`

Archivos que cambian de verdad:

- `scripts/sync-notion.mjs`: reemplazo completo.
- `index.html`: cambio pequeño en la tarjeta `Última sync`.

## Uso recomendado

1. Copia `scripts/sync-notion.mjs` sobre el archivo del repo.
2. Para `index.html`, ejecuta desde la raíz del repo:

```bash
node tools/patch-index-lastSyncRunAt.mjs
```

Eso cambia solo la lectura de la tarjeta humana:

```js
state.meta.lastSyncRunAt || state.meta.updatedAt
```

No usa `lastContentChangeAt` para la UI humana.

## Qué hace el script de sync

- `lastContentChangeAt`: solo cambia si cambia el contenido real `{ docs, datasheets }` comparado con hash SHA-256 de `stableStringify`.
- `lastSyncRunAt`: cambia siempre que el script termine bien.
- Ambos campos se escriben en `data/meta.json` y en `data/all.json.meta`.
- Mantiene `updatedAt`, `docsCount`, `datasheetsCount` y `source` para compatibilidad.

## Verificación después del deploy

Comprobar:

- `https://dvzquez-dev.github.io/base-documental/data/meta.json`
- `https://dvzquez-dev.github.io/base-documental/data/all.json`

Debe aparecer `lastContentChangeAt` y `lastSyncRunAt`.
