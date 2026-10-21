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
        <p>Incidents awaiting verification, plus incidents whose action is "Air Activity – Needs Verification" or "Unclassified / Needs Review". They are excluded from totals by default and shown separately.</p></section>
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
      <section><h3 className="font-semibold">Quiet days</h3>
        <p>A day with no ingested messages at all is drawn as a shaded band: it means no data arrived, which is different from zero incidents.</p></section>
    </div>
  </Dialog>
);

export const FooterStrip = ({ meta, filters }: { meta: MetaResponse | undefined; filters: AnalyticsFilters }) => {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const refreshed = meta?.last_refresh ?? null;
  const ageMin = refreshed ? (Date.now() - new Date(refreshed).getTime()) / 60000 : null;
  const stale = ageMin !== null && ageMin > 15;

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
    <footer className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-card-border bg-card-bg p-3 text-small shadow-raised">
      <div className="space-y-0.5">
        <p className={cn("tabular-nums", stale && "font-semibold text-warning")}>
          Data updated {refreshed ? formatRelativeTime(refreshed) : "never"}{stale ? " (refresh is behind)" : ""}
          {meta && meta.refresh_queue > 0 ? ` · ${meta.refresh_queue} date(s) queued` : ""}
        </p>
        <p className="text-caption text-text-muted">
          {meta?.archive.cutoff_date ? `History up to ${formatDate(meta.archive.cutoff_date)} comes from the frozen archive; later dates are live.` : "No archive yet: all figures are live data."}
        </p>
      </div>
      <div className="flex items-center gap-2">
        {error ? <span role="alert" className="text-caption text-danger">{error}</span> : null}
        <button type="button" onClick={() => setOpen(true)} className="h-9 rounded-md border border-border px-3 font-medium hover:bg-surface-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus-ring">Methodology</button>
        <button type="button" disabled={busy} onClick={() => void exportNow()} className="h-9 rounded-md bg-brand-navy px-3 font-semibold text-text-inverse hover:bg-brand-navy-hover disabled:opacity-60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring">{busy ? "Exporting…" : "Export to Excel"}</button>
      </div>
      {open ? <MethodologyModal onClose={() => setOpen(false)} /> : null}
    </footer>
  );
};
