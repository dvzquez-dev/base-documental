// tools/patch-index-lastSyncRunAt.mjs
// Ejecutar desde la raíz del repo: node tools/patch-index-lastSyncRunAt.mjs
// Aplica solo el cambio de la tarjeta "Última sync" en index.html.

import fs from "node:fs/promises";

const INDEX_PATH = new URL("../index.html", import.meta.url);

const replacements = [
  {
    name: "index actual en GitHub main",
    from:
` const syncLabel = state.meta && state.meta.updatedAt
 ? new Date(state.meta.updatedAt).toLocaleString('es-ES',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}) : '—';`,
    to:
` const syncAt = state.meta && (state.meta.lastSyncRunAt || state.meta.updatedAt);
 const syncLabel = syncAt
 ? new Date(syncAt).toLocaleString('es-ES',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}) : '—';`,
  },
  {
    name: "index del parche anterior",
    from:
`  const syncAt = state.meta && (state.meta.updatedAt || state.meta.lastContentChangeAt);
  const syncLabel = syncAt ? formatSyncDate(syncAt) : '—';`,
    to:
`  const syncAt = state.meta && (state.meta.lastSyncRunAt || state.meta.updatedAt);
  const syncLabel = syncAt ? formatSyncDate(syncAt) : '—';`,
  },
];

let html = await fs.readFile(INDEX_PATH, "utf8");

if (html.includes("state.meta.lastSyncRunAt || state.meta.updatedAt")) {
  console.log("index.html ya usa lastSyncRunAt. Sin cambios.");
  process.exit(0);
}

for (const replacement of replacements) {
  if (html.includes(replacement.from)) {
    html = html.replace(replacement.from, replacement.to);
    await fs.writeFile(INDEX_PATH, html);
    console.log(`index.html parcheado correctamente (${replacement.name}).`);
    process.exit(0);
  }
}

throw new Error(
  "No encontré el bloque esperado en index.html. No he tocado el archivo para evitar romperlo. " +
  "Revisa index-current-github-lastSyncRunAt.patch y aplica el cambio a mano."
);
