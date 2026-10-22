import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import "../analytics.css";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { GeoCollection } from "../api";
import { DISPUTED_LINE, FAMILY_COLORS, NO_DATA_COLOR, scaleColor, type MapScale } from "../colors";
import { buildNameIndex, findBounds, LEBANON_BOUNDS, labelPoints, searchVillages, type SearchHit } from "../geoUtils";
import { formatNumber } from "../mappers";
import type { Level, MapValue } from "../types";
import { MapLegend } from "./MapLegend";

type Geo = Record<Level, GeoCollection>;

type Props = {
  geo: Geo;
  level: Level;
  values: MapValue[];
  scale: MapScale;
  metricLabel: string;
  /** Space kept around Lebanon when fitting (e.g. more on the right under an overlay panel). */
  fitPadding?: number | maplibregl.PaddingOptions;
  familyNames: Record<string, string>;
  selectedCode: string | null;
  onSelect: (code: string | null, level: Level) => void;
  frameLabel?: string | null;
  loading?: boolean;
  controls?: ReactNode;
  fullScreen?: boolean;
  onExpand?: () => void;
};

const HATCH_SIZE = 8;

const makeHatch = (): { width: number; height: number; data: Uint8ClampedArray } => {
  const canvas = document.createElement("canvas");
  canvas.width = HATCH_SIZE;
  canvas.height = HATCH_SIZE;
  const ctx = canvas.getContext("2d");
  if (!ctx) return { width: HATCH_SIZE, height: HATCH_SIZE, data: new Uint8ClampedArray(HATCH_SIZE * HATCH_SIZE * 4) };
  ctx.strokeStyle = DISPUTED_LINE;
  ctx.lineWidth = 1.4;
  ctx.beginPath();
  ctx.moveTo(-1, HATCH_SIZE + 1);
  ctx.lineTo(HATCH_SIZE + 1, -1);
  ctx.moveTo(-1, 1);
  ctx.lineTo(1, -1);
  ctx.moveTo(HATCH_SIZE - 1, HATCH_SIZE + 1);
  ctx.lineTo(HATCH_SIZE + 1, HATCH_SIZE - 1);
  ctx.stroke();
  return { width: HATCH_SIZE, height: HATCH_SIZE, data: ctx.getImageData(0, 0, HATCH_SIZE, HATCH_SIZE).data };
};

const LEVELS: Level[] = ["mohafaza", "caza", "village"];
const BLANK_STYLE: maplibregl.StyleSpecification = {
  version: 8,
  sources: {},
  layers: [{ id: "background", type: "background", paint: { "background-color": "#f6f9fc" } }],
};

