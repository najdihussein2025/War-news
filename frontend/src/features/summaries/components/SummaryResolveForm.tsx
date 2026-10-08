import { isAxiosError } from "axios";
import { useMemo, useState } from "react";
import { StatusBadge } from "../../../components/StatusBadge";
import { Button, Label, Select, type SelectOption } from "../../../components/ui";
import { useConditionsQuery, useVillagesQuery } from "../../news/hooks";
import { useDismissSummaryTask, useResolveSummaryTask } from "../hooks";
import { reasonLabel } from "../logic";
import type { ReviewAction, SummaryDetail, SummaryItem, SummaryReasonType } from "../types";

type Draft = {
  mode: "" | "resolve" | "dismiss" | "create_incident";
  villageId: string;
  conditionIds: string[];
  save: boolean;
};

const emptyDraft: Draft = { mode: "", villageId: "", conditionIds: [""], save: false };

/** Turn one item's draft into the API action, or null while it is incomplete. */
export const draftToAction = (item: SummaryItem, type: SummaryReasonType, draft: Draft): ReviewAction | null => {
  if (draft.mode === "dismiss") return { item_id: item.id, action: "dismiss" };
  if (type === "casualty_in_summary") {
    return draft.mode === "create_incident" ? { item_id: item.id, action: "create_incident" } : null;
  }
  const conditionIds = draft.conditionIds.filter(Boolean).map(Number);
  if (type === "unknown_header") {
    return draft.mode === "resolve" && conditionIds.length
      ? { item_id: item.id, action: "resolve", condition_ids: conditionIds, save_mapping: draft.save }
      : null;
  }
  if (draft.mode !== "resolve" || !draft.villageId) return null;
  if (!item.condition && !conditionIds.length) return null;
  return {
    item_id: item.id,
    action: "resolve",
    village_id: Number(draft.villageId),
    save_alias: draft.save,
    ...(conditionIds.length ? { condition_ids: conditionIds } : {}),
  };
};

type Props = { summary: SummaryDetail };

