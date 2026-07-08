// scripts/sync-notion.mjs
//
// Lee las dos bases de datos de Notion (Documentos internos y Datasheets
// Electrónica) y regenera data/docs.json, data/datasheets.json, data/meta.json
// y data/all.json. Pensado para ejecutarse desde GitHub Actions (ver
// .github/workflows/sync.yml), pero funciona igual en local:
//
//   NOTION_TOKEN=secret_xxx node scripts/sync-notion.mjs
//
// Requiere Node 18+ (usa fetch nativo). Sin dependencias externas.

import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";

const NOTION_TOKEN = process.env.NOTION_TOKEN;

// IDs de las databases (no son secretos: sin un token de integración válido
// con acceso compartido, no permiten leer nada). Si algún día mueves o
// duplicas las bases en Notion, actualiza los IDs aquí.
const DOCS_DB_ID = process.env.DOCS_DB_ID || "11eb0e3a469c80b9969ff0d0e88e2f36";
const DATASHEETS_DB_ID = process.env.DATASHEETS_DB_ID || "366b0e3a469c808ba0bee31c8979d3f3";

const NOTION_VERSION = "2022-06-28";

if (!NOTION_TOKEN) {
  console.error("Falta la variable de entorno NOTION_TOKEN (secreto de la integración de Notion).");
  process.exit(1);
}

const SUBSYSTEM_MAP = {
  Solaris: "general",
  "Subsistema de Propulsión": "prop",
  "Subsistema de Estructuras&Aerodinámica": "struct",
  "Subsistema de Dinámica&Control": "dyn",
  "Subsistema de Electrónica": "elec",
  "Unidad de Coordinación Técnica": "coord",
};

