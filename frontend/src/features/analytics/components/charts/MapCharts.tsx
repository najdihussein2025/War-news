import { useMemo } from "react";
import { formatNumber } from "../../mappers";
import type { Pareto } from "../../types";
import { EChart, type EChartOption } from "../EChart";

const axisLabel = { color: "#506373", fontSize: 12 };
export const PARETO_CHART_LIMIT = 100;

/** Villages by value (bars) with the cumulative share of the total (line, right axis, 0-100%). */
export const ParetoChart = ({ data, metricLabel, height = 320 }: { data: Pareto; metricLabel: string; height?: number }) => {
  const rows = useMemo(() => data.rows.slice(0, PARETO_CHART_LIMIT), [data]);
  const option = useMemo<EChartOption>(() => ({
    animation: false,
    grid: { left: 44, right: 48, top: 36, bottom: 28 },
    legend: { top: 0, left: 0, textStyle: { color: "#506373", fontSize: 12 } },
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, borderColor: "#dbe5ed", textStyle: { color: "#0b2236", fontSize: 12 },
      formatter: (items: Array<{ dataIndex: number }>) => {
        const r = rows[items[0]?.dataIndex ?? 0];
        return r ? `<strong>#${r.rank} ${r.name_en}</strong> <span dir="rtl">${r.name_ar ?? ""}</span><br/>${metricLabel}: <strong>${formatNumber(r.value)}</strong><br/>Cumulative: ${r.cumulative_pct}% of the total` : "";
      } },
    xAxis: { type: "category", data: rows.map((r) => r.name_en), axisLabel: { show: false }, axisTick: { show: false }, axisLine: { lineStyle: { color: "#b8c7d3" } } },
    yAxis: [
      { type: "value", minInterval: 1, axisLabel, splitLine: { lineStyle: { color: "#dbe5ed" } } },
      { type: "value", min: 0, max: 100, axisLabel: { ...axisLabel, formatter: "{value}%" }, splitLine: { show: false } },
    ],
    series: [
      { name: metricLabel, type: "bar", data: rows.map((r) => r.value), itemStyle: { color: "#082d6f" }, barMaxWidth: 14 },
      { name: "Cumulative share", type: "line", yAxisIndex: 1, data: rows.map((r) => r.cumulative_pct), symbol: "none",
        lineStyle: { color: "#bc8e38", width: 2 }, itemStyle: { color: "#bc8e38" },
        markLine: { silent: true, symbol: "none", label: { position: "insideStartTop", color: "#506373", fontSize: 11, formatter: "{b} of the total" }, lineStyle: { color: "#8ca0af", type: "dashed" },
          data: [{ name: "80%", yAxis: 80 }, { name: "50%", yAxis: 50 }] } },
    ],
  }), [rows, metricLabel]);
  const s = data.summary;
  const summary = `Pareto chart of ${data.villages_hit} villages: the top 10 hold ${s.top10_share_pct ?? 0}% of the total; 50% comes from ${s.villages_for_50_pct ?? 0} villages and 80% from ${s.villages_for_80_pct ?? 0}.`;
  return <EChart option={option} height={height} ariaLabel={summary} />;
};