export const SummaryResolveForm = ({ summary }: Props) => {
  const task = summary.review_task;
  const { data: villages = [], isLoading: villagesLoading } = useVillagesQuery();
  const { data: conditions = [], isLoading: conditionsLoading } = useConditionsQuery();
  const resolve = useResolveSummaryTask();
  const dismiss = useDismissSummaryTask();
  const [drafts, setDrafts] = useState<Record<number, Draft>>({});
  const [error, setError] = useState("");

  const villageOptions = useMemo<SelectOption[]>(() => villages.map((v) => ({ value: String(v.id), label: v.label })), [villages]);
  const conditionOptions = useMemo<SelectOption[]>(
    () => conditions.map((c) => ({ value: String(c.id), label: `${c.action_en} - ${c.action_ar}` })),
    [conditions],
  );

  if (!task || task.status !== "open") return null;
  const openReasons = task.reasons.filter((reason) => !reason.handled);
  if (!openReasons.length) return null;
  const itemById = new Map(summary.items.map((item) => [item.id, item]));
  const draftOf = (id: number) => drafts[id] ?? emptyDraft;
  const patch = (id: number, change: Partial<Draft>) => setDrafts((all) => ({ ...all, [id]: { ...draftOf(id), ...change } }));

  const actions = openReasons.flatMap((reason) =>
    reason.item_ids.flatMap((id) => {
      const item = itemById.get(id);
      const action = item ? draftToAction(item, reason.type, draftOf(id)) : null;
      return action ? [action] : [];
    }),
  );
  const busy = resolve.isPending || dismiss.isPending;
  const messageOf = (err: unknown, fallback: string) =>
    isAxiosError(err) && typeof err.response?.data?.detail === "string" ? err.response.data.detail : fallback;

  return (
    <section className="space-y-4 rounded-lg border border-warning/40 bg-surface-raised p-4" aria-label="Resolve review task">
      <div>
        <h2 className="text-h4 font-semibold text-text-primary">Review needed</h2>
        <p className="text-small text-text-muted">Decide each item below. Nothing is created from a summary without a village and an action.</p>
      </div>
      {openReasons.map((reason) =>
        reason.item_ids.map((id) => {
          const item = itemById.get(id);
          if (!item) return null;
          const draft = draftOf(id);
          return (
            <div key={id} className="space-y-3 rounded-md border border-border bg-surface p-3">
              <div className="flex flex-wrap items-center gap-2">
                <StatusBadge label={reasonLabel(reason.type)} variant="warning" />
                {reason.origin === "llm_crosscheck" ? <StatusBadge label="LLM cross-check" variant="accent" /> : null}
                <span className="text-small text-text-primary" dir="auto">{item.evidence_span}</span>
              </div>

              {reason.type === "casualty_in_summary" ? (
                <fieldset className="space-y-2 text-small">
                  <legend className="sr-only">Casualty wording decision</legend>
                  <label className="flex items-center gap-2">
                    <input type="radio" name={`mode-${id}`} checked={draft.mode === "create_incident"} onChange={() => patch(id, { mode: "create_incident" })} />
                    Create the incident (summaries never write casualty numbers)
                  </label>
                </fieldset>
              ) : (
                <div className="grid gap-3 sm:grid-cols-2">
                  {reason.type === "unresolved_location" ? (
                    <div className="space-y-2">
                      <Label htmlFor={`village-${id}`}>Village</Label>
                      <Select
                        id={`village-${id}`}
                        value={draft.villageId}
                        options={villageOptions}
                        searchable
                        searchPlaceholder="Search village in English or Arabic"
                        placeholder={villagesLoading && !villageOptions.length ? "Loading villages..." : "Select village"}
                        className="w-full min-w-0"
                        onChange={(value) => patch(id, { villageId: value, mode: value ? "resolve" : "" })}
                      />
                    </div>
                  ) : null}
                  {reason.type === "unknown_header" || !item.condition ? (
                    <div className="space-y-2">
                      <Label htmlFor={`condition-${id}-0`}>{reason.type === "unknown_header" ? "Header means" : "Section action"}</Label>
                      {draft.conditionIds.map((value, index) => (
                        <Select
                          key={index}
                          id={`condition-${id}-${index}`}
                          value={value}
                          options={conditionOptions}
                          searchable
                          searchPlaceholder="Search condition in English or Arabic"
                          placeholder={conditionsLoading && !conditionOptions.length ? "Loading conditions..." : "Select condition"}
                          className="w-full min-w-0"
                          onChange={(next) => {
                            const ids = draft.conditionIds.map((existing, i) => (i === index ? next : existing));
                            patch(id, { conditionIds: ids, ...(reason.type === "unknown_header" ? { mode: ids.some(Boolean) ? "resolve" : "" } : {}) });
                          }}
                        />
                      ))}
                      <Button type="button" variant="ghost" className="h-8 px-2" onClick={() => patch(id, { conditionIds: [...draft.conditionIds, ""] })}>
                        + Another action (compound header)
                      </Button>
                    </div>
                  ) : null}
                </div>
              )}

              <div className="flex flex-wrap items-center gap-4 text-small">
                {reason.type !== "casualty_in_summary" ? (
                  <label className="flex items-center gap-2">
                    <input type="checkbox" checked={draft.save} onChange={(event) => patch(id, { save: event.target.checked })} />
                    {reason.type === "unresolved_location" ? "Save this spelling as an alias for future summaries" : "Save this header for future summaries"}
                  </label>
                ) : null}
                <label className="flex items-center gap-2">
                  <input type="checkbox" checked={draft.mode === "dismiss"} onChange={(event) => patch(id, { mode: event.target.checked ? "dismiss" : "" })} />
                  Dismiss this item
                </label>
              </div>
            </div>
          );
        }),
      )}
      {error ? <p className="text-small text-danger" role="alert">{error}</p> : null}
      <div className="flex flex-wrap justify-end gap-2 border-t border-border pt-3">
        <Button
          type="button"
          variant="secondary"
          disabled={busy}
          onClick={async () => {
            setError("");
            try { await dismiss.mutateAsync(summary.id); } catch (err) { setError(messageOf(err, "Could not dismiss the review task.")); }
          }}
        >
          Dismiss whole task
        </Button>
        <Button
          type="button"
          disabled={!actions.length || busy}
          isLoading={resolve.isPending}
          loadingText="Saving"
          onClick={async () => {
            setError("");
            try {
              await resolve.mutateAsync({ id: summary.id, actions });
              setDrafts({});
            } catch (err) {
              setError(messageOf(err, "Could not save the decisions."));
            }
          }}
        >
          Apply {actions.length || ""} decision{actions.length === 1 ? "" : "s"}
        </Button>
      </div>
    </section>
  );
};
