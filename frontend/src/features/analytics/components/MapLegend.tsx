import { DISPUTED_LINE, interpolateSequential, linearTicks, NO_DATA_COLOR, type MapScale } from "../colors";
import { formatNumber } from "../mappers";

const GRADIENT = `linear-gradient(to right, ${[0, 0.25, 0.5, 0.75, 1].map((t) => interpolateSequential(t)).join(", ")})`;
const swatch = "inline-block h-2.5 w-4 shrink-0 rounded-sm border border-black/10";

/** Compact overlay inside the map (top-left, over the sea). Never scrolls: ranges use two columns. */
export const MapLegend = ({ scale, metricLabel }: { scale: MapScale; metricLabel: string }) => (
  <div className="w-[13rem] rounded-md border border-border bg-surface-raised/95 px-2.5 py-2 text-caption leading-tight shadow-raised" aria-label="Map legend"
    title={scale.kind === "linear" ? "Linear scale from 0 to the highest area; values are printed on the map." : undefined}>
    <div className="mb-1 font-semibold text-text-primary">{metricLabel}</div>
    {scale.kind === "linear" ? (
      <div>
        <div className="h-2.5 rounded-sm border border-black/10" style={{ background: GRADIENT }} aria-hidden="true" />
        <div className="mt-0.5 flex justify-between tabular-nums text-text-muted">
          {linearTicks(scale.max).map((t) => <span key={t}>{formatNumber(t)}</span>)}
        </div>
      </div>
    ) : (
      <ul className="grid grid-cols-2 gap-x-2 gap-y-0.5">
        {scale.legend.map((e) => (
          <li key={e.color + e.to} className="flex items-center gap-1.5 tabular-nums">
            <span className={swatch} style={{ background: e.color }} aria-hidden="true" />
            {e.from === e.to ? formatNumber(e.to) : `${formatNumber(e.from)}–${formatNumber(e.to)}`}
          </li>
        ))}
      </ul>
    )}
    <ul className="mt-1.5 flex gap-3 border-t border-border pt-1.5 text-text-muted">
      <li className="flex items-center gap-1.5"><span className={swatch} style={{ background: NO_DATA_COLOR }} aria-hidden="true" />None</li>
      <li className="flex items-center gap-1.5">
        <span className={swatch} style={{ background: `repeating-linear-gradient(135deg, transparent 0 3px, ${DISPUTED_LINE} 3px 4px)` }} aria-hidden="true" />
        Disputed
      </li>
    </ul>
  </div>
);
