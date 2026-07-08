// scripts/sync-notion.mjs
//
// Lee las dos bases de datos de Notion (Documentos internos y Datasheets
// Electrónica) y regenera data/docs.json, data/datasheets.json,
// data/meta.json y data/all.json.
//
// Semántica de timestamps:
// - lastSyncRunAt: se actualiza SIEMPRE que esta ejecución termina bien.
// - lastContentChangeAt: solo cambia si el contenido real de docs/datasheets
//   cambia respecto al build anterior.
//
// NOTION_TOKEN=secret_xxx node scripts/sync-notion.mjs
//
// Requiere Node 18+ (usa fetch nativo). Sin dependencias externas.

import { createHash } from "node:crypto";
import fs from "node:fs/promises";

const NOTION_TOKEN = process.env.NOTION_TOKEN;

// IDs de las databases (no son secretos: sin un token de integración válido
// con acceso compartido, no permiten leer nada). Si algún día mueves o
// duplicas las bases en Notion, actualiza los IDs aquí.
const DOCS_DB_ID = process.env.DOCS_DB_ID || "11eb0e3a469c80b9969ff0d0e88e2f36";
const DATASHEETS_DB_ID = process.env.DATASHEETS_DB_ID || "366b0e3a469c808ba0bee31c8979d3f3";
const NOTION_VERSION = "2022-06-28";
const DATA_DIR = new URL("../data/", import.meta.url);

if (!NOTION_TOKEN) {
  console.error("Falta la variable de entorno NOTION_TOKEN (secreto de la integración de Notion).");
  process.exit(1);
}

