// scripts/sync-notion.mjs
//
// Lee las bases de Notion de Documentos internos y Datasheets Electrónica y
// regenera data/docs.json, data/datasheets.json, data/meta.json y data/all.json.
// Requiere Node 18+ porque usa fetch nativo.

const NOTION_TOKEN = process.env.NOTION_TOKEN;
const DOCS_DB_ID = process.env.DOCS_DB_ID || "11eb0e3a469c80b9969ff0d0e88e2f36";
const DATASHEETS_DB_ID = process.env.DATASHEETS_DB_ID || "366b0e3a469c808ba0bee31c8979d3f3";
const NOTION_VERSION = "2022-06-28";

if (!NOTION_TOKEN) {
  console.error("Falta la variable de entorno NOTION_TOKEN.");
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
  let cursor;

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

const getTitle = (prop) => (prop?.title ?? []).map((t) => t.plain_text).join("");
const getRichText = (prop) => (prop?.rich_text ?? []).map((t) => t.plain_text).join("");
const getSelect = (prop) => prop?.select?.name ?? null;
const getMultiSelect = (prop) => (prop?.multi_select ?? []).map((o) => o.name).filter(Boolean);
const getNumber = (prop) => (typeof prop?.number === "number" ? prop.number : null);
const getUrlProp = (prop) => prop?.url ?? null;

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
    docCode: getFormulaString(props["Nombre en Drive de Aerotech"]),
    subsystem: SUBSYSTEM_MAP[subsystemLabel] ?? "general",
    subsystemLabel: subsystemLabel || "Solaris",
    title: getTitle(props["Título"]) || "(sin título)",
    tipo: getSelect(props["Tipo Aerotech"]) || "SinTipo",
    season: getSelect(props["Temporada"]) || "",
    tags: getMultiSelect(props["Etiquetas"]),
    date: (page.created_time || "").slice(0, 10),
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

  const meta = {
    updatedAt: new Date().toISOString(),
    docsCount: docs.length,
    datasheetsCount: datasheets.length,
    source: "notion-sync",
    archiveName: "Archivo Técnico Unificado",
    sourceSystem: "Notion",
    role: "visual-access-layer",
    accessModel: "Los enlaces conservan los permisos definidos en Notion o en la fuente original.",
    aiScope: "Índice estructurado de metadatos; no concede acceso automático al contenido completo privado.",
  };

  const fs = await import("node:fs/promises");
  const dataDir = new URL("../data/", import.meta.url);
  await fs.mkdir(dataDir, { recursive: true });
  await fs.writeFile(new URL("../data/docs.json", import.meta.url), JSON.stringify(docs));
  await fs.writeFile(new URL("../data/datasheets.json", import.meta.url), JSON.stringify(datasheets));
  await fs.writeFile(new URL("../data/meta.json", import.meta.url), JSON.stringify(meta));
  await fs.writeFile(new URL("../data/all.json", import.meta.url), JSON.stringify({ meta, docs, datasheets }));

  console.log(`OK: ${docs.length} documentos, ${datasheets.length} datasheets.`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
