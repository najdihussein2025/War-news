import { useContext, useEffect, useState, type FormEvent } from "react";
import { ShellContext } from "../../../app/AppShell";
import { StatusBadge } from "../../../components/StatusBadge";
import { Button, Card, Dialog, EmptyState, FormField, Input, Label } from "../../../components/ui";
import { formatRelativeTime } from "../../../lib/formatters";
import { useSources } from "../../../mocks/useSources";
import type { MockSource, SourceType } from "../../../mocks/mockSources";

const sourceTypes: SourceType[] = ["Telegram", "CNRS API", "CNRS Local LLM"];
const healthVariant = (health: MockSource["health"]) =>
  health === "healthy" ? "success" : health === "error" ? "danger" : "warning";

export const SourcesPage = () => {
  const { data, isLoading, isError } = useSources();
  const shell = useContext(ShellContext);
  const [sources, setSources] = useState(data);
  const [isDialogOpen, setIsDialogOpen] = useState(false);
  const [form, setForm] = useState({ type: "Telegram" as SourceType, name: "", config: "" });

  useEffect(() => {
    shell?.setPageAction(<Button type="button" className="w-full sm:w-auto" onClick={() => setIsDialogOpen(true)}>Add Source</Button>);
    return () => shell?.setPageAction(null);
  }, [shell]);

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSources((current) => [
      {
        id: `src_${Date.now()}`,
        type: form.type,
        name: form.name,
        last_cursor: "new:pending",
        last_run_at: null,
        is_active: true,
        health: "paused",
        messages_fetched_last_run: 0,
      },
      ...current,
    ]);
    setIsDialogOpen(false);
    setForm({ type: "Telegram", name: "", config: "" });
    shell?.showToast(`${form.name} was added.`);
  };

  if (isLoading) {
    return <div className="grid gap-5 md:grid-cols-2">{Array.from({ length: 4 }).map((_, index) => <Card className="h-56 p-5" key={index}><div className="h-full rounded-md bg-surface-muted" /></Card>)}</div>;
  }

  if (isError) {
    return <Card><EmptyState title="Could not load sources" description="The mocked error state is ready for a future API failure." /></Card>;
  }

  if (sources.length === 0) {
    return <Card><EmptyState title="No sources yet" description="Add a source to begin mocked ingestion." /></Card>;
  }

  return (
    <>
      <div className="grid gap-5 md:grid-cols-2">
        {sources.map((source) => (
          <Card className="p-5" key={source.id}>
            <div className="flex items-start justify-between gap-4">
              <div>
                <StatusBadge label={source.type} variant="accent" />
                <h2 className="mt-3 text-h4 font-semibold text-text-primary">{source.name}</h2>
                <p className="mt-2 text-small text-text-muted">Cursor {source.last_cursor}</p>
              </div>
              <StatusBadge label={source.health} variant={healthVariant(source.health)} />
            </div>
            <div className="mt-5 grid grid-cols-2 gap-3 border-y border-border py-4">
              <div>
                <p className="text-caption font-semibold uppercase text-text-muted">Last run</p>
                <p className="mt-1 text-small text-text-primary">{formatRelativeTime(source.last_run_at)}</p>
              </div>
              <div>
                <p className="text-caption font-semibold uppercase text-text-muted">Fetched</p>
                <p className="mt-1 text-small text-text-primary">{source.messages_fetched_last_run} messages</p>
              </div>
            </div>
            {source.error_reason ? <p className="mt-4 rounded-md border border-border bg-surface px-3 py-2 text-small text-danger">{source.error_reason}</p> : null}
            <div className="mt-5 flex flex-wrap gap-3">
              <Button type="button" variant={source.is_active ? "secondary" : "primary"} onClick={() => setSources((current) => current.map((item) => item.id === source.id ? { ...item, is_active: !item.is_active, health: item.is_active ? "paused" : "healthy" } : item))}>
                {source.is_active ? "Pause" : "Resume"}
              </Button>
              <Button type="button" variant="ghost" onClick={() => shell?.showToast("Edit source is mocked for now.")}>Edit</Button>
            </div>
          </Card>
        ))}
      </div>

      {isDialogOpen ? (
        <Dialog title="Add Source" onClose={() => setIsDialogOpen(false)}>
          <form className="space-y-4" onSubmit={submit}>
            <div className="space-y-2">
              <Label htmlFor="source-type">Type</Label>
              <select id="source-type" className="h-11 w-full rounded-md border border-input-border bg-input-bg px-3 text-body text-text-primary" value={form.type} onChange={(event) => setForm({ ...form, type: event.target.value as SourceType })}>
                {sourceTypes.map((type) => <option key={type} value={type}>{type}</option>)}
              </select>
            </div>
            <FormField id="source-name" label="Name">
              <Input id="source-name" value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} required />
            </FormField>
            <FormField id="source-config" label="Config placeholder">
              <Input id="source-config" value={form.config} onChange={(event) => setForm({ ...form, config: event.target.value })} placeholder="Mock config JSON or notes" />
            </FormField>
            <div className="flex flex-col-reverse gap-3 pt-2 sm:flex-row sm:justify-end">
              <Button type="button" variant="secondary" onClick={() => setIsDialogOpen(false)}>Cancel</Button>
              <Button type="submit">Add source</Button>
            </div>
          </form>
        </Dialog>
      ) : null}
    </>
  );
};