async function queryDatabase(databaseId) {
  const results = [];
  let cursor = undefined;

  do {
    const res = await fetch(`https://api.notion.com/v1/databases/${databaseId}/query`, {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${NOTION_TOKEN}`,
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        page_size: 100,
        ...(cursor ? { start_cursor: cursor } : {}),
      }),
    });

    if (!res.ok) {
      const body = await res.text();
      throw new Error(`Notion API error ${res.status} en database ${databaseId}: ${body}`);
    }

    const json = await res.json();
    results.push(...json.results);
    cursor = json.has_more ? json.next_cursor : null;
  } while (cursor);

  return results;
}

// ---------- Helpers para extraer valores de propiedades de Notion ----------
const getTitle = (prop) => (prop?.title ?? []).map((t) => t.plain_text).join("");
const getRichText = (prop) => (prop?.rich_text ?? []).map((t) => t.plain_text).join("");
const getSelect = (prop) => prop?.select?.name ?? null;
const getMultiSelect = (prop) => (prop?.multi_select ?? []).map((o) => o.name);
const getNumber = (prop) => (typeof prop?.number === "number" ? prop.number : null);
const getUrlProp = (prop) => prop?.url ?? null;

// Las propiedades de tipo "formula" en Notion devuelven su resultado ya
// calculado (string, number, boolean o date, según cómo esté definida la
// fórmula). Aquí solo nos interesa el caso de resultado en texto.
const getFormulaString = (prop) => {
  if (!prop || prop.type !== "formula" || !prop.formula) return null;
  return prop.formula.type === "string" ? (prop.formula.string ?? null) : null;
};

// Mapea el texto de "Subsistema o Unidad" al código corto + color usado en el front-end.
const SUBSYSTEM_MAP = {
  "Solaris": "general",
  "Subsistema de Propulsión": "prop",
  "Subsistema de Estructuras&Aerodinámica": "struct",
  "Subsistema de Dinámica&Control": "dyn",
  "Subsistema de Electrónica": "elec",
  "Unidad de Coordinación Técnica": "coord",
};

function buildDoc(page) {
  const props = page.properties;
  const subsystemLabel = getSelect(props["Subsistema o Unidad"]);

  return {
    id: getNumber(props["ID (XXXX)"]),
    // Código documental único (p.ej. "Informe_S-2009_26"), calculado por
    // Notion a partir de tipo + ID + temporada. A diferencia de "id" (que
    // se reutiliza entre temporadas), este código no se repite nunca: es el
    // identificador sin ambigüedad para localizar un documento exacto.
    docCode: getFormulaString(props["Nombre en Drive de Aerotech"]),
    subsystem: SUBSYSTEM_MAP[subsystemLabel] ?? "general",
    title: getTitle(props["Título"]) || "(sin título)",
    tipo: getSelect(props["Tipo Aerotech"]) || "SinTipo",
    season: getSelect(props["Temporada"]) || "",
    tags: getMultiSelect(props["Etiquetas"]),
    date: (page.created_time || "").slice(0, 10),
    // Timestamp completo (fecha + hora + zona, formato ISO 8601), tal cual
    // lo da Notion. "date" se mantiene igual (solo YYYY-MM-DD) porque la
    // interfaz y el gráfico de telemetría ya cuentan con ese formato; este
    // campo es un añadido para quien necesite la hora exacta de subida.
    uploadedAt: page.created_time || null,
    url: page.url,
  };
}

function buildDatasheet(page) {
  const props = page.properties;

  return {
    name: getTitle(props["Nombre"]) || "(sin nombre)",
    tipo: getSelect(props["Tipo"]) || "",
    fabricante: getRichText(props["Fabricante"]) || "",
    desc: getRichText(props["Descripción/Notas"]) || "",
    uso: getRichText(props["Uso / placa"]) || "",
    proyectos: getMultiSelect(props["Proyectos"]),
    interfaces: getMultiSelect(props["Interfaces"]),
    enlace: getUrlProp(props["Enlace"]) || "",
    url: page.url,
  };
}

function stableStringify(value) {
  if (value === null || typeof value !== "object") {
    return JSON.stringify(value);
  }

  if (Array.isArray(value)) {
    return `[${value.map((item) => stableStringify(item) ?? "null").join(",")}]`;
  }

  return `{${Object.keys(value)
    .filter((key) => value[key] !== undefined)
    .sort()
    .map((key) => `${JSON.stringify(key)}:${stableStringify(value[key])}`)
    .join(",")}}`;
}

function sha256Stable(value) {
  return createHash("sha256").update(stableStringify(value)).digest("hex");
}

async function readJsonIfExists(path) {
  try {
    return JSON.parse(await fs.readFile(path, "utf8"));
  } catch (err) {
    if (err && err.code === "ENOENT") return null;
    throw err;
  }
}

function isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function sortDocs(docs) {
  return docs.sort((a, b) =>
    (b.date || "").localeCompare(a.date || "") ||
    String(a.docCode || "").localeCompare(String(b.docCode || "")) ||
    String(a.title || "").localeCompare(String(b.title || "")) ||
    String(a.url || "").localeCompare(String(b.url || ""))
  );
}

function sortDatasheets(datasheets) {
  return datasheets.sort((a, b) =>
    String(a.name || "").localeCompare(String(b.name || "")) ||
    String(a.fabricante || "").localeCompare(String(b.fabricante || "")) ||
    String(a.url || "").localeCompare(String(b.url || ""))
  );
}

async function main() {
  console.log("Consultando Notion...");

  const [docPages, dsPages] = await Promise.all([
    queryDatabase(DOCS_DB_ID),
    queryDatabase(DATASHEETS_DB_ID),
  ]);

  const docs = sortDocs(docPages.map(buildDoc));
  const datasheets = sortDatasheets(dsPages.map(buildDatasheet));

  await fs.mkdir(DATA_DIR, { recursive: true });

  const metaPath = new URL("meta.json", DATA_DIR);
  const allPath = new URL("all.json", DATA_DIR);
  const docsPath = new URL("docs.json", DATA_DIR);
  const datasheetsPath = new URL("datasheets.json", DATA_DIR);

  const previousMeta = await readJsonIfExists(metaPath);
  const previousAll = await readJsonIfExists(allPath);
  const previousDocs = await readJsonIfExists(docsPath);
  const previousDatasheets = await readJsonIfExists(datasheetsPath);
  const previousAllMeta = isObject(previousAll?.meta) ? previousAll.meta : null;

  const currentContentHash = sha256Stable({ docs, datasheets });

  let previousContentHash =
    previousMeta?.contentHash ??
    previousMeta?.contentSha256 ??
    previousAllMeta?.contentHash ??
    previousAllMeta?.contentSha256 ??
    null;

  if (!previousContentHash && Array.isArray(previousDocs) && Array.isArray(previousDatasheets)) {
    previousContentHash = sha256Stable({ docs: previousDocs, datasheets: previousDatasheets });
  }

  const syncRunAt = new Date().toISOString();
  const previousContentChangeAt =
    previousMeta?.lastContentChangeAt ??
    previousAllMeta?.lastContentChangeAt ??
    previousMeta?.updatedAt ??
    previousAllMeta?.updatedAt ??
    null;

  const contentChanged = previousContentHash !== currentContentHash;
  const lastContentChangeAt = contentChanged ? syncRunAt : (previousContentChangeAt ?? syncRunAt);

  const previousPublicMeta = isObject(previousMeta) ? previousMeta : {};
  const meta = {
    ...previousPublicMeta,
    updatedAt: syncRunAt,
    lastSyncRunAt: syncRunAt,
    lastContentChangeAt,
    contentHash: currentContentHash,
    docsCount: docs.length,
    datasheetsCount: datasheets.length,
    source: "notion-sync",
  };

  await fs.writeFile(docsPath, JSON.stringify(docs));
  await fs.writeFile(datasheetsPath, JSON.stringify(datasheets));
  await fs.writeFile(metaPath, JSON.stringify(meta));

  // Archivo combinado: pensado para automatizaciones externas (Zapier, Make,
  // n8n...) que solo quieren hacer UNA petición HTTP en vez de tres.
  await fs.writeFile(allPath, JSON.stringify({ meta, docs, datasheets }));

  console.log(
    `OK: ${docs.length} documentos, ${datasheets.length} datasheets. ` +
    `contentChanged=${contentChanged}. lastContentChangeAt=${lastContentChangeAt}. lastSyncRunAt=${syncRunAt}.`
  );
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
