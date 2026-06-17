import fs from "node:fs/promises";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const project = "E:/stock_ranking/us_stock_data_project";
const csvPath = `${project}/data/processed/nasdaq100_atr_relative_strength.csv`;
const xlsxPath = `${project}/data/processed/nasdaq100_atr_relative_strength.xlsx`;
const fallbackXlsxPath = `${project}/data/processed/nasdaq100_atr_relative_strength_latest.xlsx`;
const previewPath = `${project}/data/processed/nasdaq100_atr_relative_strength_preview.png`;

function parseCsv(text) {
  const rows = [];
  let row = [];
  let cell = "";
  let inQuotes = false;

  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i];
    const next = text[i + 1];
    if (ch === "\"") {
      if (inQuotes && next === "\"") {
        cell += "\"";
        i += 1;
      } else {
        inQuotes = !inQuotes;
      }
    } else if (ch === "," && !inQuotes) {
      row.push(cell);
      cell = "";
    } else if ((ch === "\n" || ch === "\r") && !inQuotes) {
      if (ch === "\r" && next === "\n") i += 1;
      row.push(cell);
      cell = "";
      if (row.some((value) => value !== "")) rows.push(row);
      row = [];
    } else {
      cell += ch;
    }
  }
  if (cell.length || row.length) {
    row.push(cell);
    if (row.some((value) => value !== "")) rows.push(row);
  }
  return rows;
}

function colName(index) {
  let n = index;
  let name = "";
  while (n >= 0) {
    name = String.fromCharCode((n % 26) + 65) + name;
    n = Math.floor(n / 26) - 1;
  }
  return name;
}

const rawRows = parseCsv((await fs.readFile(csvPath, "utf8")).replace(/^\uFEFF/, ""));
const headers = rawRows[0];
const data = rawRows.slice(1).map((row) =>
  row.map((value, index) => {
    if (index === 1 || index === 2 || index === 3) return value;
    const numeric = Number(value);
    return Number.isFinite(numeric) ? numeric : value;
  }),
);

const matrix = [headers, ...data];
const rowCount = matrix.length;
const colCount = headers.length;
const lastCol = colName(colCount - 1);

const workbook = Workbook.create();
const sheet = workbook.worksheets.add("ATR Ranking");
sheet.showGridLines = false;
sheet.getRangeByIndexes(0, 0, rowCount, colCount).values = matrix;

sheet.getRange(`A1:${lastCol}1`).format = {
  fill: "#111827",
  font: { bold: true, color: "#FFFFFF" },
  wrapText: true,
};
sheet.getRange(`A1:${lastCol}${rowCount}`).format.borders = {
  preset: "all",
  style: "thin",
  color: "#D1D5DB",
};
sheet.freezePanes.freezeRows(1);

sheet.getRange(`A2:A${rowCount}`).format = {
  fill: "#DBEAFE",
  font: { bold: true, color: "#1E3A8A" },
};
sheet.getRange(`A2:A${rowCount}`).format.numberFormat = "0";
sheet.getRange(`E2:H${rowCount}`).format.numberFormat = "0.00";
sheet.getRange(`I2:J${rowCount}`).format.numberFormat = "0.00";

for (let i = 0; i < data.length; i += 1) {
  if (data[i][1] === "QQQ") {
    const excelRow = i + 2;
    sheet.getRange(`A${excelRow}:${lastCol}${excelRow}`).format = {
      fill: "#DC2626",
      font: { bold: true, color: "#FFFFFF" },
    };
  }
}

sheet.getRange(`I2:I${rowCount}`).conditionalFormats.add("colorScale", {
  thresholds: ["min", "50%", "max"],
  colors: ["#FEE2E2", "#FEF3C7", "#DCFCE7"],
});

const widths = [58, 78, 130, 92, 92, 105, 138, 82, 95, 135];
for (let column = 0; column < Math.min(widths.length, colCount); column += 1) {
  sheet.getRangeByIndexes(0, column, rowCount, 1).format.columnWidthPx = widths[column];
}
sheet.getRange(`A1:${lastCol}${rowCount}`).format.rowHeightPx = 24;
sheet.getRange("A1").format.rowHeightPx = 40;

const inspect = await workbook.inspect({
  kind: "table",
  range: `ATR Ranking!A1:${lastCol}12`,
  include: "values,formulas",
  tableMaxRows: 12,
  tableMaxCols: colCount,
  maxChars: 3000,
});
console.log(inspect.ndjson);

const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 50 },
  maxChars: 1000,
});
console.log(errors.ndjson);

const preview = await workbook.render({
  sheetName: "ATR Ranking",
  range: `A1:${lastCol}${Math.min(rowCount, 45)}`,
  scale: 1,
  format: "png",
});
await fs.writeFile(previewPath, new Uint8Array(await preview.arrayBuffer()));

const output = await SpreadsheetFile.exportXlsx(workbook);
try {
  await output.save(xlsxPath);
} catch (error) {
  if (error && error.code === "EBUSY") {
    await output.save(fallbackXlsxPath);
    console.log(`Primary file is busy; saved fallback ${fallbackXlsxPath}`);
  } else {
    throw error;
  }
}
console.log(`Preview ${previewPath}`);
console.log(`Saved ${xlsxPath}`);
