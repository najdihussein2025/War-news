import { DISPUTED_LINE, legendEntries, NO_DATA_COLOR } from "../colors";
import { formatNumber } from "../mappers";

export const MapLegend = ({ breaks, metricLabel }: { breaks: number[]; metricLabel: string }) => {
  const entries = legendEntries(breaks);
  return (
    <div className="max-w-[210px] rounded-md border border-border bg-surface-raised/95 p-2.5 text-caption shadow-raised" aria-label="Map legend">
      <div className="mb-1.5 font-semibold text-text-primary">{metricLabel}</div>
      <ul className="space-y-1">
        {entries.map((e) => (
          <li key={e.color + e.to} className="flex items-center gap-2 tabular-nums">
            <span className="inline-block h-3 w-5 rounded-sm border border-black/10" style={{ background: e.color }} aria-hidden="true" />
            {e.from === e.to ? formatNumber(e.to) : `${formatNumber(e.from)} – ${formatNumber(e.to)}`}
          </li>
        ))}
        <li className="flex items-center gap-2">
          <span className="inline-block h-3 w-5 rounded-sm border border-black/10" style={{ background: NO_DATA_COLOR }} aria-hidden="true" />
          None recorded
        </li>
        <li className="flex items-center gap-2">
          <span
            className="inline-block h-3 w-5 rounded-sm border border-black/10"
            style={{ background: `repeating-linear-gradient(135deg, transparent 0 3px, ${DISPUTED_LINE} 3px 4px)` }}
            aria-hidden="true"
          />
          Disputed area
        </li>
      </ul>
    </div>
  );
};
