import { useMemo } from "react";
import { AIR_TYPE_COLORS, FAMILY_COLORS } from "../colors";
import { coverageWarning, peakOf } from "../mappers";
import type { Grain, TimelineResponse } from "../types";
import { EChart, type EChartOption } from "./EChart";

const colorFor = (metric: string, key: string) => (metric === "breaches" ? AIR_TYPE_COLORS[key] : FAMILY_COLORS[key]) ?? "#7f8c8d";

export const TimelineChart = ({ data, grain, height = 300 }: { data: TimelineResponse; grain: Grain; height?: number }) => {
  const option = useMemo<EChartOption>(() => {
    const dates = data.total.map((p) => p.date);
    const peak = peakOf(data);
    const gaps = grain === "day" ? data.coverage.gap_dates : [];
    const coverageByDate = new Map(data.coverage.flagged.map((flag) => [flag.date, flag.status]));
    const bars = data.series.map((s, i) => ({
      name: s.label_en,
      type: "bar" as const,
      stack: "total",
      barMaxWidth: 22,
      itemStyle: { color: colorFor(data.metric, s.key), ...(s.key === "unclassified" ? { decal: { symbol: "rect", dashArrayX: [1, 0], dashArrayY: [2, 3], rotation: Math.PI / 4 } } : {}) },
      emphasis: { focus: "series" as const },
      data: s.points.map((p) => p.value),
      ...(i === data.series.length - 1 && gaps.length
        ? { markArea: { silent: true, itemStyle: { color: "rgba(140,160,175,0.18)", decal: { symbol: "rect", dashArrayX: [1, 0], dashArrayY: [2, 3], rotation: -Math.PI / 4, color: "rgba(80,99,115,0.4)" } }, data: gaps.map((g) => [{ xAxis: g }, { xAxis: g }]) } }
        : {}),
    }));
    return {
      animation: false,
      grid: { left: 44, right: 16, top: 48, bottom: 40 },
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, formatter: (items: Array<{ axisValue: string; marker: string; seriesName: string; value: number }>) => {
        const date = items[0]?.axisValue;
        const coverage = date ? coverageByDate.get(date) : undefined;
        const lines = items.map((item) => `${item.marker}${item.seriesName}: <strong>${item.value}</strong>`);
        const warning = coverageWarning(coverage);
        return [`<strong>${date ?? ""}</strong>`, ...lines, warning ? `<span style="color:#506373">${warning}</span>` : ""].filter(Boolean).join("<br/>");
      } },
      legend: { top: 0, type: "plain", width: "90%", textStyle: { color: "#506373", fontSize: 12 } },
      xAxis: { type: "category", data: dates, axisLabel: { color: "#506373", fontSize: 12, hideOverlap: true }, axisLine: { lineStyle: { color: "#b8c7d3" } } },
      yAxis: { type: "value", minInterval: 1, axisLabel: { color: "#506373", fontSize: 12 }, splitLine: { lineStyle: { color: "#dbe5ed" } } },
      series: [
        ...bars,
        {
          name: "7-day average",
          type: "line" as const,
          smooth: true,
          symbol: "none",
          lineStyle: { color: "#0b2236", width: 2 },
          itemStyle: { color: "#0b2236" },
          data: data.moving_average_7d.map((p) => p.value),
          z: 5,
          ...(peak ? { markPoint: { symbolSize: 44, itemStyle: { color: "#bc8e38" }, label: { color: "#0b2236", fontSize: 11, fontWeight: 600 }, data: [{ name: "Peak", coord: [dates[peak.index], peak.value], value: peak.value }] } } : {}),
        },
      ],
    } as EChartOption;
  }, [data, grain]);

  const summary = `Stacked bar chart of ${data.metric} per ${grain} by ${data.metric === "breaches" ? "air type" : "action family"} with a 7-day moving average. Total ${data.total.reduce((a, p) => a + p.value, 0)}.`;
  return <EChart option={option} height={height} ariaLabel={summary} />;
};
