import { useMemo } from "react";
import { AIR_TYPE_COLORS, familyColor } from "../../colors";
import { formatNumber } from "../../mappers";
import type { ActionTrend, Metric, PeriodComparison, ShareRow } from "../../types";
import { EChart, type EChartOption } from "../EChart";

export const seriesColor = (metric: Metric, key: string): string =>
  metric === "breaches" ? AIR_TYPE_COLORS[key] ?? "#7f8c8d" : familyColor(key);

const axisLabel = { color: "#506373", fontSize: 12 };
const tooltipBox = { borderColor: "#dbe5ed", textStyle: { color: "#0b2236", fontSize: 12 } };

/** Share of the metric per action family (or air type). Pie only up to 7 slices; the legend lists all. */
export const ActionShareDonut = ({ metric, rows, total, height = 260 }: { metric: Metric; rows: ShareRow[]; total: number; height?: number }) => {
  const option = useMemo<EChartOption>(() => ({
    animation: false,
    tooltip: { trigger: "item", ...tooltipBox, formatter: (p: { marker: string; name: string; value: number; percent: number }) =>
      `${p.marker}${p.name}<br/><strong>${formatNumber(p.value)}</strong> (${p.percent}%)` },
    title: { text: formatNumber(total), subtext: "total", left: "center", top: "38%", textStyle: { fontSize: 20, fontWeight: 600, color: "#0b2236" }, subtextStyle: { color: "#506373", fontSize: 12 } },
    series: [{
      type: "pie", radius: ["56%", "80%"], center: ["50%", "50%"], avoidLabelOverlap: true, label: { show: false },
      itemStyle: { borderColor: "#fff", borderWidth: 2 },
      data: rows.map((r) => ({ name: r.label_en, value: r.value, itemStyle: { color: seriesColor(metric, r.key) } })),
    }],
  }), [metric, rows, total]);
  const summary = `Donut chart: ${rows.map((r) => `${r.label_en} ${r.share_pct ?? 0}%`).join(", ")}.`;
  return <EChart option={option} height={height} ariaLabel={summary} />;
};

/** One small line chart: a single family over the period. ``yMax`` shares one scale across the grid. */
export const SmallTrend = ({ label, color, points, yMax, height = 96 }: {
  label: string;
  color: string;
  points: Array<{ date: string; value: number }>;
  yMax?: number;
  height?: number;
}) => {
  const option = useMemo<EChartOption>(() => ({
    animation: false,
    grid: { left: 30, right: 6, top: 8, bottom: 18 },
    tooltip: { trigger: "axis", ...tooltipBox, formatter: (items: Array<{ axisValue: string; value: number }>) =>
      `${items[0]?.axisValue ?? ""}<br/>${label}: <strong>${formatNumber(items[0]?.value ?? 0)}</strong>` },
    xAxis: { type: "category", data: points.map((p) => p.date), axisLabel: { show: false }, axisTick: { show: false }, axisLine: { lineStyle: { color: "#dbe5ed" } } },
    yAxis: { type: "value", minInterval: 1, max: yMax, axisLabel: { ...axisLabel, fontSize: 10 }, splitLine: { lineStyle: { color: "#eef2f6" } } },
    series: [{ type: "line", data: points.map((p) => p.value), symbol: "none", lineStyle: { color, width: 1.8 },
      areaStyle: { color, opacity: 0.12 } }],
  }), [label, color, points, yMax]);
  return <EChart option={option} height={height} ariaLabel={`${label}: ${points.reduce((a, p) => a + p.value, 0)} in the period`} />;
};

export const ActionTrendGrid = ({ trend, sameScale }: { trend: ActionTrend; sameScale: boolean }) => (
  <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
    {trend.series.map((s) => (
      <li key={s.key} className="min-w-0 rounded-md border border-border p-2">
        <div className="flex items-baseline justify-between gap-2 text-caption">
          <span className="flex min-w-0 items-center gap-1.5 font-semibold">
            <span className="inline-block h-2.5 w-2.5 shrink-0 rounded-sm" style={{ background: seriesColor(trend.metric, s.key) }} aria-hidden="true" />
            <span className="truncate" title={s.label_en}>{s.label_en}</span>
          </span>
          <span className="shrink-0 tabular-nums text-text-muted">{formatNumber(s.total)}</span>
        </div>
        <SmallTrend label={s.label_en} color={seriesColor(trend.metric, s.key)} points={s.points} yMax={sameScale ? Math.max(1, trend.max_point) : undefined} />
      </li>
    ))}
  </ul>
);

/** Current vs previous period per caza, horizontal grouped bars with the % change at the end. */
export const PeriodComparisonChart = ({ data }: { data: PeriodComparison }) => {
  const rows = useMemo(() => [...data.rows].sort((a, b) => b.current - a.current || b.previous - a.previous).slice(0, 15).reverse(), [data]);
  const option = useMemo<EChartOption>(() => ({
    animation: false,
    grid: { left: 112, right: 64, top: 28, bottom: 24 },
    legend: { top: 0, left: 0, textStyle: { color: "#506373", fontSize: 12 } },
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, ...tooltipBox, formatter: (items: Array<{ dataIndex: number }>) => {
      const r = rows[items[0]?.dataIndex ?? 0];
      if (!r) return "";
      const pct = r.pct === null ? "new" : `${r.pct > 0 ? "+" : ""}${r.pct}%`;
      return `<strong>${r.name_en}</strong><br/>This period: <strong>${formatNumber(r.current)}</strong><br/>Previous: ${formatNumber(r.previous)}<br/>Change: ${pct}`;
    } },
    xAxis: { type: "value", minInterval: 1, axisLabel, splitLine: { lineStyle: { color: "#dbe5ed" } } },
    yAxis: { type: "category", data: rows.map((r) => r.name_en), axisLabel: { ...axisLabel, width: 104, overflow: "truncate" } },
    series: [
      { name: "Previous period", type: "bar", data: rows.map((r) => r.previous), itemStyle: { color: "#b8c7d3" }, barGap: "10%", barMaxWidth: 12 },
      { name: "This period", type: "bar", data: rows.map((r) => r.current), itemStyle: { color: "#082d6f" }, barMaxWidth: 12,
        label: { show: true, position: "right", fontSize: 11, color: "#506373", formatter: (p: { dataIndex: number }) => {
          const pct = rows[p.dataIndex]?.pct;
          return pct === null || pct === undefined ? "new" : `${pct > 0 ? "+" : ""}${pct}%`;
        } } },
    ],
  }), [rows]);
  const summary = `Grouped bars per caza, this period vs previous: ${rows.slice().reverse().slice(0, 5).map((r) => `${r.name_en} ${r.current} vs ${r.previous}`).join("; ")}.`;
  return <EChart option={option} height={Math.max(160, rows.length * 30 + 56)} ariaLabel={summary} />;
};
