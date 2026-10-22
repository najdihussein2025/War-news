import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { cn } from "../../../lib/cn";
import { getBeirutDate } from "../../../lib/localDate";
import { formatDate } from "../../../lib/formatters";
import { levelDisabledReason, nearestSupportedLevel, excludedAirTypes, airTypeLabel } from "../airRules";
import { AirSection } from "../components/AirSection";
import { AreaPanel } from "../components/AreaPanel";
import { ErrorBlock, SectionCard, Skeleton, errorMessage, useInView } from "../components/common";
import { DrilldownDrawer } from "../components/DrilldownDrawer";
import { ActiveFilterChips, FilterBar, metricLabel } from "../components/FilterBar";
import { ArchiveNote, HeaderActions, MethodologyModal } from "../components/HeaderActions";
import { HeatMap } from "../components/HeatMap";
import { FullMapFrame } from "../components/FullMapFrame";
import { FullMapToolbar } from "../components/FullMapToolbar";
import { KpiCards } from "../components/KpiCards";
import { MatrixTable } from "../components/MatrixTable";
import { PeaksCards } from "../components/PeaksCards";
import { PlayControls, type Playback } from "../components/PlayControls";
import { RankingsPanel } from "../components/RankingsPanel";
import { TimelineChart } from "../components/TimelineChart";
import { TopAreasPanel } from "../components/TopAreasPanel";
import { buildScale, type MapScale } from "../colors";
import { defaultFilters, parseFilters, resolveRange, serializeFilters, toApiParams } from "../filters";
import { buildNameIndex } from "../geoUtils";
import { MapSections } from "../components/tabs/MapSections";
import { OverviewSections } from "../components/tabs/OverviewSections";
import { useAnalyticsMap, useAnalyticsOverview, useDebounced, useGeo, useKpis, useMapData, useMatrix, useMeta, usePeaks, usePrefetchMap, useTimeline } from "../hooks";
import { TopBarActions } from "../layout/AnalyticsLayout";
import { playbackFrames } from "../mappers";
import type { AnalyticsFilters, Grain, Level, MapResponse } from "../types";

