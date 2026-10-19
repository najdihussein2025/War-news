import { useContext, useEffect, useMemo, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { ShellContext } from "../../../app/AppShell";
import { Button, Dialog, Input } from "../../../components/ui";
import { formatDate, formatDateTime } from "../../../lib/formatters";
import { roleBaseFromPath } from "../../../lib/rolePath";
import { assignedTotal, buildResolutionEntries, casualtyFields, dismissReasonError, isWholeNonNegative, mapApiError, mapFieldErrors, type AllocationValues } from "../logic";
import { useCasualtyFlag, useDismissCasualtyFlag, useResolveCasualtyFlag } from "../hooks";
import type { CasualtyField, CasualtyFlagDetail } from "../types";

const fieldLabels: Record<CasualtyField, string> = { male_d: "ذكور", female_d: "إناث", children_d: "أطفال", total_deaths: "الإجمالي", male_i: "ذكور", female_i: "إناث", children_i: "أطفال", total_injuries: "الإجمالي" };
const groups: Array<{ title: string; fields: CasualtyField[] }> = [
  { title: "وفيات", fields: ["male_d", "female_d", "children_d", "total_deaths"] },
  { title: "إصابات", fields: ["male_i", "female_i", "children_i", "total_injuries"] },
];

const Evidence = ({ text, evidence }: { text: string; evidence: string | null }) => {
  if (!evidence || !text.includes(evidence)) return <>{text}</>;
  const [before, ...after] = text.split(evidence);
  return <>{before}<mark className="rounded bg-warning/20 px-1 text-inherit">{evidence}</mark>{after.join(evidence)}</>;
};

const ReadOnlyResolution = ({ flag }: { flag: CasualtyFlagDetail }) => (
  <section className="rounded-lg border border-border bg-surface-muted p-4">
    <h3 className="font-semibold text-text-primary">This check is {flag.status.replace("_", " ")}</h3>
    {flag.resolved_at ? <p className="mt-1 text-small text-text-muted">By {flag.resolved_by ?? "an administrator"} on {formatDateTime(flag.resolved_at)}</p> : null}
    {flag.resolution?.entries?.length ? <ul className="mt-3 space-y-1 text-small">{flag.resolution.entries.map((entry) => <li key={entry.incident_id}>{entry.incident_id}: {entry.total_deaths === undefined ? "" : `${entry.total_deaths} deaths`} {entry.total_injuries === undefined ? "" : `${entry.total_injuries} injuries`}</li>)}</ul> : null}
    {flag.resolution?.confirmed_unknown ? <p className="mt-2 text-small">Confirmed unknown</p> : null}
    {flag.resolution?.note ? <p className="mt-2 text-small">Note: {flag.resolution.note}</p> : null}
    {flag.resolution?.dismiss_reason ? <p className="mt-2 text-small">Dismissed because: {flag.resolution.dismiss_reason}</p> : null}
    {flag.auto_clear_reason ? <p className="mt-2 text-small">Auto-cleared because: {flag.auto_clear_reason}</p> : null}
  </section>
);

export const CasualtyCheckPanel = ({ id: initialId, onClose, onComplete, inline = false }: { id: string; onClose: () => void; onComplete: () => void; inline?: boolean }) => {
  const location = useLocation();
  const shell = useContext(ShellContext);
  // After a partial aggregate save the panel moves on to an open sibling flag.
  const [id, setId] = useState(initialId);
  useEffect(() => setId(initialId), [initialId]);
  const query = useCasualtyFlag(id);
  const resolve = useResolveCasualtyFlag();
  const dismiss = useDismissCasualtyFlag();
  const [values, setValues] = useState<AllocationValues>({});
  const [override, setOverride] = useState(false);
  const [overrideReason, setOverrideReason] = useState("");
  const [note, setNote] = useState("");
  const [showDismiss, setShowDismiss] = useState(false);
  const [dismissReason, setDismissReason] = useState("");
  const [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [saveResult, setSaveResult] = useState("");

  useEffect(() => { setValues({}); setOverride(false); setOverrideReason(""); setNote(""); setError(""); setFieldErrors({}); }, [id]);
  useEffect(() => setSaveResult(""), [initialId]);
  const flag = query.data;
  useEffect(() => {
    if (!flag || Object.keys(values).length) return;
    setValues(Object.fromEntries(flag.incidents.map((incident) => [incident.id, Object.fromEntries(casualtyFields.map((field) => [field, incident[field] == null ? "" : String(incident[field])]))])));
  }, [flag, values]);
  const totals = flag?.detail.bulletin_totals ?? {};
  const remaining = useMemo(() => ({
    deaths: typeof totals.deaths === "number" ? totals.deaths - assignedTotal(values, "total_deaths") : null,
    injuries: typeof totals.injuries === "number" ? totals.injuries - assignedTotal(values, "total_injuries") : null,
  }), [totals.deaths, totals.injuries, values]);
  const mismatch = flag?.reason_code === "aggregate_no_breakdown" && Object.values(remaining).some((value) => value !== null && value !== 0);
  const setValue = (incidentId: string, kind: CasualtyField, value: string) => {
    if (!isWholeNonNegative(value)) return;
    setValues((current) => ({ ...current, [incidentId]: { ...current[incidentId], [kind]: value } }));
  };
  const entries = buildResolutionEntries(values);
  const localInvalid = flag?.incidents.some((incident) => groups.some((group) => {
    const [male, female, children, total] = group.fields;
    const row = values[incident.id] ?? {};
    const sum = [male, female, children].reduce((value, field) => value + Number(row[field] || 0), 0);
    return row[total] !== "" && Number(row[total]) < sum;
  }));
  const canSubmit = Boolean(flag) && !resolve.isPending && entries.length === flag?.incidents.length && !localInvalid && (!mismatch || (override && overrideReason.trim().length >= 3));

  const submit = async () => {
    if (!flag || !canSubmit) return;
    setError("");
    setFieldErrors({});
    try {
      const response = await resolve.mutateAsync({ id, entries, note: note.trim() || undefined, override, override_reason: override ? overrideReason.trim() : undefined });
      const resolvedNames = response.results.filter((item) => item.resolved).map((item) => flag.incidents.find((incident) => incident.id === item.incident_id)?.village_name ?? item.incident_id);
      const openNames = response.results.filter((item) => item.still_open).map((item) => flag.incidents.find((incident) => incident.id === item.incident_id)?.village_name ?? item.incident_id);
      setSaveResult([resolvedNames.length ? `Resolved: ${resolvedNames.join(", ")}.` : "", openNames.length ? `Still open: ${openNames.join(", ")}.` : ""].filter(Boolean).join(" "));
      shell?.showToast("Casualty check saved.");
      onComplete();
    } catch (requestError) { const mapped = mapFieldErrors(requestError); setFieldErrors(mapped.fields); const status = (requestError as { response?: { status?: number } }).response?.status; setError(status === 409 ? "قام مسؤول آخر بحل هذه المجموعة. أعد تحميل البيانات وحاول مجددًا." : mapped.summary.join(" ") || mapApiError(requestError)); }
  };

  const content = <>
    {query.isLoading ? <div className="space-y-3" aria-label="Loading casualty check"><div className="h-24 animate-pulse rounded bg-surface-muted" /><div className="h-48 animate-pulse rounded bg-surface-muted" /></div> : query.isError || !flag ? <div role="alert"><p className="text-danger">Could not load this casualty check.</p><Button className="mt-4" variant="secondary" onClick={() => query.refetch()}>Try again</Button></div> : <div className="space-y-6">
      <section><div className="flex flex-wrap justify-between gap-2 text-small text-text-muted"><span>{flag.source_name ?? "Unknown source"}</span><span>{flag.event_date ? formatDate(flag.event_date) : "Unknown date"}</span></div><p dir="rtl" lang="ar" className="mt-3 rounded-lg border border-border bg-surface p-4 text-right text-body leading-8 text-text-primary"><Evidence text={flag.message_text ?? flag.evidence_sentence ?? "No original message available."} evidence={flag.evidence_sentence} /></p>{flag.message_snapshot_used ? <p className="mt-2 text-small text-text-muted">Original raw message is unavailable; showing the saved flag snapshot.</p> : null}<Link className="mt-3 inline-block text-small font-semibold text-accent" to={`${roleBaseFromPath(location.pathname)}/incidents/${flag.incident_id}`}>Open incident</Link></section>
      <section><h3 className="font-semibold text-text-primary">What we know</h3><div className="mt-3 space-y-2">{flag.incidents.map((incident) => <div key={incident.id} className="grid grid-cols-3 gap-2 rounded border border-border p-3 text-small"><span>{incident.village_name ?? "Unknown location"}</span><span>Deaths: {incident.total_deaths ?? "Unknown"}</span><span>Injuries: {incident.total_injuries ?? "Unknown"}</span></div>)}</div></section>
      {flag.status !== "open" ? <ReadOnlyResolution flag={flag} /> : <form onSubmit={(event) => { event.preventDefault(); void submit(); }} className="space-y-5">
        <div className="space-y-4" dir="rtl">{flag.incidents.map((incident, rowIndex) => <fieldset key={incident.id} className="rounded-lg border border-border p-4"><legend className="px-1 font-semibold">{incident.village_name ?? "موقع غير معروف"}</legend>{groups.map((group) => <section key={group.title} className="mt-3"><h4 className="text-small font-semibold">{group.title}</h4><div className="mt-2 grid grid-cols-2 gap-3 sm:grid-cols-4">{group.fields.map((field, fieldIndex) => <label key={field} className="text-small font-semibold">{fieldLabels[field]}<Input autoFocus={rowIndex === 0 && fieldIndex === 0} className="mt-1" type="number" inputMode="numeric" min="0" step="1" value={values[incident.id]?.[field] ?? ""} onChange={(event) => setValue(incident.id, field, event.target.value)} />{fieldErrors[`${incident.id}.${field}`] ? <span className="mt-1 block text-danger">{fieldErrors[`${incident.id}.${field}`]}</span> : null}</label>)}</div></section>)}</fieldset>)}{(["deaths", "injuries"] as const).map((kind) => totals[kind] == null ? null : <p key={kind} className={`text-small font-semibold ${remaining[kind] === 0 ? "text-success" : "text-danger"}`}>المتبقي لتوزيعه — {kind === "deaths" ? "إجمالي الوفيات" : "إجمالي الإصابات"}: {remaining[kind]}</p>)}{localInvalid ? <p className="text-small font-semibold text-danger" role="alert">يجب ألا يكون الإجمالي أقل من مجموع الذكور والإناث والأطفال.</p> : null}{mismatch ? <p className="text-small font-semibold text-danger" role="alert">مجموع الأعداد الموزّعة لا يساوي إجمالي النشرة. صحّح الأعداد أو فعّل التجاوز مع ذكر السبب.</p> : null}{flag.reason_code === "aggregate_no_breakdown" ? <><label className="flex items-center gap-2 text-small font-semibold"><input type="checkbox" checked={override} onChange={(event) => setOverride(event.target.checked)} />السماح بتجاوز إجمالي النشرة</label>{override ? <label className="block text-small font-semibold">سبب التجاوز (مطلوب)<textarea className="mt-1 min-h-20 w-full rounded-md border border-input-border p-3 font-normal" value={overrideReason} onChange={(event) => setOverrideReason(event.target.value)} /></label> : null}</> : null}</div>
        <label className="block text-small font-semibold">Optional note<textarea className="mt-1 min-h-24 w-full rounded-md border border-input-border p-3 font-normal" value={note} onChange={(event) => setNote(event.target.value)} /></label>
        {error ? <p className="text-small font-semibold text-danger" role="alert">{error}</p> : null}
        {saveResult ? <p className="text-small font-semibold text-success" role="status">{saveResult}</p> : null}
        <div className="flex flex-wrap justify-between gap-3 border-t border-border pt-4"><Button type="button" variant="destructive" onClick={() => setShowDismiss(true)}>Dismiss</Button><Button type="submit" disabled={!canSubmit} isLoading={resolve.isPending} loadingText="Saving…">Save entered values</Button></div>
      </form>}
      {showDismiss ? <div className="rounded-lg border border-danger/30 bg-surface p-4"><label className="text-small font-semibold">Dismiss reason<Input autoFocus className="mt-1" value={dismissReason} onChange={(event) => setDismissReason(event.target.value)} /></label>{dismiss.isError ? <p className="mt-2 text-small text-danger">{mapApiError(dismiss.error)}</p> : null}<div className="mt-3 flex justify-end gap-2"><Button variant="secondary" onClick={() => setShowDismiss(false)}>Cancel</Button><Button variant="destructive" disabled={Boolean(dismissReasonError(dismissReason))} isLoading={dismiss.isPending} onClick={async () => { const reasonError = dismissReasonError(dismissReason); if (reasonError) { setError(reasonError); return; } await dismiss.mutateAsync({ id, reason: dismissReason.trim() }); shell?.showToast("Casualty check dismissed."); onComplete(); }}>Dismiss</Button></div></div> : null}
    </div>}
  </>;
  return inline ? (
    <section className="rounded-lg border border-warning/40 bg-warning/5 p-5 sm:p-6">
      <p className="mb-4 text-caption font-semibold uppercase tracking-wide text-warning">Casualty check</p>
      {content}
    </section>
  ) : (
    <Dialog title="Casualty check" eyebrow={flag ? (flag.reason_code === "count_missing" ? "Missing number" : "Aggregate toll") : "Loading"} onClose={onClose} size="panel">{content}</Dialog>
  );
};
