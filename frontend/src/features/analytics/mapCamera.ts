import { LngLatBounds, MercatorCoordinate, type LngLat, type Map, type PaddingOptions } from "maplibre-gl";
import { LEBANON_BOUNDS } from "./geoUtils";

/** Clamp drawer padding on narrow screens so cameraForBounds always has usable space. */
export function cameraPadding(padding: number | PaddingOptions, width: number, height: number): PaddingOptions {
  const p = typeof padding === "number" ? { top: padding, bottom: padding, left: padding, right: padding } : padding;
  const x = Math.min(1, width * 0.45 / Math.max(1, p.left + p.right));
  const y = Math.min(1, height * 0.45 / Math.max(1, p.top + p.bottom));
  return { left: p.left * x, right: p.right * x, top: p.top * y, bottom: p.bottom * y };
}

/** Screen-sized margins in Mercator space, not fixed degrees (which vary with zoom). */
export function panBounds(width: number, height: number, zoom: number): LngLatBounds {
  const nw = MercatorCoordinate.fromLngLat([LEBANON_BOUNDS[0][0], LEBANON_BOUNDS[1][1]]);
  const se = MercatorCoordinate.fromLngLat([LEBANON_BOUNDS[1][0], LEBANON_BOUNDS[0][1]]);
  const world = 512 * 2 ** zoom;
  const vw = width / world, vh = height / world;
  // Letterboxing is unavoidable when the country is smaller than the viewport.
  // Keep a little travel in that case (15% of the country) so fit view isn't locked.
  // Once zoomed in, allow only a quarter-screen past each national edge.
  const cw = se.x - nw.x, ch = se.y - nw.y;
  const mx = Math.max(vw * 0.25, (vw - cw) / 2 + Math.min(vw, cw) * 0.15);
  const my = Math.max(vh * 0.25, (vh - ch) / 2 + Math.min(vh, ch) * 0.15);
  return new LngLatBounds(new MercatorCoordinate(nw.x - mx, se.y + my).toLngLat(),
    new MercatorCoordinate(se.x + mx, nw.y - my).toLngLat());
}

/** Apply the detail-zoom limits before rendering, without changing maxBounds during
 * a zoom gesture (MapLibre otherwise raises zoom to fit the previous, tighter bounds).
 */
export function constrainCenter(center: LngLat, width: number, height: number, zoom: number): LngLat {
  const bounds = panBounds(width, height, zoom);
  const sw = MercatorCoordinate.fromLngLat(bounds.getSouthWest());
  const ne = MercatorCoordinate.fromLngLat(bounds.getNorthEast());
  const point = MercatorCoordinate.fromLngLat(center), world = 512 * 2 ** zoom;
  const hx = width / world / 2, hy = height / world / 2;
  return new MercatorCoordinate(
    Math.max(sw.x + hx, Math.min(ne.x - hx, point.x)),
    Math.max(ne.y + hy, Math.min(sw.y - hy, point.y)),
  ).toLngLat();
}

/** Fraction of the maximum visible national bounding rectangle at this zoom.
 * Literal viewport coverage cannot reach 40% at country-fit on wide/portrait boxes.
 */
export function visibleCountryFraction(map: Map): number {
  const nw = map.project([LEBANON_BOUNDS[0][0], LEBANON_BOUNDS[1][1]]);
  const se = map.project([LEBANON_BOUNDS[1][0], LEBANON_BOUNDS[0][1]]);
  const { clientWidth: w, clientHeight: h } = map.getContainer();
  const area = Math.max(0, Math.min(w, se.x) - Math.max(0, nw.x))
    * Math.max(0, Math.min(h, se.y) - Math.max(0, nw.y));
  return area / Math.max(1, Math.min(w, se.x - nw.x) * Math.min(h, se.y - nw.y));
}
