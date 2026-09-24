import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const repoRoot = path.resolve("../..");
const servicePath = path.join(repoRoot, "app", "news", "services", "incidents", "incident_workbook_service.py");
const sourcePath = "C:\\Users\\User\\Downloads\\accuracy_study_synthetic_news.xlsx";
const outputPath = "C:\\Users\\User\\Downloads\\accuracy_study_import_template_FIXED.xlsx";

const serviceSource = await fs.readFile(servicePath, "utf8");
function assignmentStrings(name) {
  const start = serviceSource.indexOf(`${name}:`);
  if (start < 0) throw new Error(`Missing ${name}`);
  const end = serviceSource.indexOf("\n\n", start);
  return [...serviceSource.slice(start, end).matchAll(/"([^"]+)"/g)].map((m) => m[1]);
}
function dictKeys(name, nextMarker) {
  const start = serviceSource.indexOf(`${name}:`);
  const end = serviceSource.indexOf(nextMarker, start);
  if (start < 0 || end < 0) throw new Error(`Missing ${name}`);
  return [...serviceSource.slice(start, end).matchAll(/^\s+"([^"]+)":/gm)].map((m) => m[1]);
}

const optional = new Set(assignmentStrings("OPTIONAL_HEADERS"));
const headers = [
  ...assignmentStrings("LOOKUP_ONLY_HEADERS"),
  ...dictKeys("INCIDENT_FIELD_MAP", "INCIDENT_INT_FIELD_MAP"),
  ...dictKeys("INCIDENT_INT_FIELD_MAP", "INCIDENT_DETAIL_FIELD_MAP"),
  "Time",
  "Date",
  ...dictKeys("INCIDENT_DETAIL_FIELD_MAP", "CASUALTY_DEMOGRAPHIC_HEADERS"),
].filter((header) => !optional.has(header));

const sourceWorkbook = await SpreadsheetFile.importXlsx(await fs.readFile(sourcePath));
const rawSheet = sourceWorkbook.worksheets.getItem("raw_import");
const rawValues = rawSheet.getUsedRange().values;
const sourceHeaders = rawValues[0];
const rowIdIndex = sourceHeaders.indexOf("row_id");
const textIndex = sourceHeaders.indexOf("raw_text");
const sourceNameIndex = sourceHeaders.indexOf("source_name");

const workbook = Workbook.create();
const sheet = workbook.worksheets.add("Import incidents");
sheet.getRangeByIndexes(0, 0, 1, headers.length).values = [headers];
const index = Object.fromEntries(headers.map((header, i) => [header, i]));
const rows = rawValues.slice(1).filter((row) => row[textIndex]).map((sourceRow) => {
  const row = Array(headers.length).fill("");
  const rowId = Number(sourceRow[rowIdIndex]);
  row[index.Khabar] = sourceRow[textIndex];
  row[index.NOTE] = `ACCSTUDY-${String(rowId).padStart(3, "0")}`;
  row[index.Date] = new Date(Date.UTC(2026, 8, 23));
  row[index.Source] = sourceRow[sourceNameIndex] || "accuracy_study_synthetic";
  return row;
});
sheet.getRangeByIndexes(1, 0, rows.length, headers.length).values = rows;
sheet.freezePanes.freezeRows(1);
sheet.getRangeByIndexes(0, 0, rows.length + 1, headers.length).format.font = { name: "Arial", size: 10 };
sheet.getRangeByIndexes(0, 0, 1, headers.length).format = {
  fill: "#1F2937",
  font: { name: "Arial", bold: true, color: "#FFFFFF", size: 10 },
};
sheet.getRangeByIndexes(1, index.Khabar, rows.length, 1).format.wrapText = true;
sheet.getRangeByIndexes(1, index.Date, rows.length, 1).format.numberFormat = "yyyy-mm-dd";
for (let i = 0; i < headers.length; i += 1) {
  sheet.getRangeByIndexes(0, i, rows.length + 1, 1).format.columnWidth =
    headers[i] === "Khabar" ? 80 : headers[i] === "NOTE" ? 18 : headers[i] === "Date" ? 14 : 13;
}

const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!",
  options: { useRegex: true, maxResults: 20 },
  summary: "fixed import formula error scan",
});
console.log(errors.ndjson);

const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
console.log(JSON.stringify({ outputPath, rows: rows.length, headers: headers.length }, null, 2));
