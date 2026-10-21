import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { getBeirutDate } from "../../../lib/localDate";
import { formatDate } from "../../../lib/formatters";
import { levelDisabledReason, nearestSupportedLevel, excludedAirTypes, airTypeLabel } from "../airRules";
import { AirSection } from "../components/AirSection";
import { AreaPanel } from "../components/AreaPanel";
import { ErrorBlock, SectionCard, Skeleton, errorMessage, useInView } from "../components/common";
import { DrilldownDrawer } from "../components/DrilldownDrawer";
import { FilterBar, metricLabel } from "../components/FilterBar";
import { FooterStrip } from "../components/FooterStrip";
import { HeatMap } from "../components/HeatMap";
import { KpiCards } from "../components/KpiCards";
import { MatrixTable } from "../components/MatrixTable";
import { PeaksCards } from "../components/PeaksCards";
import { PlayControls, type Playback } from "../components/PlayControls";
import { RankingsPanel } from "../components/RankingsPanel";
import { TimelineChart } from "../components/TimelineChart";
import { quantileBreaks } from "../colors";
import { defaultFilters, parseFilters, resolveRange, serializeFilters, toApiParams } from "../filters";
import { useDebounced, useGeo, useKpis, useMapData, useMatrix, useMeta, usePeaks, usePrefetchMap, useTimeline } from "../hooks";
import { playbackFrames } from "../mappers";
import type { AnalyticsFilters, Grain, Level, MapResponse } from "../types";

const IDLE: Playback = { active: false, playing: false, preparing: false, progress: 0, index: 0, labels: [] };

