import { useState } from "react";
import { formatDate } from "../../../../lib/formatters";
import { formatNumber } from "../../mappers";
import type { Grain, OverviewTab } from "../../types";
import { ActionShareDonut, ActionTrendGrid, PeriodComparisonChart, seriesColor } from "../charts/OverviewCharts";
import { CsvButton, EmptyState, ErrorBlock, SectionCard, Skeleton, Toggle, errorMessage } from "../common";
import { PeaksCards } from "../PeaksCards";
import { TimelineChart, type TimelineMode } from "../TimelineChart";

type Props = {
  data: OverviewTab | undefined;
  error: unknown;
  onRetry: () => void;
  grain: Grain;
  onGrain: (grain: Grain) => void;
  metricLabel: string;
  /** e.g. "2026-09-23_2026-10-22": appended to every CSV file name. */
  fileSuffix: string;
  onViewIncidents: () => void;
};

const GRAINS: Array<[Grain, string]> = [["day", "Day"], ["week", "Week"], ["month", "Month"]];

/** Everything on the Overview tab below the map: timeline, peaks, action share and trends, period comparison. */
export const OverviewSections = ({ data, error, onRetry, grain, onGrain, metricLabel, fileSuffix, onViewIncidents }: Props) => {
  const [mode, setMode] = useState<TimelineMode>("stacked");
  const [overlay, setOverlay] = useState<"off" | "on">("off");
  const [sameScale, setSameScale] = useState<"same" | "own">("same");
  const failed = error && !data ? <ErrorBlock message={errorMessage(error)} onRetry={onRetry} /> : null;
  const breaches = data?.timeline.metric === "breaches";
  const groupLabel = breaches ? "air type" : "action family";

  const timeline = data?.timeline;
  const share = data?.action_share;
  const trend = data?.action_trend;
  const period = data?.period_comparison;

  return (
    <>
      <div className="col-span-12">
        <SectionCard id="timeline" title="Timeline" subtitle={`${metricLabel} per ${grain}, by ${groupLabel}, with the 7-day average${overlay === "on" && !breaches ? "; deaths and injuries on the right axis" : ""}`}
          actions={(
            <div className="flex flex-wrap items-center gap-2">
              <Toggle label="Chart type" value={mode} onChange={setMode} options={[["stacked", "Stacked"], ["lines", "Lines per action"]]} />
              {!breaches ? <Toggle label="Deaths and injuries overlay" value={overlay} onChange={setOverlay} options={[["off", "No overlay"], ["on", "+ Deaths & injuries"]]} /> : null}
              <Toggle label="Time grain" value={grain} onChange={onGrain} options={GRAINS} />
              <CsvButton filename={`timeline_${grain}_${fileSuffix}`} disabled={!timeline}
                headers={["date", ...(timeline?.series.map((s) => s.label_en) ?? []), "total", "7-day average", ...(timeline?.casualties?.length ? ["deaths", "injuries"] : [])]}
                rows={() => (timeline?.total ?? []).map((p, i) => [p.date, ...timeline!.series.map((s) => s.points[i]?.value ?? 0), p.value,
                  timeline!.moving_average_7d[i]?.value ?? "", ...(timeline!.casualties?.length ? [timeline!.casualties[i]?.deaths ?? 0, timeline!.casualties[i]?.injuries ?? 0] : [])])} />
              <button type="button" onClick={onViewIncidents} className="h-8 rounded-md border border-border px-3 text-small hover:bg-surface-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus-ring">View incidents</button>
            </div>
          )}>
          {failed ?? (timeline ? (
            <>
              <TimelineChart data={timeline} grain={grain} height={320} mode={mode} overlay={overlay === "on"} />
              {timeline.coverage.gap_dates.length > 0 ? (
                <p className="mt-1 text-caption text-text-muted">Hatched days ({timeline.coverage.gap_dates.length}) had low or no message coverage: missing or incomplete data, not zero incidents.</p>
              ) : null}
            </>
          ) : <Skeleton className="h-[320px]" />)}
        </SectionCard>
      </div>

      <div className="col-span-12">
        <SectionCard id="peaks" title="Peaks" subtitle="Worst day and worst week in the period, with the three most affected cazas"
          actions={<CsvButton filename={`peaks_${fileSuffix}`} disabled={!data}
            headers={["metric", "unit", "start", "value", "low coverage days", "top cazas"]}
            rows={() => (["incidents", "deaths", "breaches"] as const).flatMap((m) => (["day", "week"] as const).map((u) => {
              const e = data!.peaks[m][u];
              return [m, u, e?.start ?? "", e?.value ?? "", e?.low_coverage_days ?? "", e?.top_areas.map((a) => `${a.name_en} ${a.value}`).join("; ") ?? ""];
            }))} />}>
          {failed ?? <PeaksCards data={data?.peaks} loading={!data} error={null} onRetry={onRetry} />}
        </SectionCard>
      </div>

      <div className="col-span-12 lg:col-span-5 2xl:col-span-4">
        <SectionCard id="action-share" className="h-full" title={`${breaches ? "Air type" : "Action"} share`} subtitle={`Share of ${metricLabel.toLowerCase()} in the period by ${groupLabel}`}
          actions={<CsvButton filename={`action_share_${fileSuffix}`} disabled={!share}
            headers={[groupLabel, "value", "share %"]} rows={() => (share?.rows ?? []).map((r) => [r.label_en, r.value, r.share_pct])} />}>
          {failed ?? (!share ? <Skeleton className="h-[372px]" /> : share.rows.length === 0 ? <EmptyState>Nothing recorded for these filters.</EmptyState> : (
            <>
              <ActionShareDonut metric={share.metric} rows={share.rows} total={share.total} />
              <ul className="mt-2 space-y-1 text-caption tabular-nums">
                {share.rows.map((r) => (
                  <li key={r.key} className="flex min-w-0 items-center gap-2">
                    <span className="inline-block h-2.5 w-2.5 shrink-0 rounded-sm" style={{ background: seriesColor(share.metric, r.key) }} aria-hidden="true" />
                    <span className="min-w-0 flex-1 truncate" title={r.label_en}>{r.label_en}</span>
                    <span className="shrink-0 font-semibold">{formatNumber(r.value)}</span>
                    <span className="w-12 shrink-0 text-right text-text-muted">{r.share_pct ?? 0}%</span>
                  </li>
                ))}
              </ul>
            </>
          ))}
        </SectionCard>
      </div>

      <div className="col-span-12 lg:col-span-7 2xl:col-span-8">
        <SectionCard id="action-trend" className="h-full" title={`${breaches ? "Air type" : "Action"} trends`} subtitle={`${metricLabel} per ${grain} for each ${groupLabel}`}
          actions={(
            <div className="flex items-center gap-2">
              <Toggle label="Y axis" value={sameScale} onChange={setSameScale} options={[["same", "Same scale"], ["own", "Own scale"]]} />
              <CsvButton filename={`action_trends_${grain}_${fileSuffix}`} disabled={!trend}
                headers={["date", ...(trend?.series.map((s) => s.label_en) ?? [])]}
                rows={() => (trend?.series[0]?.points ?? []).map((p, i) => [p.date, ...trend!.series.map((s) => s.points[i]?.value ?? 0)])} />
            </div>
          )}>
          {failed ?? (!trend ? <Skeleton className="h-[372px]" /> : trend.series.length === 0 ? <EmptyState>Nothing recorded for these filters.</EmptyState>
            : <ActionTrendGrid trend={trend} sameScale={sameScale === "same"} />)}
        </SectionCard>
      </div>

      <div className="col-span-12">
        <SectionCard id="period-comparison" title="This period vs the previous one, by caza"
          subtitle={period ? `${metricLabel}: ${formatDate(period.period.date_from)} – ${formatDate(period.period.date_to)} vs ${formatDate(period.previous.date_from)} – ${formatDate(period.previous.date_to)} (15 largest; labels = % change)` : "Each caza in this period and in the previous period of the same length"}
          actions={<CsvButton filename={`period_comparison_${fileSuffix}`} disabled={!period}
            headers={["caza", "caza (ar)", "this period", "previous period", "change", "change %"]}
            rows={() => (period?.rows ?? []).map((r) => [r.name_en, r.name_ar, r.current, r.previous, r.delta, r.pct])} />}>
          {failed ?? (!period ? <Skeleton className="h-[360px]" /> : period.rows.length === 0 ? <EmptyState>Nothing recorded in either period.</EmptyState>
            : <PeriodComparisonChart data={period} />)}
        </SectionCard>
      </div>
    </>
  );
};
