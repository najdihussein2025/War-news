# Map features: recon and verification — 22 October 2026

## Recon before implementation

`HeatMap.tsx` used HTML `maplibregl.Marker` value badges on mohafaza/caza polygon centroids.
The blank style had no glyph URL or RTL plugin. HTML badges could not participate in symbol collisions.

| Boundary file in `frontend/public/geo` | Features | Geometry | Existing centers |
| --- | ---: | --- | --- |
| `lb_mohafaza.geojson` | 8 | Polygon | Computed from geometry |
| `lb_caza.geojson` | 26 | Polygon / MultiPolygon | Computed from geometry |
| `lb_village.geojson` | 1,611 | Polygon / MultiPolygon | All have boundary-derived centers |

The running villages table has 1,544 rows, with 0 missing UTM coordinates and 0 unlinked
boundary codes. The new authenticated `/api/analytics/village-labels` endpoint converts the
table's UTM zone 36N coordinates to WGS84 with the existing conversion utility. It returns
1,544 points, `missing_coordinates: 0`, and `unlinked: 0`. Boundary-derived village centers are
not substituted for missing table coordinates. Missing coordinates are skipped and reported.

## Result

- Grid children can shrink; bilingual ranking names truncate with full `title` text.
  The heading uses “Top mohafazat”; caza/village headings reflect the displayed row count.
- “View full map” works in Overview and Map. The same mounted map becomes a viewport overlay;
  URL filters persist with `map=full`. Background content is inert, focus cycles within the map,
  Escape/button close it, and focus returns to the trigger. Opening/closing calls `resize()`.
- Full-screen controls include level, action family, metric, period, playback, language,
  legend, search, zoom/reset, and close. Selecting an area opens a drawer above the map.
- Place names and value badges are symbol layers sharing MapLibre's collision index.
  Badges have white rounded backgrounds, bold type, and collision priority over names.
  Names use a 1.5px white halo and dark text, with EN / AR / Both (default Both).
- Mohafaza names appear below zoom 8.6; caza names from 8.6 to 10; villages from 10.
  At 1440px, measured country fit is approximately 7.73 embedded and 8.52 full-screen at
  1080px height, keeping country names visible in both cases. Caza/village screenshots use
  zoom 9.2 / 11.2. Village `symbol-sort-key` favors larger incident counts for the selected
  period and filters, independently of the selected map metric.
- Village point geometry is fetched and cached independently of filters. Filter changes
  update only the priority expression and numeric badge source, not the village GeoJSON.

## Offline assets and Arabic

PBFs for Noto Sans Regular/Bold (Latin, Arabic and Arabic presentation-form ranges) live in
`frontend/public/map-fonts`. The RTL plugin and its license live in `frontend/public/map-rtl`.
`scripts/vendor_map_assets.mjs` is a build-time download tool, not a runtime dependency.
`map-fonts/manifest.json` records source URLs and SHA-256 hashes; runtime requests use only
the frontend's origin. Font and plugin licenses are included.

The RTL plugin is pinned to **0.2.3**, matching MapLibre **4.7.1**'s synchronous worker
registration contract. Version 0.3.0 imported asynchronously and caused a worker import error;
browser verification caught it and the compatible local file fixed it.

An actual browser worker running the bundled plugin confirmed:

- Logical text: `بنت جبيل`
- Shaped text: `ﺑﻨﺖ ﺟﺒﻴﻞ` (connected presentation forms)
- Visual order: `ﻞﻴﺒﺟ ﺖﻨﺑ` (right-to-left)

Screenshots were also visually inspected. All nonlocal HTTP requests were blocked during
verification; there were no blocked external requests, missing glyph requests, or browser errors.

## Verification evidence

Browser runner: `scripts/verify_map.cjs`. Read-only aggregate snapshot builder:
`scripts/map_verify_fixtures.py`. The runner uses intercepted session/API responses from that
snapshot on a disposable frontend at port 5180; it does not change production authentication.

Screenshots and JSON evidence are in `.codex-staging/map-screenshots/` (local artifacts):

- `{1440,1920}-{normal,full}-{country,caza,village}.png` — 12 map captures.
- `{1440,1920}-full-arabic.png` — Arabic-only captures.
- `1920-full-area-profile.png` — selected area and drawer, with controls accessible.
- `verification.json` — measured dimensions, zooms, rendered labels, shaping result, and requests.

Assertions cover no horizontal document overflow at 1280/1440/1920; exact viewport map sizing;
all three name levels; absence of HTML markers; focus containment/return; Escape and close;
full-screen persistence after refresh and filter changes; area selection/drawer; opening from
the Map tab; and no runtime external requests. The village point endpoint is requested once
per page lifetime, including through filter changes (a refresh starts a new lifetime).

Frontend suite: 150 tests passed in the verification copy. Backend label tests: 3 passed,
including missing-coordinate reporting, filter-independent caching, and authentication.
Typecheck and production build passed in the verified snapshot. Concurrent Phase 2 edits
were preserved and were not authored as part of these map changes.
