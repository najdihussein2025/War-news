import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { apiClient } from "../../../lib/apiClient";
import "./intelligenceFlow.css";

type RawMessage = {
  id: number;
  khabar: string;
  confidence?: number | null;
  received_at?: string | null;
  status?: string | null;
};

type Incident = {
  id?: string | null;
  raw_message_id?: number | null;
  village?: string | null;
  village_name?: string | null;
  condition?: string | null;
  condition_name?: string | null;
  created_at?: string | null;
  verification_status?: string | null;
};

type AirViolation = {
  id?: number;
  raw_message_id?: number | null;
  village_en?: string | null;
  caza_en?: string | null;
  action_en?: string | null;
};

type StageHealth = { stage_name: string; queue_depth: number; oldest_waiting_seconds: number | null };
type PipelineHealth = {
  stages: StageHealth[];
  cursor_gap: { gap: number; unhealthy: boolean };
  latency: { materialized: { p50_seconds: number | null; sample_size: number } };
  ollama: { status: string };
  cnrs_webhook: { status: string; last_received_at: string | null };
};

const stageLabels: Record<string, string> = {
  relevance_filter: "Relevance filter",
  pre_extraction_dedup: "Duplicate guard",
  tier1_extraction: "AI extraction",
  matching: "Geo matching",
  fast_path: "Fast path",
  tier2_detail_fill: "Detail enrichment",
  embedding: "Embedding",
  materialization: "Materialization",
};

const fallbackStages = Object.keys(stageLabels).map((stage_name) => ({ stage_name, queue_depth: 0, oldest_waiting_seconds: null }));
const age = (seconds: number | null) => seconds == null ? "—" : seconds < 60 ? `${Math.round(seconds)}s` : seconds < 3600 ? `${Math.round(seconds / 60)}m` : `${Math.round(seconds / 3600)}h`;
const time = (value?: string | null) => value ? new Date(value).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "—";
const dependencyLabel = (status?: string) => status === "healthy" ? "ONLINE" : status === "stale" ? "STALE" : status === "waiting" ? "WAITING" : status === "not_configured" ? "NOT CONFIGURED" : "OFFLINE";

const FlowNode = ({ eyebrow, label, tone = "neutral", active = false }: { eyebrow: string; label: string; tone?: string; active?: boolean }) => (
  <div className={`if-node if-${tone} ${active ? "if-active" : ""}`}>
    <span className="if-node-icon" aria-hidden="true">{tone === "ai" ? "✦" : tone === "rule" ? "⌁" : tone === "success" ? "✓" : "◉"}</span>
    <span><small>{eyebrow}</small><strong>{label}</strong></span>
  </div>
);

const Connector = () => <span className="if-connector" aria-hidden="true"><i /></span>;