async function queryDatabase(databaseId) {
  const results = [];
  let cursor = undefined;

  do {
    const res = await fetch(`https://api.notion.com/v1/databases/${databaseId}/query`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${NOTION_TOKEN}`,
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
const getMultiSelect = (prop) => (prop?.multi_select ?? []).map((o) => o.name).filter(Boolean);
const getNumber = (prop) => (typeof prop?.number === "number" ? prop.number : null);
const getUrlProp = (prop) => prop?.url ?? null;

// Las propiedades de tipo "formula" en Notion devuelven su resultado ya
// calculado (string, number, boolean o date, según cómo esté definida la
// fórmula). Aquí solo nos interesa el caso de resultado en texto.
function getFormulaString(prop) {
  if (!prop || prop.type !== "formula" || !prop.formula) return null;
  return prop.formula.type === "string" ? prop.formula.string ?? null : null;
}

function normalizeText(value) {
  return String(value ?? "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .trim();
}

function buildSearchText(values) {
  return normalizeText(values.filter(Boolean).join(" "));
}

function buildDoc(page) {
  const props = page.properties;
  const subsystemLabel = getSelect(props["Subsistema o Unidad"]);
  const doc = {
    id: getNumber(props["ID (XXXX)"]),
    // Código documental único (p.ej. "Informe_S-2009_26"), calculado por
    // Notion a partir de tipo + ID + temporada. A diferencia de "id" (que
    // se reutiliza entre temporadas), este código no se repite nunca: es el
    // identificador sin ambigüedad para localizar un documento exacto.
    docCode: getFormulaString(props["Nombre en Drive de Aerotech"]),
    subsystem: SUBSYSTEM_MAP[subsystemLabel] ?? "general",
    subsystemLabel: subsystemLabel || "Solaris",
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

  doc.searchText = buildSearchText([
    doc.docCode,
    doc.title,
    doc.tipo,
    doc.season,
    doc.subsystem,
    doc.subsystemLabel,
    doc.tags.join(" "),
    doc.date,
    doc.uploadedAt,
  ]);

  return doc;
}

function buildDatasheet(page) {
  const props = page.properties;
  const datasheet = {
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

  datasheet.searchText = buildSearchText([
    datasheet.name,
    datasheet.tipo,
    datasheet.fabricante,
    datasheet.desc,
    datasheet.uso,
    datasheet.proyectos.join(" "),
    datasheet.interfaces.join(" "),
  ]);

  return datasheet;
}

function byUploadedAtDesc(a, b) {
  return (b.uploadedAt || b.date || "").localeCompare(a.uploadedAt || a.date || "");
}

function isoNowUtc() {
  return new Date().toISOString().replace(/\.\d{3}Z$/, "Z");
}

async function readJsonOrNull(path) {
  try {
    return JSON.parse(await readFile(path, "utf8"));
  } catch (error) {
    if (error && error.code === "ENOENT") return null;
    console.warn(`No se pudo leer ${path.pathname || path}: ${error.message}`);
    return null;
  }
}

function stableStringify(value) {
  if (Array.isArray(value)) return `[${value.map(stableStringify).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${stableStringify(value[key])}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}

function hashContent(value) {
  return createHash("sha256").update(stableStringify(value)).digest("hex");
}

function extractContentPayload(allJson) {
  return {
    docs: Array.isArray(allJson?.docs) ? allJson.docs : [],
    datasheets: Array.isArray(allJson?.datasheets) ? allJson.datasheets : [],
  };
}

function resolvePreviousLastChange(previousMeta, previousAll) {
  return (
    previousMeta?.lastContentChangeAt ||
    previousAll?.meta?.lastContentChangeAt ||
    previousAll?.meta?.updatedAt ||
    null
  );
}

async function main() {
  console.log("Consultando Notion...");

  const [docPages, dsPages] = await Promise.all([
    queryDatabase(DOCS_DB_ID),
    queryDatabase(DATASHEETS_DB_ID),
  ]);

  const docs = docPages.map(buildDoc).sort(byUploadedAtDesc);
  const datasheets = dsPages
    .map(buildDatasheet)
    .sort((a, b) => a.name.localeCompare(b.name, "es"));

  const dataDir = new URL("../data/", import.meta.url);
  const allPath = new URL("../data/all.json", import.meta.url);
  const metaPath = new URL("../data/meta.json", import.meta.url);

  const previousAll = await readJsonOrNull(allPath);
  const previousMeta = await readJsonOrNull(metaPath);
  const nextContentPayload = { docs, datasheets };
  const previousContentHash = previousAll ? hashContent(extractContentPayload(previousAll)) : null;
  const nextContentHash = hashContent(nextContentPayload);
  const contentChanged = previousContentHash !== nextContentHash;
  const previousLastContentChangeAt = resolvePreviousLastChange(previousMeta, previousAll);
  const lastContentChangeAt = contentChanged || !previousLastContentChangeAt
    ? isoNowUtc()
    : previousLastContentChangeAt;

  const meta = {
    // Compatibilidad con consumidores existentes: updatedAt se mantiene, pero
    // ya no representa "hora de build" sino última modificación real del índice.
    updatedAt: lastContentChangeAt,
    lastContentChangeAt,
    docsCount: docs.length,
    docCount: docs.length,
    datasheetsCount: datasheets.length,
    source: "notion-sync",
    archiveName: "Archivo Técnico Unificado",
    sourceSystem: "Notion",
    role: "visual-access-layer",
    accessModel: "Los enlaces conservan los permisos definidos en Notion o en la fuente original.",
    aiScope: "Índice estructurado de metadatos; no concede acceso automático al contenido completo privado.",
  };

  const smallMeta = {
    lastContentChangeAt,
    docCount: docs.length,
  };

  await mkdir(dataDir, { recursive: true });
  await writeFile(new URL("../data/docs.json", import.meta.url), JSON.stringify(docs));
  await writeFile(new URL("../data/datasheets.json", import.meta.url), JSON.stringify(datasheets));
  await writeFile(metaPath, `${JSON.stringify(smallMeta, null, 2)}\n`);
  await writeFile(allPath, JSON.stringify({ meta, docs, datasheets }));

  console.log(
    `OK: ${docs.length} documentos, ${datasheets.length} datasheets. ` +
      (contentChanged ? `Cambio real detectado: ${lastContentChangeAt}.` : `Sin cambios reales desde ${lastContentChangeAt}.`)
  );
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
