import { DISPUTED_LINE, interpolateSequential, linearTicks, NO_DATA_COLOR, type MapScale } from "../colors";
import { formatNumber } from "../mappers";

const GRADIENT = `linear-gradient(to right, ${[0, 0.25, 0.5, 0.75, 1].map((t) => interpolateSequential(t)).join(", ")})`;

/** Sits inside the map (bottom-left). Its height is capped by the map box, so it scrolls instead of being clipped. */
export const MapLegend = ({ scale, metricLabel }: { scale: MapScale; metricLabel: string }) => (
  <div className="max-h-[calc(100%-1.5rem)] w-[200px] overflow-auto rounded-md border border-border bg-surface-raised/95 p-2.5 text-caption shadow-raised" aria-label="Map legend">
    <div className="mb-1.5 font-semibold text-text-primary">{metricLabel}</div>
    {scale.kind === "linear" ? (
      <div>
        <div className="h-3 rounded-sm border border-black/10" style={{ background: GRADIENT }} aria-hidden="true" />
        <div className="mt-0.5 flex justify-between tabular-nums">
          {linearTicks(scale.max).map((t) => <span key={t}>{formatNumber(t)}</span>)}
        </div>
        <p className="mt-1 text-text-muted">Linear scale from 0 to the highest area; values printed on the map.</p>
      </div>
    ) : (
      <ul className="space-y-1">
        {scale.legend.map((e) => (
          <li key={e.color + e.to} className="flex items-center gap-2 tabular-nums">
            <span className="inline-block h-3 w-5 rounded-sm border border-black/10" style={{ background: e.color }} aria-hidden="true" />
            {e.from === e.to ? formatNumber(e.to) : `${formatNumber(e.from)} – ${formatNumber(e.to)}`}
          </li>
        ))}
      </ul>
    )}
    <ul className="mt-1 space-y-1">
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
