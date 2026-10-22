import { useMemo } from "react";
import { AIR_TYPE_COLORS, FAMILY_COLORS } from "../colors";
import { coverageWarning, peakOf } from "../mappers";
import type { Grain, TimelineResponse } from "../types";
import { EChart, type EChartOption } from "./EChart";

const colorFor = (metric: string, key: string) => (metric === "breaches" ? AIR_TYPE_COLORS[key] : FAMILY_COLORS[key]) ?? "#7f8c8d";
const DEATHS_COLOR = "#9b2c2c";
const INJURIES_COLOR = "#bc8e38";

export type TimelineMode = "stacked" | "lines";

/**
 * Metric per bucket by action family (or air type) with the 7-day average.
 * ``mode`` stacks the families as bars or draws one line each; ``overlay`` adds deaths
 * and injuries on a second axis so the two scales never squash each other.
 */
export const TimelineChart = ({ data, grain, height = 300, mode = "stacked", overlay = false }: {
  data: TimelineResponse;
  grain: Grain;
  height?: number;
  mode?: TimelineMode;
  overlay?: boolean;
}) => {
  const showOverlay = overlay && data.metric !== "breaches" && (data.casualties?.length ?? 0) > 0;
  const option = useMemo<EChartOption>(() => {
    const dates = data.total.map((p) => p.date);
    const peak = peakOf(data);
    const gaps = grain === "day" ? data.coverage.gap_dates : [];
    const coverageByDate = new Map(data.coverage.flagged.map((flag) => [flag.date, flag.status]));
    const families = data.series.map((s, i) => ({
      name: s.label_en,
      ...(mode === "stacked"
        ? { type: "bar" as const, stack: "total", barMaxWidth: 22 }
        : { type: "line" as const, symbol: "none", smooth: false, lineStyle: { width: 1.8 } }),
      itemStyle: { color: colorFor(data.metric, s.key), ...(s.key === "unclassified" && mode === "stacked" ? { decal: { symbol: "rect", dashArrayX: [1, 0], dashArrayY: [2, 3], rotation: Math.PI / 4 } } : {}) },
      emphasis: { focus: "series" as const },
      data: s.points.map((p) => p.value),
      ...(i === data.series.length - 1 && gaps.length
        ? { markArea: { silent: true, itemStyle: { color: "rgba(140,160,175,0.18)", decal: { symbol: "rect", dashArrayX: [1, 0], dashArrayY: [2, 3], rotation: -Math.PI / 4, color: "rgba(80,99,115,0.4)" } }, data: gaps.map((g) => [{ xAxis: g }, { xAxis: g }]) } }
        : {}),
    }));
    const casualtyLine = (name: string, color: string, values: number[]) => ({
      name, type: "line" as const, yAxisIndex: 1, symbol: "circle", symbolSize: 5, showSymbol: false,
      lineStyle: { color, width: 2, type: "dashed" as const }, itemStyle: { color }, data: values, z: 6,
    });
    const casualties = showOverlay ? [
      casualtyLine("Deaths", DEATHS_COLOR, (data.casualties ?? []).map((p) => p.deaths)),
      casualtyLine("Injuries", INJURIES_COLOR, (data.casualties ?? []).map((p) => p.injuries)),
    ] : [];
    const axisLabel = { color: "#506373", fontSize: 12 };
    return {
      animation: false,
      grid: { left: 44, right: showOverlay ? 48 : 16, top: 62, bottom: 40 },
      tooltip: { trigger: "axis", axisPointer: { type: mode === "stacked" ? "shadow" : "line" }, formatter: (items: Array<{ axisValue: string; marker: string; seriesName: string; value: number }>) => {
        const date = items[0]?.axisValue;
        const coverage = date ? coverageByDate.get(date) : undefined;
        const lines = items.map((item) => `${item.marker}${item.seriesName}: <strong>${item.value}</strong>`);
        const warning = coverageWarning(coverage);
        return [`<strong>${date ?? ""}</strong>`, ...lines, warning ? `<span style="color:#506373">${warning}</span>` : ""].filter(Boolean).join("<br/>");
      } },
      legend: { top: 0, left: 0, right: 8, type: "plain", itemGap: 14, textStyle: { color: "#506373", fontSize: 12 } },
      xAxis: { type: "category", data: dates, axisLabel: { ...axisLabel, hideOverlap: true }, axisLine: { lineStyle: { color: "#b8c7d3" } } },
      yAxis: [
        { type: "value", minInterval: 1, axisLabel, splitLine: { lineStyle: { color: "#dbe5ed" } } },
        ...(showOverlay ? [{ type: "value", minInterval: 1, name: "Casualties", nameTextStyle: axisLabel, axisLabel, splitLine: { show: false } }] : []),
      ],
      series: [
        ...families,
        {
          name: "7-day average",
          type: "line" as const,
          smooth: true,
          symbol: "none",
          lineStyle: { color: "#0b2236", width: 2 },
          itemStyle: { color: "#0b2236" },
          data: data.moving_average_7d.map((p) => p.value),
          z: 5,
          ...(peak && mode === "stacked" ? { markPoint: { symbolSize: 44, itemStyle: { color: "#bc8e38" }, label: { color: "#0b2236", fontSize: 11, fontWeight: 600 }, data: [{ name: "Peak", coord: [dates[peak.index], peak.value], value: peak.value }] } } : {}),
        },
        ...casualties,
      ],
    } as EChartOption;
  }, [data, grain, mode, showOverlay]);

  const kind = mode === "stacked" ? "Stacked bar chart" : "Line chart";
  const summary = `${kind} of ${data.metric} per ${grain} by ${data.metric === "breaches" ? "air type" : "action family"} with a 7-day moving average${showOverlay ? ", deaths and injuries on a second axis" : ""}. Total ${data.total.reduce((a, p) => a + p.value, 0)}.`;
  return <EChart option={option} height={height} ariaLabel={summary} />;
};
