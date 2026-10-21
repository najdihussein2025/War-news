import { AIR_TYPES } from "../airRules";
import { AIR_TYPE_COLORS } from "../colors";
import { toApiParams } from "../filters";
import { useRankings, useTimeline } from "../hooks";
import { formatNumber } from "../mappers";
import type { AnalyticsFilters, Level, RankingRow } from "../types";
import { ErrorBlock, Skeleton, errorMessage } from "./common";
import { TimelineChart } from "./TimelineChart";

const Bars = ({ rows, onFocus }: { rows: RankingRow[]; onFocus: (code: string, level: Level) => void }) => {
  const max = Math.max(...rows.map((r) => r.value), 1);
  if (!rows.length) return <p className="text-small text-text-muted">No breaches recorded for these filters.</p>;
  return (
    <ul className="space-y-1.5">
      {rows.slice(0, 10).map((r) => (
        <li key={r.code}>
          <button type="button" onClick={() => onFocus(r.code, r.level)} className="grid w-full grid-cols-[9rem_1fr_3rem] items-center gap-2 text-left text-small hover:bg-surface-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus-ring">
            <span className="truncate">{r.name_en} <span dir="rtl" lang="ar" className="text-text-muted">{r.name_ar}</span></span>
            <span className="h-3 rounded-sm bg-gray-100"><span className="block h-3 rounded-sm bg-brand-navy" style={{ width: `${(r.value / max) * 100}%` }} /></span>
            <span className="text-right tabular-nums">{formatNumber(r.value)}</span>
          </button>
        </li>
      ))}
    </ul>
  );
};

export const AirSection = ({ filters, enabled, onFocusArea }: { filters: AnalyticsFilters; enabled: boolean; onFocusArea: (code: string, level: Level) => void }) => {
  const base = { metric: "breaches" as const, areaCode: null, families: [] as string[] };
  const grain = (new Date(filters.dateTo).getTime() - new Date(filters.dateFrom).getTime()) / 86_400_000 > 90 ? "week" : "day";
  const timeline = useTimeline(toApiParams(filters, base), grain, enabled);
  const moh = useRankings(toApiParams(filters, { ...base, level: "mohafaza" }), 10, enabled);
  const caza = useRankings(toApiParams(filters, { ...base, level: "caza" }), 10, enabled);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-3 text-caption">
        {AIR_TYPES.map((t) => (
          <span key={t.id} className="flex items-center gap-1.5"><span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: AIR_TYPE_COLORS[String(t.id)] }} aria-hidden="true" />{t.label}</span>
        ))}
      </div>
      {timeline.error && !timeline.data ? <ErrorBlock message={errorMessage(timeline.error)} onRetry={() => void timeline.refetch()} />
        : timeline.data ? <TimelineChart data={timeline.data} grain={grain} height={240} /> : <Skeleton className="h-60" />}
      <div className="grid gap-6 lg:grid-cols-2">
        <div><h3 className="mb-2 text-small font-semibold">By mohafaza</h3>{moh.data ? <Bars rows={moh.data.rows} onFocus={onFocusArea} /> : <Skeleton className="h-40" />}</div>
        <div><h3 className="mb-2 text-small font-semibold">By caza <span className="font-normal text-text-muted">(drones, balloons, helicopters)</span></h3>{caza.data ? <Bars rows={caza.data.rows} onFocus={onFocusArea} /> : <Skeleton className="h-40" />}</div>
      </div>
      <p className="rounded-md bg-surface-muted p-3 text-caption text-text-muted">
        <strong>How breaches are counted.</strong> Warplanes: per mohafaza in anchored 10-minute windows. Drones / surveillance: per caza, in 6-hour windows
        for the listed cazas and once per day elsewhere. Helicopters: once per village named. Spy balloons: once per caza named. Warplane breaches are never
        split below mohafaza, and drone breaches never below caza. Reports with no resolvable place are counted nationally only.
      </p>
    </div>
  );
};
