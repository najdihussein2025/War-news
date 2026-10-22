import { familyColor } from "../colors";
import { toApiParams } from "../filters";
import { useRankings } from "../hooks";
import { formatNumber } from "../mappers";
import type { AnalyticsFilters, Level } from "../types";
import { EmptyState, ErrorBlock, Skeleton, errorMessage } from "./common";

const PLURAL: Record<Level, string> = { mohafaza: "mohafazat", caza: "cazas", village: "villages" };

/** Share of each action family in the period, as one stacked bar plus the five largest. */
const ActionMix = ({ mix, familyNames }: { mix: Record<string, number>; familyNames: Record<string, string> }) => {
  const entries = Object.entries(mix).filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1]);
  const total = entries.reduce((sum, [, v]) => sum + v, 0);
  if (!total) return null;
  const pct = (v: number) => `${Math.round((v / total) * 100)}%`;
  return (
    <div className="mt-auto border-t border-border pt-2">
      <h3 className="mb-1.5 text-caption font-semibold uppercase tracking-wide text-text-muted">Action mix</h3>
      <div className="flex h-2.5 overflow-hidden rounded-sm" role="img" aria-label={entries.map(([c, v]) => `${familyNames[c] ?? c} ${pct(v)}`).join(", ")}>
        {entries.map(([code, v]) => <span key={code} style={{ width: `${(v / total) * 100}%`, background: familyColor(code) }} title={`${familyNames[code] ?? code}: ${formatNumber(v)} (${pct(v)})`} />)}
      </div>
      <ul className="mt-1.5 grid grid-cols-2 gap-x-3 gap-y-0.5 text-caption tabular-nums">
        {entries.slice(0, 6).map(([code, v]) => (
          <li key={code} className="flex min-w-0 items-center gap-1.5">
            <span className="inline-block h-2.5 w-2.5 shrink-0 rounded-sm" style={{ background: familyColor(code) }} aria-hidden="true" />
            <span className="truncate">{familyNames[code] ?? code}</span>
            <span className="ml-auto text-text-muted">{pct(v)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
};

/** Side column next to the map: the ten areas with the highest value of the current metric. */
export const TopAreasPanel = ({ filters, metricLabel, onFocusArea, mix, familyNames }: {
  filters: AnalyticsFilters;
  metricLabel: string;
  onFocusArea: (code: string, level: Level) => void;
  /** Family totals for the period (from the map breakdown); empty for air breaches. */
  mix: Record<string, number>;
  familyNames: Record<string, string>;
}) => {
  const query = useRankings(toApiParams(filters, { areaCode: null }), 10);
  const rows = query.data?.rows ?? [];
  const max = Math.max(1, ...rows.map((r) => r.value));
  const total = rows.reduce((sum, r) => sum + r.value, 0);

  return (
    <section aria-labelledby="top-areas-title" className="flex h-full min-h-0 flex-col rounded-lg border border-card-border bg-card-bg p-3 shadow-raised xl:p-4">
      <div className="mb-2">
        <h2 id="top-areas-title" className="text-body font-semibold">Top 10 {PLURAL[filters.level]}</h2>
        <p className="text-caption text-text-muted">{metricLabel} in the period. Select one for its profile.</p>
      </div>
      {query.error && !query.data ? <ErrorBlock message={errorMessage(query.error)} onRetry={() => void query.refetch()} />
        : !query.data ? <Skeleton className="h-full min-h-64" />
          : rows.length === 0 ? <EmptyState>Nothing recorded for these filters.</EmptyState> : (
            <ol className="-mx-1 min-h-0 shrink space-y-0.5 overflow-auto">
              {rows.map((r) => (
                <li key={r.code}>
                  <button type="button" onClick={() => onFocusArea(r.code, r.level)}
                    className="grid w-full grid-cols-[1.5rem_minmax(0,1fr)_auto] items-center gap-x-2 rounded-md px-1 py-1.5 text-left hover:bg-surface-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus-ring">
                    <span className="text-caption tabular-nums text-text-muted">{r.rank}</span>
                    <span className="min-w-0">
                      <span className="flex items-baseline gap-1.5 text-small">
                        <span className="truncate font-medium">{r.name_en || r.name_ar || r.code}</span>
                        {r.name_ar && r.name_en ? <span dir="rtl" lang="ar" className="truncate text-caption text-text-muted">{r.name_ar}</span> : null}
                      </span>
                      <span className="mt-1 block h-1.5 rounded-sm bg-gray-100" aria-hidden="true">
                        <span className="block h-1.5 rounded-sm" style={{ width: `${(r.value / max) * 100}%`, background: r.dominant_family ? familyColor(r.dominant_family) : "#082d6f" }} />
                      </span>
                    </span>
                    <span className="text-small font-semibold tabular-nums">{formatNumber(r.value)}</span>
                  </button>
                </li>
              ))}
            </ol>
          )}
      {rows.length > 0 ? <p className="mt-1 text-caption text-text-muted tabular-nums">Shown: {formatNumber(total)} · bar colour = most frequent action</p> : null}
      <ActionMix mix={mix} familyNames={familyNames} />
    </section>
  );
};
