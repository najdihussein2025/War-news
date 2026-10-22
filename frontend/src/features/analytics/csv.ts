/** CSV for the "Download CSV" action on every chart and table: exactly the values drawn. */
export type CsvCell = string | number | boolean | null | undefined;

const cell = (value: CsvCell): string => {
  if (value === null || value === undefined) return "";
  const text = String(value);
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
};

export const toCsv = (headers: string[], rows: CsvCell[][]): string =>
  [headers, ...rows].map((row) => row.map(cell).join(",")).join("\r\n");

/** BOM first so Excel opens the Arabic names as UTF-8. */
export const downloadCsv = (filename: string, headers: string[], rows: CsvCell[][]): void => {
  const blob = new Blob(["﻿", toCsv(headers, rows)], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename.endsWith(".csv") ? filename : `${filename}.csv`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
};
