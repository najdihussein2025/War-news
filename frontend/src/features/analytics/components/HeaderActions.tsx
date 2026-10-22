import { useState } from "react";
import { Dialog } from "../../../components/ui/Dialog";
import { formatDate, formatRelativeTime } from "../../../lib/formatters";
import { cn } from "../../../lib/cn";
import { downloadExport } from "../api";
import { toApiParams } from "../filters";
import type { AnalyticsFilters, MetaResponse } from "../types";

export const MethodologyModal = ({ onClose }: { onClose: () => void }) => (
  <Dialog title="Methodology" eyebrow="How these numbers are produced" onClose={onClose} size="xl">
    <div className="space-y-4 text-small leading-relaxed">
      <section><h3 className="font-semibold">Headline ("counted")</h3>
        <p>An incident counts when its verification status is <em>verified</em> or <em>auto processed</em>, it is not deleted or rejected, and its action family counts in the headline. The toggle <em>Include pending review</em> adds the pending bucket.</p></section>
      <section><h3 className="font-semibold">Pending review</h3>
        <p>Any non-deleted, non-rejected incident with status <em>needs verification</em>, plus incidents in an unclassified / needs-review action family. They are excluded from headline totals by default and shown separately.</p></section>
      <section><h3 className="font-semibold">Casualties</h3>
        <p>Totals are the incident's reported deaths and injuries. The male / female / children split comes from the incident details; the remainder is "unspecified". A shared toll from a multi-village bulletin is stored on one incident only and counted once; it is <em>not attributed to a specific village</em>.</p></section>
      <section><h3 className="font-semibold">Air violations</h3>
        <ul className="list-disc pl-5">
          <li>Warplanes: per mohafaza, anchored 10-minute windows.</li>
          <li>Drones / surveillance: per caza; 6-hour windows in the listed cazas, otherwise once per day.</li>
          <li>Helicopters: once per village named. Spy balloons: once per caza named.</li>
          <li>Map levels: mohafaza shows all types; caza shows drones, balloons and helicopters; village shows helicopters only.</li>
        </ul></section>
      <section><h3 className="font-semibold">Geography and history</h3>
        <p>Villages are placed on the OCHA/HDX boundaries by code, never by name. Data from before the reset is read from a frozen archive and is never recalculated; live data excludes anything already archived.</p></section>
      <section><h3 className="font-semibold">Coverage</h3>
        <p>Low and no-coverage days are shown with hatched bands and an asterisk on affected peaks. They mean too few or no messages arrived, which is different from zero incidents.</p></section>
    </div>
  </Dialog>
);

const button = "h-8 shrink-0 rounded-md px-3 text-small focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring";

/** Freshness, Methodology and Export, rendered into the analytics top bar. */
export const HeaderActions = ({ meta, filters, onMethodologyOpen }: { meta: MetaResponse | undefined; filters: AnalyticsFilters; onMethodologyOpen: () => void }) => {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const refreshed = meta?.last_refresh ?? null;
  const ageMin = refreshed ? (Date.now() - new Date(refreshed).getTime()) / 60000 : null;
  const stale = ageMin !== null && ageMin > 15;
  const queued = meta?.refresh_queue ?? 0;

  const exportNow = async () => {
    setBusy(true);
    setError("");
    try {
      await downloadExport(toApiParams(filters));
    } catch {
      setError("Export failed. Try again.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <p className={cn("hidden min-w-0 items-center gap-1.5 truncate text-caption tabular-nums md:flex", stale ? "font-semibold text-warning" : "text-text-muted")}
        title={refreshed ? `Last refresh ${new Date(refreshed).toLocaleString()}` : undefined} role="status">
        <span className={cn("inline-block h-2 w-2 shrink-0 rounded-full", stale ? "bg-warning" : "bg-success")} aria-hidden="true" />
        <span className="truncate">
          Updated {refreshed ? formatRelativeTime(refreshed) : "never"}
          {queued > 0 ? ` · ${queued} date${queued === 1 ? "" : "s"} queued` : ""}
          {stale ? <span className="sr-only"> (refresh is behind)</span> : null}
        </span>
      </p>
      {error ? <span role="alert" className="shrink-0 text-caption text-danger">{error}</span> : null}
      <button type="button" onClick={onMethodologyOpen} className={cn(button, "hidden border border-border font-medium hover:bg-surface-muted sm:block")}>Methodology</button>
      <button type="button" disabled={busy} onClick={() => void exportNow()} aria-label="Export to Excel"
        className={cn(button, "bg-brand-navy font-semibold text-text-inverse hover:bg-brand-navy-hover disabled:opacity-60")}>
        {busy ? "Exporting…" : <><span className="lg:hidden">Export</span><span className="hidden lg:inline">Export to Excel</span></>}
      </button>
    </>
  );
};

export const ArchiveNote = ({ meta }: { meta: MetaResponse | undefined }) => (
  <p className="text-caption text-text-muted">
    {meta?.archive.cutoff_date ? `History up to ${formatDate(meta.archive.cutoff_date)} comes from the frozen archive; later dates are live.` : "No archive yet: all figures are live data."}
  </p>
);
