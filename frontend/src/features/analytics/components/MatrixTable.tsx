import { useMemo } from "react";
import { colorForValue, quantileBreaks, textOn } from "../colors";
import { formatNumber } from "../mappers";
import type { MatrixResponse } from "../types";
import { ErrorBlock, FamilyDot, Skeleton, errorMessage } from "./common";
import { familyColor } from "../colors";

const SHORT_LABELS: Record<string, string> = {
  airstrikes: "Airstrikes", drone_strikes: "Drones", artillery: "Artillery", flares_phosphorus: "Flares",
  demolitions: "Demolition", gunfire: "Gunfire", incursions: "Incursions", other: "Other",
};

type Props = {
  data?: MatrixResponse;
  loading: boolean;
  error: unknown;
  onRetry: () => void;
  onCell: (caza: string, family: string | null) => void;
};

export const MatrixTable = ({ data, loading, error, onRetry, onCell }: Props) => {
  const breaks = useMemo(() => quantileBreaks((data?.rows ?? []).flatMap((r) => Object.values(r.cells))), [data]);
  if (error && !data) return <ErrorBlock message={errorMessage(error)} onRetry={onRetry} />;
  if (!data || loading && !data) return <Skeleton className="h-96" />;
  const topRows = [...data.rows].filter((row) => row.total > 0).sort((a, b) => b.total - a.total || a.name_en.localeCompare(b.name_en)).slice(0, 7);
  return (
    <div className="overflow-auto">
      <table className="w-full border-collapse text-caption">
        <caption className="sr-only">Number of {data.metric} by caza (rows) and action family (columns)</caption>
        <thead>
          <tr>
            <th scope="col" className="sticky left-0 bg-surface-raised px-2 py-2 text-left text-text-muted">Caza</th>
            {data.columns.map((c) => (
              <th key={c.code} scope="col" className="px-1 py-2 text-center align-bottom font-medium" title={c.name_en}>
                <span className="flex flex-col items-center gap-1"><FamilyDot color={familyColor(c.code)} /><span className="whitespace-nowrap leading-tight">{SHORT_LABELS[c.code] ?? c.name_en}</span></span>
              </th>
            ))}
            <th scope="col" className="px-2 py-2 text-right text-text-muted">Total</th>
          </tr>
        </thead>
        <tbody>
          {topRows.map((row) => (
            <tr key={row.code} className="border-t border-border">
              <th scope="row" className="sticky left-0 bg-surface-raised px-2 py-1 text-left font-medium">
                <button type="button" onClick={() => onCell(row.code, null)} className="text-left hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus-ring">
                  {row.name_en} <span dir="rtl" lang="ar" className="text-text-muted">{row.name_ar}</span>
                </button>
              </th>
              {data.columns.map((c) => {
                const value = row.cells[c.code] ?? 0;
                const bg = colorForValue(value, breaks);
                return (
                  <td key={c.code} className="p-0 text-center tabular-nums">
                    <button type="button" onClick={() => onCell(row.code, c.code)} aria-label={`${row.name_en}, ${c.name_en}: ${value}`}
                      className="h-7 w-full min-w-9 focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-focus-ring"
                      style={{ background: value > 0 ? bg : "transparent", color: value > 0 ? textOn(bg) : "#8ca0af" }}>{value > 0 ? formatNumber(value) : "·"}</button>
                  </td>
                );
              })}
              <td className="px-2 text-right font-semibold tabular-nums">{formatNumber(row.total)}</td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr className="border-t-2 border-border-strong font-semibold">
            <th scope="row" className="sticky left-0 bg-surface-raised px-2 py-2 text-left">Total</th>
            {data.columns.map((c) => <td key={c.code} className="text-center tabular-nums">{formatNumber(data.column_totals[c.code] ?? 0)}</td>)}
            <td className="px-2 text-right tabular-nums">{formatNumber(data.grand_total)}</td>
          </tr>
        </tfoot>
      </table>
    </div>
  );
};