export const IntelligenceFlowPage = () => {
  const [rawItems, setRawItems] = useState<RawMessage[]>([]);
  const [incident, setIncident] = useState<Incident | null>(null);
  const [air, setAir] = useState<AirViolation | null>(null);
  const [health, setHealth] = useState<PipelineHealth | null>(null);
  const [lastSync, setLastSync] = useState<Date | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [step, setStep] = useState(0);

  const sync = useCallback(async () => {
    try {
      const [rawResponse, incidentResponse, airResponse, healthResponse] = await Promise.all([
        apiClient.get<{ items: RawMessage[] }>("/filtered-news?limit=20&offset=0"),
        apiClient.get<{ items: Incident[] }>("/incidents?limit=20&sort_order=newest"),
        apiClient.get<{ items: AirViolation[] }>("/air-violations?limit=20&offset=0"),
        apiClient.get<PipelineHealth>("/pipeline/health"),
      ]);
      const raws = rawResponse.data.items ?? [];
      const current = raws[0];
      const incidents = incidentResponse.data.items ?? [];
      const airs = airResponse.data.items ?? [];
      setRawItems(raws);
      setIncident(incidents.find((item) => item.raw_message_id === current?.id) ?? incidents[0] ?? null);
      setAir(airs.find((item) => item.raw_message_id === current?.id) ?? airs[0] ?? null);
      setHealth(healthResponse.data);
      setLastSync(new Date());
      setError(null);
    } catch {
      setError("Live pipeline data could not be loaded.");
    }
  }, []);

  useEffect(() => {
    void sync();
    const poll = window.setInterval(() => void sync(), 3000);
    return () => window.clearInterval(poll);
  }, [sync]);

  useEffect(() => {
    const animation = window.setInterval(() => setStep((value) => (value + 1) % 8), 2200);
    return () => window.clearInterval(animation);
  }, []);

  const raw = rawItems[0];
  const stages = health?.stages ?? fallbackStages;
  const totalQueued = stages.reduce((sum, stage) => sum + stage.queue_depth, 0);
  const location = incident?.village ?? incident?.village_name ?? air?.village_en ?? air?.caza_en ?? "Location pending";
  const condition = incident?.condition ?? incident?.condition_name ?? air?.action_en ?? "Processing";
  const confidence = Math.round((raw?.confidence ?? 0) * 100);
  const activeQueue = useMemo(() => new Map(stages.map((stage) => [stage.stage_name, stage.queue_depth])), [stages]);

  return (
    <section className="intelligence-flow">
      <header className="if-header">
        <div><Link className="if-back" to="/superadmin/dashboard" aria-label="Back to dashboard">←</Link><span className="if-logo">⌁</span><strong>War News <em>/ Intelligence Flow</em></strong><small>LIVE PROCESSING ARCHITECTURE</small></div>
        <div className="if-live"><b>⌁ LIVE API</b><span>Last sync {lastSync?.toLocaleTimeString() ?? "—"}</span></div>
      </header>

      <div className="if-hero">
        <div><b>SYSTEM OBSERVABILITY</b><h2>From signal to <span>structured intelligence.</span></h2><p>Follow one report as it is collected, understood, geolocated and delivered to analysts.</p></div>
        <div className="if-metrics"><span>RAW MESSAGE<strong>#{raw?.id ?? "—"}</strong></span><span>CONFIDENCE<strong>{confidence || "—"}%</strong></span><span>LATENCY<strong>{age(health?.latency.materialized.p50_seconds ?? null)}</strong></span></div>
      </div>

      {error ? <div className="if-error" role="alert">{error} <button type="button" onClick={() => void sync()}>Retry</button></div> : null}

      <section className="if-pulse">
        <div className="if-pulse-head"><div><i /><small>LIVE PIPELINE STATE</small><strong>{totalQueued} items currently queued</strong></div><p>Cursor gap <b className={health?.cursor_gap.unhealthy ? "if-warn" : ""}>{health?.cursor_gap.gap ?? "—"}</b> P50 latency <b>{age(health?.latency.materialized.p50_seconds ?? null)}</b> Sample <b>{health?.latency.materialized.sample_size ?? "—"}</b></p></div>
        <div className="if-dependencies" aria-label="Live dependency status">
          <span><small>OLLAMA LLM</small><b className={health?.ollama.status === "healthy" ? "if-ok" : "if-bad"}>{dependencyLabel(health?.ollama.status)}</b></span>
          <span><small>CNRS WEBHOOK</small><b className={health?.cnrs_webhook.status === "healthy" ? "if-ok" : health?.cnrs_webhook.status === "stale" ? "if-warn" : "if-bad"}>{dependencyLabel(health?.cnrs_webhook.status)}</b><em>{health?.cnrs_webhook.last_received_at ? `last received ${time(health.cnrs_webhook.last_received_at)}` : "no receipt recorded"}</em></span>
        </div>
        <div className="if-stages">{stages.map((stage, index) => <div className={stage.queue_depth ? "if-working" : ""} key={stage.stage_name}><span>{String(index + 1).padStart(2, "0")}<i /></span><strong>{stageLabels[stage.stage_name] ?? stage.stage_name.replaceAll("_", " ")}</strong><small><b>{stage.queue_depth}</b> queued<br />oldest {age(stage.oldest_waiting_seconds)}</small></div>)}</div>
      </section>

      <div className="if-workspace">
        <aside className="if-recent"><header><small>RECENT LIVE RECORDS</small><span>Newest first</span></header>{rawItems.slice(0, 5).map((item, index) => <article className={index === 0 ? "if-selected" : ""} key={item.id}><i /><strong>#{item.id}</strong><p dir="auto">{item.khabar}</p><b>{item.status?.replaceAll("_", " ") ?? "processed"}</b><time>{time(item.received_at)}</time></article>)}</aside>
        <section className="if-canvas">
          <div className="if-lanes"><span>01 · INGESTION</span><span>02 · INTELLIGENCE</span><span>03 · OUTPUT</span></div>
          <div className="if-payload"><i /><small>ACTIVE PAYLOAD · #{raw?.id ?? "—"}</small><p dir="auto">{raw?.khabar ?? "Waiting for the next processed message…"}</p><b>MATERIALIZED</b></div>
          <div className="if-row if-ingestion"><FlowNode eyebrow="MULTI-SOURCE INPUT" label="Incoming signals" active={step === 0} /><Connector /><FlowNode eyebrow="INGEST" label="Collector" active={step === 1} /><Connector /><FlowNode eyebrow="PERSIST" label="raw_messages" tone="success" active={step === 2} /></div>
          <div className="if-split">• ROUTE TO SPECIALIZED INTELLIGENCE •</div>
          <div className="if-branch if-incident"><header><span>✦</span><div><small>PIPELINE A</small><h3>Incident intelligence</h3></div><b>{incident?.verification_status?.replaceAll("_", " ") ?? "LIVE"}</b></header><div className="if-row"><FlowNode eyebrow="LLM GATE" label="Relevance filter" tone="ai" active={step === 3 || Boolean(activeQueue.get("relevance_filter"))} /><Connector /><FlowNode eyebrow="LLM" label="Classification" tone="ai" active={step === 4} /><Connector /><FlowNode eyebrow="STRUCTURE" label="Extraction" tone="ai" active={step === 5} /><Connector /><FlowNode eyebrow="STORE" label="incidents" tone="success" active={step === 6} /><Connector /><FlowNode eyebrow="OPERATIONAL UI" label="Workspace" tone="success" active={step === 7} /></div></div>
          <div className="if-branch if-air"><header><span>⌁</span><div><small>PIPELINE B</small><h3>Air violation intelligence</h3></div><b>RULE-GUIDED</b></header><div className="if-row"><FlowNode eyebrow="SOURCE + KEYWORDS" label="Air rules" tone="rule" active={step === 3} /><Connector /><FlowNode eyebrow="RULE ENGINE" label="Condition" tone="rule" active={step === 4} /><Connector /><FlowNode eyebrow="GEOGRAPHIC" label="Village match" active={step === 5} /><Connector /><FlowNode eyebrow="STORE" label="air_violations" tone="success" active={step === 6} /><Connector /><FlowNode eyebrow="OPERATIONAL UI" label="Map" tone="success" active={step === 7} /></div></div>
          <div className="if-result"><small>LATEST STRUCTURED RESULT</small><strong>{condition}</strong><span>{location}</span></div>
        </section>
      </div>
    </section>
  );
};
