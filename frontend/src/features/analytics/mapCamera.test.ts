import { describe, expect, it } from "vitest";
import { LngLat, MercatorCoordinate } from "maplibre-gl";
import { cameraPadding, constrainCenter, panBounds } from "./mapCamera";

describe("map camera constraints", () => {
  it("keeps desktop fit padding intact", () => {
    expect(cameraPadding(16, 1280, 640)).toEqual({ top: 16, bottom: 16, left: 16, right: 16 });
  });
  it("leaves usable map space beside a drawer on a phone", () => {
    const p = cameraPadding({ top: 96, bottom: 16, left: 16, right: 368 }, 358, 480);
    expect(p.left + p.right).toBeCloseTo(358 * .45);
    expect(p.top + p.bottom).toBe(112);
  });
  it.each([[1280, 800], [1920, 1080], [390, 844]])("limits zoomed edge margins to a quarter screen at %ix%i", (width, height) => {
    const zoom = 11.2, world = 512 * 2 ** zoom;
    const b = panBounds(width, height, zoom);
    const sw = MercatorCoordinate.fromLngLat(b.getSouthWest());
    const ne = MercatorCoordinate.fromLngLat(b.getNorthEast());
    const countryNW = MercatorCoordinate.fromLngLat([35.05, 34.7]);
    const countrySE = MercatorCoordinate.fromLngLat([36.65, 33.03]);
    expect((countryNW.x - sw.x) * world).toBeCloseTo(width * .25);
    expect((countryNW.y - ne.y) * world).toBeCloseTo(height * .25);
    expect((ne.x - countrySE.x) * world).toBeCloseTo(width * .25);
    expect((sw.y - countrySE.y) * world).toBeCloseTo(height * .25);
  });
  it("does not force a higher zoom in a wide country-fit viewport", () => {
    const width = 1920, height = 1080, zoom = 7.2, world = 512 * 2 ** zoom;
    const b = panBounds(width, height, zoom);
    const sw = MercatorCoordinate.fromLngLat(b.getSouthWest()), ne = MercatorCoordinate.fromLngLat(b.getNorthEast());
    expect((ne.x - sw.x) * world).toBeGreaterThanOrEqual(width - .001);
    expect((sw.y - ne.y) * world).toBeGreaterThanOrEqual(height - .001);
  });
  it("preserves a camera inside the allowed region", () => {
    const center = constrainCenter(new LngLat(35.85, 33.86), 1920, 1080, 11);
    expect(center.lng).toBeCloseTo(35.85);
    expect(center.lat).toBeCloseTo(33.86);
  });
  it("clamps an off-country camera at detail zoom without changing zoom", () => {
    const zoom = 11, width = 1920, height = 1080;
    const center = constrainCenter(new LngLat(5, 5), width, height, zoom);
    const bound = panBounds(width, height, zoom), world = 512 * 2 ** zoom;
    const sw = MercatorCoordinate.fromLngLat(bound.getSouthWest());
    const at = MercatorCoordinate.fromLngLat(center);
    expect((at.x - sw.x) * world).toBeCloseTo(width / 2);
    expect((sw.y - at.y) * world).toBeCloseTo(height / 2);
  });
});