export const AnalyticsPage = () => {
  const today = useMemo(() => getBeirutDate(), []);
  const [search, setSearch] = useSearchParams();
  const meta = useMeta();
  const geo = useGeo();
  const ctx = useMemo(
    () => ({ today, dataFirst: meta.data?.incident_data.first_date ?? null, dataLast: meta.data?.incident_data.last_date ?? null }),
    [today, meta.data],
  );
  const filters = useMemo(() => parseFilters(search, ctx), [search, ctx]);
  const queryFilters = useDebounced(filters, 250);
  const [grainChoice, setGrainChoice] = useState<Grain | null>(null);
  const [drill, setDrill] = useState<{ title: string } | null>(null);

  const update = useCallback((patch: Partial<AnalyticsFilters>) => {
    setSearch(serializeFilters({ ...filters, ...patch }, today));
  }, [filters, setSearch, today]);

  const reset = () => setSearch(serializeFilters(defaultFilters(today), today));

  // Keep the level valid for the chosen air type.
  useEffect(() => {
    if (filters.metric === "breaches" && levelDisabledReason(filters.level, filters.airType, true)) {
      update({ level: nearestSupportedLevel(filters.level, filters.airType) });
    }
  }, [filters.metric, filters.level, filters.airType, update]);

  const familyNames = useMemo(
    () => Object.fromEntries((meta.data?.families ?? []).map((f) => [f.code, f.name_en])),
    [meta.data],
  );

  // ---- map data (never filtered to the selected area, so the whole map stays visible)
  const mapParams = toApiParams(queryFilters, { areaCode: null });
  const mapQuery = useMapData(mapParams);
  const prefetch = usePrefetchMap();
  const [playback, setPlayback] = useState<Playback>(IDLE);
  const framesRef = useRef<MapResponse[]>([]);
  const frameBreaksRef = useRef<number[]>([]);

  const startPlayback = async () => {
    const frames = playbackFrames(queryFilters.dateFrom, queryFilters.dateTo);
    const labels = frames.map((f) => (f.from === f.to ? formatDate(f.from) : `${formatDate(f.from)} – ${formatDate(f.to)}`));
    setPlayback({ active: true, playing: false, preparing: true, progress: 0, index: 0, labels });
    const results: MapResponse[] = new Array(frames.length);
    let done = 0;
    const queue = frames.map((f, i) => ({ f, i }));
    const worker = async () => {
      for (let job = queue.shift(); job; job = queue.shift()) {
        results[job.i] = await prefetch(toApiParams(queryFilters, { areaCode: null, dateFrom: job.f.from, dateTo: job.f.to }));
        done += 1;
        setPlayback((s) => (s.active ? { ...s, progress: done / frames.length } : s));
      }
    };
    try {
      await Promise.all([worker(), worker(), worker(), worker()]);
    } catch {
      setPlayback(IDLE);
      return;
    }
    framesRef.current = results;
    frameBreaksRef.current = quantileBreaks(results.flatMap((r) => r.values.map((v) => v.value)));
    setPlayback((s) => (s.active ? { ...s, preparing: false, playing: true, index: 0 } : s));
  };
  const stopPlayback = () => setPlayback(IDLE);

  useEffect(() => {
    if (!playback.playing || playback.preparing) return undefined;
    const id = window.setInterval(() => {
      setPlayback((s) => {
        if (s.index >= s.labels.length - 1) return { ...s, playing: false };
        return { ...s, index: s.index + 1 };
      });
    }, 700);
    return () => window.clearInterval(id);
  }, [playback.playing, playback.preparing]);
  // A filter change invalidates the cached frames.
  const filterKey = toApiParams(queryFilters, { areaCode: null }).toString();
  useEffect(() => setPlayback(IDLE), [filterKey]);

  const framing = playback.active && !playback.preparing;
  const shownValues = framing ? framesRef.current[playback.index]?.values ?? [] : mapQuery.data?.values ?? [];
  const breaks = useMemo(
    () => (framing ? frameBreaksRef.current : quantileBreaks((mapQuery.data?.values ?? []).map((v) => v.value))),
    [framing, mapQuery.data],
  );

  const focusArea = useCallback((code: string, level: Level) => {
    update({ areaCode: code, level: level === "village" || level === "caza" || level === "mohafaza" ? level : filters.level });
  }, [update, filters.level]);

  // ---- lower sections
  const kpiParams = toApiParams(queryFilters);
  const kpis = useKpis(kpiParams);
  const [tlRef, tlSeen] = useInView();
  const [rkRef, rkSeen] = useInView();
  const [mxRef, mxSeen] = useInView();
  const [airRef, airSeen] = useInView();
  const grain: Grain = grainChoice ?? ((new Date(queryFilters.dateTo).getTime() - new Date(queryFilters.dateFrom).getTime()) / 86_400_000 > 120 ? "week" : "day");
  const timeline = useTimeline(kpiParams, grain, tlSeen);
  const peaks = usePeaks(kpiParams, tlSeen);
  const matrix = useMatrix(kpiParams, mxSeen);

  const label = metricLabel(filters.metric);
  const mapError = mapQuery.error && !mapQuery.data ? errorMessage(mapQuery.error) : null;
  const excluded = filters.metric === "breaches" && !filters.airType ? excludedAirTypes(filters.level).map(airTypeLabel) : [];

  return (
    <div className="space-y-4 pb-8">
      <FilterBar filters={filters} meta={meta.data} today={today} onChange={update} onReset={reset}
        resolveRange={(range) => resolveRange(range, ctx)} />

      <section aria-label="Heat map">
        <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-h4 font-semibold">{label} by {filters.level}</h2>
          <p className="text-caption text-text-muted">
            {mapQuery.data?.unit_note}
            {excluded.length ? ` Not shown at ${filters.level} level: ${excluded.join(", ")}.` : ""}
          </p>
        </div>
        {mapError ? <ErrorBlock message={mapError} onRetry={() => void mapQuery.refetch()} /> : null}
        <div className="relative h-[560px] min-h-[420px]">
          {geo.data ? (
            <HeatMap
              geo={geo.data}
              level={filters.level}
              values={shownValues}
              breaks={breaks}
              metricLabel={label}
              familyNames={familyNames}
              selectedCode={filters.areaCode}
              onSelect={(code, level) => (code ? focusArea(code, level) : update({ areaCode: null }))}
              frameLabel={framing ? playback.labels[playback.index] : null}
              loading={mapQuery.isFetching && !framing}
              controls={<PlayControls state={playback} setState={setPlayback} onStart={() => void startPlayback()} onStop={stopPlayback} disabled={!geo.data} />}
            />
          ) : geo.error ? (
            <ErrorBlock message={errorMessage(geo.error)} onRetry={() => void geo.refetch()} />
          ) : <Skeleton className="h-full w-full" />}
          {filters.areaCode ? (
            <AreaPanel code={filters.areaCode} filters={queryFilters} onClose={() => update({ areaCode: null })}
              onFocusArea={focusArea} onViewIncidents={() => setDrill({ title: "Incidents in the selected area" })} />
          ) : null}
        </div>
        {mapQuery.data && mapQuery.data.values.length === 0 && !mapError ? (
          <p className="mt-2 text-small text-text-muted" role="status">Nothing recorded for these filters. Try a longer period or turn on pending review.</p>
        ) : null}
      </section>

      <KpiCards data={kpis.data} loading={kpis.isLoading} error={kpis.error} onRetry={() => void kpis.refetch()} />

      <div ref={tlRef} className="grid gap-4 xl:grid-cols-[1fr_380px]">
        <SectionCard id="timeline" title="Timeline" subtitle={`${label} per ${grain}, stacked by ${filters.metric === "breaches" ? "air type" : "action family"}`}
          actions={(
            <div className="flex items-center gap-2">
              <div role="group" aria-label="Time grain" className="flex overflow-hidden rounded-md border border-border">
                {(["day", "week", "month"] as Grain[]).map((g) => (
                  <button key={g} type="button" aria-pressed={grain === g} onClick={() => setGrainChoice(g)}
                    className={`h-8 px-3 text-small capitalize focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-focus-ring ${grain === g ? "bg-brand-navy text-text-inverse" : "hover:bg-surface-muted"}`}>{g}</button>
                ))}
              </div>
              <button type="button" onClick={() => setDrill({ title: "Incidents in this period" })} className="h-8 rounded-md border border-border px-3 text-small hover:bg-surface-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus-ring">View incidents</button>
            </div>
          )}>
          {timeline.error && !timeline.data ? <ErrorBlock message={errorMessage(timeline.error)} onRetry={() => void timeline.refetch()} />
            : timeline.data ? (
              <>
                <TimelineChart data={timeline.data} grain={grain} />
                {timeline.data.coverage.gap_dates.length > 0 ? (
                  <p className="mt-1 text-caption text-text-muted">Shaded days ({timeline.data.coverage.gap_dates.length}) had no ingested messages: missing data, not zero incidents.</p>
                ) : null}
              </>
            ) : <Skeleton className="h-[300px]" />}
        </SectionCard>
        <SectionCard id="peaks" title="Peaks" subtitle="Worst day and week in the period">
          <PeaksCards data={peaks.data} loading={peaks.isLoading} error={peaks.error} onRetry={() => void peaks.refetch()} />
        </SectionCard>
      </div>

      <div className="grid gap-4 xl:grid-cols-[7fr_5fr]">
        <div ref={rkRef}>
          <SectionCard id="rankings" title="Rankings" subtitle="Keyboard-friendly list of the same values as the map">
            {rkSeen ? <RankingsPanel filters={queryFilters} familyNames={familyNames} enabled={rkSeen} onFocusArea={focusArea} /> : <Skeleton className="h-80" />}
          </SectionCard>
        </div>
        <div ref={mxRef}>
          <SectionCard id="matrix" title="Action × caza" subtitle="Click a cell to filter the page to that caza and action">
            <MatrixTable data={matrix.data} loading={matrix.isLoading} error={matrix.error} onRetry={() => void matrix.refetch()}
              onCell={(caza, family) => update({ areaCode: caza, level: "caza", families: family ? [family] : [] })} />
          </SectionCard>
        </div>
      </div>

      <div ref={airRef}>
        <SectionCard id="air" title="Air violations" subtitle="CNRS breaches, not report counts">
          {airSeen ? <AirSection filters={queryFilters} enabled={airSeen} onFocusArea={focusArea} /> : <Skeleton className="h-72" />}
        </SectionCard>
      </div>

      <FooterStrip meta={meta.data} filters={queryFilters} />
      {drill ? <DrilldownDrawer filters={queryFilters} title={drill.title} onClose={() => setDrill(null)} /> : null}
    </div>
  );
};

export default AnalyticsPage;