export const HeatMap = ({
  geo, level, values, scale, metricLabel, familyNames, selectedCode, onSelect, frameLabel, loading, controls, fitPadding = 16, fullScreen = false, onExpand,
}: Props) => {
  const container = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const [ready, setReady] = useState(false);
  const [tooltip, setTooltip] = useState<{ x: number; y: number; code: string } | null>(null);
  const [query, setQuery] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const hoverRef = useRef<string | null>(null);
  const selectedRef = useRef<string | null>(null);
  const levelRef = useRef(level);
  const onSelectRef = useRef(onSelect);
  const shownRef = useRef<string[]>([]);
  levelRef.current = level;
  onSelectRef.current = onSelect;

  const names = useMemo(() => buildNameIndex(geo), [geo]);
  const valueByCode = useMemo(() => new Map(values.map((v) => [v.code, v])), [values]);
  const hits: SearchHit[] = useMemo(() => searchVillages(geo, query), [geo, query]);

  useEffect(() => {
    const id = requestAnimationFrame(() => mapRef.current?.resize());
    return () => cancelAnimationFrame(id);
  }, [fullScreen]);

  // Map creation (once).
  useEffect(() => {
    if (!container.current) return undefined;
    const map = new maplibregl.Map({
      container: container.current,
      style: BLANK_STYLE,
      bounds: LEBANON_BOUNDS,
      fitBoundsOptions: { padding: 16 },
      attributionControl: false,
      dragRotate: false,
      pitchWithRotate: false,
      maxBounds: [[33.5, 32.2], [38.2, 35.6]],
      minZoom: 6,
    });
    map.touchZoomRotate.disableRotation();
    mapRef.current = map;

    map.on("load", () => {
      map.addImage("hatch", makeHatch(), { pixelRatio: 2 });
      for (const lvl of LEVELS) {
        map.addSource(lvl, { type: "geojson", data: geo[lvl] as never, promoteId: "code" });
      }
      for (const lvl of LEVELS) {
        map.addLayer({
          id: `fill-${lvl}`,
          type: "fill",
          source: lvl,
          layout: { visibility: lvl === levelRef.current ? "visible" : "none" },
          paint: { "fill-color": ["coalesce", ["feature-state", "color"], NO_DATA_COLOR], "fill-opacity": 0.92 },
        });
      }
      map.addLayer({
        id: "disputed-hatch",
        type: "fill",
        source: "village",
        filter: ["any", ["==", ["get", "disputed"], true], ["==", ["get", "name_en"], "Litige"]],
        paint: { "fill-pattern": "hatch", "fill-opacity": 0.9 },
      });
      map.addLayer({ id: "line-village", type: "line", source: "village", minzoom: 8.5, paint: { "line-color": "rgba(8,45,111,0.18)", "line-width": 0.4 } });
      map.addLayer({ id: "line-caza", type: "line", source: "caza", paint: { "line-color": "rgba(8,45,111,0.5)", "line-width": 0.9 } });
      map.addLayer({ id: "line-mohafaza", type: "line", source: "mohafaza", paint: { "line-color": "#082d6f", "line-width": 1.6 } });
      for (const lvl of LEVELS) {
        map.addLayer({
          id: `highlight-${lvl}`,
          type: "line",
          source: lvl,
          layout: { visibility: lvl === levelRef.current ? "visible" : "none" },
          paint: {
            "line-color": "#bc8e38",
            "line-width": ["case", ["boolean", ["feature-state", "selected"], false], 3.2, ["boolean", ["feature-state", "hover"], false], 2.2, 0],
          },
        });
      }
      map.addLayer({
        id: "search-highlight",
        type: "line",
        source: "village",
        paint: { "line-color": "#bc8e38", "line-width": ["case", ["boolean", ["feature-state", "searched"], false], 3.4, 0] },
      });
      // The box may have changed size between construction and load (tab switch, breakpoint).
      map.resize();
      setReady(true);
    });

    // Keep the WebGL canvas the size of its box; debounced so a breakpoint or drag-resize
    // repaints once at the final size instead of on every intermediate frame.
    // The window listener also covers a viewport crossing a breakpoint before the
    // observer has delivered its first entry.
    let resizeTimer: number | undefined;
    const scheduleResize = () => {
      window.clearTimeout(resizeTimer);
      resizeTimer = window.setTimeout(() => map.resize(), 100);
    };
    const sizeObserver = new ResizeObserver(scheduleResize);
    sizeObserver.observe(container.current);
    window.addEventListener("resize", scheduleResize);

    const handleMove = (e: maplibregl.MapMouseEvent) => {
      const layer = `fill-${levelRef.current}`;
      if (!map.getLayer(layer)) return;
      const feature = map.queryRenderedFeatures(e.point, { layers: [layer] })[0];
      const code = feature ? String(feature.properties?.code ?? feature.id) : null;
      if (hoverRef.current && hoverRef.current !== code) {
        map.setFeatureState({ source: levelRef.current, id: hoverRef.current }, { hover: false });
      }
      hoverRef.current = code;
      if (code) {
        map.setFeatureState({ source: levelRef.current, id: code }, { hover: true });
        setTooltip({ x: e.point.x, y: e.point.y, code });
      } else {
        setTooltip(null);
      }
      map.getCanvas().style.cursor = code ? "pointer" : "";
    };
    const handleLeave = () => {
      if (hoverRef.current) map.setFeatureState({ source: levelRef.current, id: hoverRef.current }, { hover: false });
      hoverRef.current = null;
      setTooltip(null);
    };
    const handleClick = (e: maplibregl.MapMouseEvent) => {
      const layer = `fill-${levelRef.current}`;
      if (!map.getLayer(layer)) return;
      const feature = map.queryRenderedFeatures(e.point, { layers: [layer] })[0];
      const code = feature ? String(feature.properties?.code ?? feature.id) : null;
      onSelectRef.current(code && code !== selectedRef.current ? code : null, levelRef.current);
    };
    map.on("mousemove", handleMove);
    map.on("mouseout", handleLeave);
    map.on("click", handleClick);
    return () => {
      window.clearTimeout(resizeTimer);
      sizeObserver.disconnect();
      window.removeEventListener("resize", scheduleResize);
      map.remove();
      mapRef.current = null;
      setReady(false);
    };
    // geo is stable for the page lifetime; the map is created exactly once.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Active level visibility.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    for (const lvl of LEVELS) {
      const visibility = lvl === level ? "visible" : "none";
      map.setLayoutProperty(`fill-${lvl}`, "visibility", visibility);
      map.setLayoutProperty(`highlight-${lvl}`, "visibility", visibility);
    }
    if (hoverRef.current) hoverRef.current = null;
    setTooltip(null);
  }, [level, ready]);

  // Colors via feature-state; layers are never re-added.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    for (const lvl of LEVELS) map.removeFeatureState({ source: lvl });
    for (const v of values) map.setFeatureState({ source: level, id: v.code }, { color: scaleColor(scale, v.value) });
    shownRef.current = values.map((v) => v.code);
    if (selectedRef.current) map.setFeatureState({ source: level, id: selectedRef.current }, { selected: true });
  }, [values, scale, level, ready]);

  // Value labels on each polygon at mohafaza/caza level (HTML markers: the blank style has no glyphs).
  const anchors = useMemo(() => (level === "village" ? null : labelPoints(geo[level])), [geo, level]);
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !anchors) return undefined;
    const markers = values.flatMap((v) => {
      const at = anchors.get(v.code);
      if (!at || !(v.value > 0)) return [];
      const el = document.createElement("div");
      el.className = "analytics-map-label";
      el.textContent = formatNumber(v.value);
      el.setAttribute("aria-hidden", "true");
      return [new maplibregl.Marker({ element: el }).setLngLat(at).addTo(map)];
    });
    return () => markers.forEach((m) => m.remove());
  }, [values, anchors, ready]);

  // Keep Lebanon filling the box when the container changes size (tabs, side panel), unless an area is focused.
  const userMovedRef = useRef(false);
  useEffect(() => {
    const map = mapRef.current;
    const node = container.current;
    if (!map || !ready || !node) return undefined;
    const onMove = (e: { originalEvent?: unknown }) => { if (e.originalEvent) userMovedRef.current = true; };
    map.on("movestart", onMove);
    const fit = () => {
      map.resize();
      if (!userMovedRef.current && !selectedRef.current) map.fitBounds(LEBANON_BOUNDS, { padding: fitPadding, duration: 0 });
    };
    fit();
    let fitTimer: number | undefined;
    const observer = new ResizeObserver(() => {
      window.clearTimeout(fitTimer);
      fitTimer = window.setTimeout(fit, 100);
    });
    observer.observe(node);
    return () => { window.clearTimeout(fitTimer); observer.disconnect(); map.off("movestart", onMove); };
  }, [ready, fitPadding]);

  // Selected area highlight + fit.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    if (selectedRef.current) {
      for (const lvl of LEVELS) map.setFeatureState({ source: lvl, id: selectedRef.current }, { selected: false });
    }
    selectedRef.current = selectedCode;
    if (selectedCode) {
      const found = findBounds(geo, selectedCode);
      if (found) {
        map.setFeatureState({ source: found.level, id: selectedCode }, { selected: true });
        map.fitBounds(found.bounds, { padding: 80, maxZoom: found.level === "village" ? 12 : 10, duration: 600 });
      }
    }
  }, [selectedCode, ready, geo]);

  const resetView = useCallback(() => {
    userMovedRef.current = false;
    mapRef.current?.fitBounds(LEBANON_BOUNDS, { padding: fitPadding, duration: 500 });
  }, [fitPadding]);

  const pickHit = (hit: SearchHit) => {
    const map = mapRef.current;
    if (!map) return;
    map.removeFeatureState({ source: "village" }, "searched");
    map.setFeatureState({ source: "village", id: hit.code }, { searched: true });
    const found = findBounds(geo, hit.code);
    if (found) map.fitBounds(found.bounds, { padding: 120, maxZoom: 12, duration: 700 });
    else if (hit.lat !== null && hit.lon !== null) map.flyTo({ center: [hit.lon, hit.lat], zoom: 11 });
    setQuery(`${hit.name_en} ${hit.name_ar}`.trim());
    setSearchOpen(false);
  };

  const tip = tooltip ? names.get(tooltip.code) : null;
  const tipValue = tooltip ? valueByCode.get(tooltip.code) : undefined;
  const topFamilies = tipValue?.families
    ? Object.entries(tipValue.families).sort((a, b) => b[1] - a[1]).slice(0, 4)
    : [];

  return (
    <div className="relative h-full w-full overflow-hidden rounded-lg border border-card-border bg-surface">
      <div
        ref={container}
        className="h-full w-full"
        role="application"
        aria-label="Heat map of Lebanon. Use the rankings table below for a keyboard accessible list of the same values."
      />

      {/* Lebanon's bounding box leaves the sea (top-left) and land outside Lebanon
          (bottom-right) empty, so the overlays sit there instead of over the data. */}
      <div className="absolute bottom-3 right-3 flex flex-col items-end gap-2">
        <div className="relative w-56">
          <label htmlFor="map-search" className="sr-only">Search a village by Arabic or English name</label>
          <input
            id="map-search"
            value={query}
            onChange={(e) => { setQuery(e.target.value); setSearchOpen(true); }}
            onFocus={() => setSearchOpen(true)}
            onKeyDown={(e) => {
              if (e.key === "Escape") setSearchOpen(false);
              if (e.key === "Enter" && hits[0]) pickHit(hits[0]);
            }}
            placeholder="Find a village (عربي / English)"
            autoComplete="off"
            className="h-9 w-full rounded-md border border-input-border bg-input-bg px-3 text-small shadow-raised hover:border-input-border-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus-ring"
          />
          {searchOpen && hits.length > 0 ? (
            <ul role="listbox" aria-label="Matching villages" className="absolute bottom-full z-30 mb-1 max-h-64 w-full overflow-auto rounded-md border border-border bg-surface-raised shadow-overlay">
              {hits.map((hit) => (
                <li key={hit.code} role="option" aria-selected="false">
                  <button type="button" onClick={() => pickHit(hit)} className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-small hover:bg-surface-muted focus-visible:bg-surface-muted focus-visible:outline-none">
                    <span>{hit.name_en}</span>
                    <span dir="rtl" lang="ar" className="text-text-muted">{hit.name_ar}</span>
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
        <div className="flex items-center gap-2">
          <div className="flex overflow-hidden rounded-md border border-border bg-surface-raised shadow-raised">
            <button type="button" aria-label="Zoom in" onClick={() => mapRef.current?.zoomIn()} className="h-9 w-9 text-h4 leading-none hover:bg-surface-muted focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-focus-ring">+</button>
            <button type="button" aria-label="Zoom out" onClick={() => mapRef.current?.zoomOut()} className="h-9 w-9 border-l border-border text-h4 leading-none hover:bg-surface-muted focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-focus-ring">−</button>
          </div>
          <button type="button" onClick={resetView} className="h-9 rounded-md border border-border bg-surface-raised px-3 text-small font-medium shadow-raised hover:bg-surface-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus-ring">Reset view</button>
        </div>
      </div>

      {onExpand ? <button type="button" onClick={onExpand} aria-label="View full map" style={fullScreen ? { display: "none" } : undefined}
        className="absolute right-3 top-3 flex h-9 items-center gap-2 rounded-md border border-border bg-surface-raised px-3 text-small font-medium shadow-raised hover:bg-surface-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus-ring">
        <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><path d="M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5M3 3l6 6m12-6-6 6M3 21l6-6m12 6-6-6" /></svg>
        View full map
      </button> : null}
      <div className={`absolute left-3 ${fullScreen ? "top-28 sm:top-20" : "top-3"}`}><MapLegend scale={scale} metricLabel={metricLabel} /></div>
      {controls ? <div className="absolute bottom-3 left-1/2 -translate-x-1/2">{controls}</div> : null}
      <div className="pointer-events-none absolute left-1/2 top-3 flex -translate-x-1/2 flex-col items-center gap-1.5">
        {frameLabel ? <div className="rounded-md bg-brand-navy px-3 py-1 text-small font-semibold text-text-inverse tabular-nums shadow-raised" aria-live="polite">{frameLabel}</div> : null}
        {loading ? <div className="rounded-md bg-surface-raised px-2 py-1 text-caption text-text-muted shadow-raised" role="status">Updating…</div> : null}
      </div>

      {tooltip && tip ? (
        <div
          role="tooltip"
          className="pointer-events-none absolute z-20 w-60 rounded-md border border-border bg-surface-raised p-3 text-small shadow-overlay"
          style={{ left: Math.min(tooltip.x + 14, (container.current?.clientWidth ?? 600) - 250), top: Math.max(tooltip.y - 8, 8) }}
        >
          <div dir="rtl" lang="ar" className="text-body font-semibold">{tip.name_ar || "—"}</div>
          <div className="text-text-muted">{tip.name_en}</div>
          <div className="mt-2 tabular-nums">
            <span className="text-h4 font-semibold">{formatNumber(tipValue?.value ?? 0)}</span>{" "}
            <span className="text-text-muted">{metricLabel}</span>
          </div>
          {topFamilies.length ? (
            <ul className="mt-2 space-y-1">
              {topFamilies.map(([code, value]) => (
                <li key={code} className="flex items-center justify-between gap-2 text-caption">
                  <span className="flex items-center gap-1.5"><span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: FAMILY_COLORS[code] }} aria-hidden="true" />{familyNames[code] ?? code}</span>
                  <span className="tabular-nums">{formatNumber(value)}</span>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </div>
  );
};