const IDLE: Playback = { active: false, playing: false, preparing: false, progress: 0, index: 0, labels: [] };
const TABS = [
  ["overview", "Overview"], ["map", "Map"], ["incidents", "Incidents"],
  ["casualties", "Casualties"], ["air", "Air violations"], ["quality", "Data quality"],
] as const;
type AnalyticsTab = typeof TABS[number][0];
const isTab = (value: string | null): value is AnalyticsTab => TABS.some(([id]) => id === value);
// Stable references: HeatMap refits whenever its padding prop changes identity.
const FIT_DEFAULT = 16;
const FIT_UNDER_PANEL = { top: 16, bottom: 16, left: 16, right: 368 };

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
  const [methodologyOpen, setMethodologyOpen] = useState(false);
  const requestedTab = search.get("tab");
  const activeTab: AnalyticsTab = isTab(requestedTab) ? requestedTab : "overview";
  const fullMap = search.get("map") === "full";
  const setFullMap = (full: boolean) => {
    const next = new URLSearchParams(search);
    if (full) next.set("map", "full"); else next.delete("map");
    setSearch(next);
  };
  const on = (...tabs: AnalyticsTab[]) => tabs.includes(activeTab);

  const update = useCallback((patch: Partial<AnalyticsFilters>) => {
    const next = serializeFilters({ ...filters, ...patch }, today);
    if (activeTab !== "overview") next.set("tab", activeTab);
    if (fullMap) next.set("map", "full");
    setSearch(next);
  }, [filters, setSearch, today, activeTab, fullMap]);

  const reset = () => setSearch(serializeFilters(defaultFilters(today), today));
  const setTab = (tab: AnalyticsTab) => {
    const next = serializeFilters(filters, today);
    if (tab === "overview") next.delete("tab"); else next.set("tab", tab);
    setSearch(next);
  };
  const setRange = (range: string) => {
    const { from, to } = resolveRange(range, ctx);
    update({ range, dateFrom: from, dateTo: to });
  };

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
  const areaNames = useMemo(() => (geo.data ? buildNameIndex(geo.data) : null), [geo.data]);
  const areaName = filters.areaCode ? areaNames?.get(filters.areaCode)?.name_en ?? null : null;

  const grain: Grain = grainChoice ?? ((new Date(queryFilters.dateTo).getTime() - new Date(queryFilters.dateFrom).getTime()) / 86_400_000 > 120 ? "week" : "day");
  // ---- tab payloads: one request per tab, only for the active tab
  const tabParams = toApiParams(queryFilters);
  const overview = useAnalyticsOverview(tabParams, grain, activeTab === "overview");
  // The Map tab has no time grain (its trends are weekly), so its key ignores the grain toggle.
  const mapTabData = useAnalyticsMap(tabParams, "day", activeTab === "map");

  // ---- map data (never filtered to the selected area, so the whole map stays visible).
  // The Overview and Map payloads carry the map; other tabs (the full-screen map) use /map.
  const mapParams = toApiParams(queryFilters, { areaCode: null });
  const tabMapSource = activeTab === "overview" ? overview : activeTab === "map" ? mapTabData : null;
  const mapFallback = useMapData(mapParams, !tabMapSource);
  const mapQuery = {
    data: tabMapSource ? tabMapSource.data?.map : mapFallback.data,
    error: tabMapSource ? tabMapSource.error : mapFallback.error,
    isFetching: tabMapSource ? tabMapSource.isFetching : mapFallback.isFetching,
    refetch: tabMapSource ? tabMapSource.refetch : mapFallback.refetch,
  };
  const prefetch = usePrefetchMap();
  const [playback, setPlayback] = useState<Playback>(IDLE);
  const framesRef = useRef<MapResponse[]>([]);
  const frameScaleRef = useRef<MapScale>({ kind: "linear", max: 0 });

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
    frameScaleRef.current = buildScale(queryFilters.level, results.flatMap((r) => r.values.map((v) => v.value)));
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

  const actionMix = useMemo(() => {
    const totals: Record<string, number> = {};
    for (const v of mapQuery.data?.values ?? []) {
      for (const [code, n] of Object.entries(v.families ?? {})) totals[code] = (totals[code] ?? 0) + n;
    }
    return totals;
  }, [mapQuery.data]);

  const framing = playback.active && !playback.preparing;
  const shownValues = framing ? framesRef.current[playback.index]?.values ?? [] : mapQuery.data?.values ?? [];
  const scale = useMemo(
    () => (framing ? frameScaleRef.current : buildScale(mapQuery.data?.level ?? filters.level, (mapQuery.data?.values ?? []).map((v) => v.value))),
    [framing, mapQuery.data, filters.level],
  );

  const focusArea = useCallback((code: string, level: Level) => {
    update({ areaCode: code, level: level === "village" || level === "caza" || level === "mohafaza" ? level : filters.level });
  }, [update, filters.level]);

  // ---- lower sections
  const kpiParams = toApiParams(queryFilters);
  // Tabs not yet on their own payload still read /kpis, /timeline, /peaks, /matrix.
  const kpis = useKpis(kpiParams, activeTab !== "overview");
  const headline = activeTab === "overview" ? overview.data?.kpis : kpis.data;
  const [tlRef, tlSeen] = useInView();
  const [rkRef, rkSeen] = useInView();
  const [mxRef, mxSeen] = useInView();
  const [airRef, airSeen] = useInView();
  const timeline = useTimeline(kpiParams, grain, tlSeen && activeTab === "incidents");
  const peaks = usePeaks(kpiParams, tlSeen && activeTab === "incidents");
  const matrix = useMatrix(kpiParams, mxSeen);
  const fileSuffix = `${queryFilters.dateFrom}_${queryFilters.dateTo}`;

  const label = metricLabel(filters.metric);
  const mapError = mapQuery.error && !mapQuery.data ? errorMessage(mapQuery.error) : null;
  const excluded = filters.metric === "breaches" && !filters.airType ? excludedAirTypes(filters.level).map(airTypeLabel) : [];
  const mapTab = activeTab === "map";
  const areaProps = filters.areaCode ? {
    code: filters.areaCode, filters: queryFilters, onClose: () => update({ areaCode: null }), onFocusArea: focusArea,
    onViewIncidents: () => setDrill({ title: "Incidents in the selected area" }), onOpenMethodology: () => setMethodologyOpen(true),
  } : null;

  return (
    <>
      <TopBarActions><HeaderActions meta={meta.data} filters={queryFilters} onMethodologyOpen={() => setMethodologyOpen(true)} /></TopBarActions>

      <div className="sticky top-14 z-20 -mx-4 border-b border-border bg-surface/95 px-4 backdrop-blur sm:-mx-6 sm:px-6">
        <FilterBar filters={filters} meta={meta.data} today={today} onChange={update}
          resolveRange={(range) => resolveRange(range, ctx)} pendingReview={headline?.pending_review} />
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 border-t border-border/70 py-1.5">
          <nav aria-label="Analytics sections" className="-mx-1 flex max-w-full gap-0.5 overflow-x-auto px-1">
            {TABS.map(([id, tabLabel]) => (
              <button key={id} type="button" onClick={() => setTab(id)} aria-current={activeTab === id ? "page" : undefined}
                className={cn("h-7 shrink-0 rounded-md px-3 text-small font-medium focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus-ring",
                  activeTab === id ? "bg-brand-navy text-text-inverse" : "text-text-muted hover:bg-surface-muted hover:text-text-primary")}>{tabLabel}</button>
            ))}
          </nav>
          <div className="flex min-w-0 flex-1 justify-end">
            <ActiveFilterChips filters={filters} meta={meta.data} areaName={areaName} onChange={update} onRemoveRange={() => setRange("30d")} onReset={reset} />
          </div>
        </div>
      </div>

      <div className="mt-4 grid min-w-0 grid-cols-12 gap-4 [&>*]:min-w-0">
        {on("overview", "casualties") ? (
          <div className="col-span-12">
            {activeTab === "casualties" ? <p className="mb-1.5 text-caption text-text-muted">Reported deaths and injuries. Use the rankings and the matrix below to compare affected places.</p> : null}
            {activeTab === "overview"
              ? <KpiCards data={overview.data?.kpis} loading={overview.isLoading} error={overview.error} onRetry={() => void overview.refetch()} onOpenMethodology={() => setMethodologyOpen(true)} />
              : <KpiCards data={kpis.data} loading={kpis.isLoading} error={kpis.error} onRetry={() => void kpis.refetch()} onOpenMethodology={() => setMethodologyOpen(true)} />}
          </div>
        ) : null}

        {/* One map instance for both tabs: only its box changes, so maplibre is never re-created. */}
        <section aria-labelledby="map-title" className={cn("col-span-12 min-w-0", activeTab === "overview" && "xl:col-span-8", !on("overview", "map") && "hidden")}>
          <h2 id="map-title" className="sr-only">{label} by {filters.level}</h2>
          {mapError ? <ErrorBlock message={mapError} onRetry={() => void mapQuery.refetch()} /> : null}
          <div className={cn("relative", mapTab ? "h-[560px] lg:h-[calc(100dvh-13rem)] lg:max-h-[920px] lg:min-h-[600px]" : "h-[480px] md:h-[560px] xl:h-[640px]")}>
            <FullMapFrame full={fullMap} onClose={() => setFullMap(false)} toolbar={<FullMapToolbar filters={filters} meta={meta.data} onChange={update}
              play={<PlayControls state={playback} setState={setPlayback} onStart={() => void startPlayback()} onStop={stopPlayback} disabled={!geo.data} />} />}>
            {geo.data ? (
              <HeatMap
                geo={geo.data}
                level={filters.level}
                values={shownValues}
                scale={scale}
                metricLabel={label}
                incidentParams={toApiParams(queryFilters, { areaCode: null, level: "village", metric: "incidents", airType: null }).toString()}
                fullScreen={fullMap}
                onExpand={() => setFullMap(true)}
                fitPadding={(mapTab || fullMap) && filters.areaCode ? FIT_UNDER_PANEL : FIT_DEFAULT}
                familyNames={familyNames}
                selectedCode={filters.areaCode}
                onSelect={(code, level) => (code ? focusArea(code, level) : update({ areaCode: null }))}
                frameLabel={framing ? playback.labels[playback.index] : null}
                loading={mapQuery.isFetching && !framing}
                controls={!fullMap ? <PlayControls state={playback} setState={setPlayback} onStart={() => void startPlayback()} onStop={stopPlayback} disabled={!geo.data} /> : null}
              />
            ) : geo.error ? (
              <ErrorBlock message={errorMessage(geo.error)} onRetry={() => void geo.refetch()} />
            ) : <Skeleton className="h-full w-full" />}
            {(mapTab || fullMap) && areaProps ? <AreaPanel {...areaProps} variant="overlay" /> : null}
            </FullMapFrame>
          </div>
          <p className="mt-1.5 text-caption text-text-muted" role="status">
            {mapQuery.data && mapQuery.data.values.length === 0 && !mapError ? "Nothing recorded for these filters. Try a longer period or turn on pending review. " : ""}
            {mapQuery.data?.unit_note}
            {excluded.length ? ` Not shown at ${filters.level} level: ${excluded.join(", ")}.` : ""}
          </p>
        </section>

        {activeTab === "overview" ? (
          <div className="col-span-12 h-[560px] min-w-0 xl:col-span-4 xl:h-[640px]">
            {areaProps ? <AreaPanel {...areaProps} variant="column" />
              : <TopAreasPanel filters={queryFilters} metricLabel={label} onFocusArea={focusArea} mix={actionMix} familyNames={familyNames}
                  data={overview.data?.top_areas} error={overview.error} onRetry={() => void overview.refetch()} />}
          </div>
        ) : null}

        {activeTab === "overview" ? (
          <OverviewSections data={overview.data} error={overview.error} onRetry={() => void overview.refetch()} grain={grain} onGrain={setGrainChoice}
            metricLabel={label} fileSuffix={fileSuffix} onViewIncidents={() => setDrill({ title: "Incidents in this period" })} />
        ) : null}

        {mapTab ? (
          <MapSections data={mapTabData.data} error={mapTabData.error} onRetry={() => void mapTabData.refetch()} familyNames={familyNames}
            metricLabel={label} fileSuffix={fileSuffix} onFocusArea={focusArea} />
        ) : null}

        <div ref={tlRef} className={cn("col-span-12 min-w-0", activeTab !== "incidents" && "hidden")}>
          <SectionCard id="timeline" title="Timeline" subtitle={`${label} per ${grain}, stacked by ${filters.metric === "breaches" ? "air type" : "action family"}, with the 7-day average`}
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
                  <TimelineChart data={timeline.data} grain={grain} height={320} />
                  {timeline.data.coverage.gap_dates.length > 0 ? (
                    <p className="mt-1 text-caption text-text-muted">Hatched days ({timeline.data.coverage.gap_dates.length}) had low or no message coverage: missing or incomplete data, not zero incidents.</p>
                  ) : null}
                </>
              ) : <Skeleton className="h-[320px]" />}
          </SectionCard>
        </div>

        <div className={cn("col-span-12 min-w-0", activeTab !== "incidents" && "hidden")}>
          <SectionCard id="peaks" title="Peaks" subtitle="Worst day and worst week in the period, with the three most affected cazas">
            <PeaksCards data={peaks.data} loading={peaks.isLoading} error={peaks.error} onRetry={() => void peaks.refetch()} />
          </SectionCard>
        </div>

        <div ref={rkRef} className={cn("col-span-12 min-w-0", !on("incidents", "casualties") && "hidden")}>
          <SectionCard id="rankings" title="Rankings" subtitle="The same values as the map, as a keyboard-friendly list">
            {rkSeen ? <RankingsPanel filters={queryFilters} familyNames={familyNames} enabled={rkSeen} onFocusArea={focusArea} /> : <Skeleton className="h-80" />}
          </SectionCard>
        </div>

        <div ref={mxRef} className={cn("col-span-12 min-w-0", !on("incidents", "casualties") && "hidden")}>
          <SectionCard id="matrix" title="Action × caza" subtitle="Click a cell to filter the page to that caza and action">
            <MatrixTable data={matrix.data} loading={matrix.isLoading} error={matrix.error} onRetry={() => void matrix.refetch()}
              onCell={(caza, family) => update({ areaCode: caza, level: "caza", families: family ? [family] : [] })} />
          </SectionCard>
        </div>

        <div ref={airRef} className={cn("col-span-12 min-w-0", activeTab !== "air" && "hidden")}>
          <SectionCard id="air" title="Air violations" subtitle="CNRS breaches, not report counts">
            {airSeen ? <AirSection filters={queryFilters} enabled={airSeen} onFocusArea={focusArea} /> : <Skeleton className="h-72" />}
          </SectionCard>
        </div>

        <section className={cn("col-span-12 min-w-0", activeTab !== "quality" && "hidden")} aria-label="Data quality">
          <SectionCard id="quality" title="Data quality" subtitle="Coverage, pending review and geography checks for the selected period">
            <div className="grid gap-3 sm:grid-cols-3">
              <div className="rounded-md border border-border p-3"><p className="text-caption text-text-muted">Pending review</p><p className="text-h3 font-semibold tabular-nums">{kpis.data?.pending_review ?? "—"}</p></div>
              <div className="rounded-md border border-border p-3"><p className="text-caption text-text-muted">Casualty status</p><p className="text-h3 font-semibold tabular-nums">{kpis.data?.casualty_completeness.pct ?? "—"}{kpis.data?.casualty_completeness.pct !== null && kpis.data ? "%" : ""}</p></div>
              <div className="rounded-md border border-border p-3"><p className="text-caption text-text-muted">Last refresh</p><p className="text-small font-semibold">{meta.data?.last_refresh ? formatDate(meta.data.last_refresh) : "—"}</p></div>
            </div>
          </SectionCard>
        </section>

        <div className="col-span-12"><ArchiveNote meta={meta.data} /></div>
      </div>

      {methodologyOpen ? <MethodologyModal onClose={() => setMethodologyOpen(false)} /> : null}
      {drill ? <DrilldownDrawer filters={queryFilters} title={drill.title} onClose={() => setDrill(null)} /> : null}
    </>
  );
};

export default AnalyticsPage;
