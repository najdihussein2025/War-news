# Map features: recon and verification — 22 October 2026

## Pan, zoom and background follow-up

### Reproduction before changes

The `MAP_RECON=1` branch of `scripts/verify_map.cjs` inspected Overview at 1280×800
and 1920×1080 before implementation. Evidence: `.codex-staging/map-pan-before/recon.json`
and `{1280,1920}-before-{small,full}.png`.

- Drag-pan was enabled and worked without a preliminary click: a 90px drag changed
  longitude from 35.85 to approximately 35.54 at both sizes.
- A subsequent resize did **not** undo that genuine pointer move. The old `originalEvent`
  guard worked for drags, but did not cover zoom buttons, search, or area focus.
- Plain wheel zoomed from 7.727 to 8.181 without scrolling the page. This was the main
  gesture conflict; fullscreen was not enabling an otherwise disabled map.
- Canvas hit-testing found no large transparent blocker. The bottom-right controls'
  flex wrapper did intercept its empty gaps. Legend and playback intercepted their own
  footprints, the sticky filter bar occupied the top of the screen, and tooltips were
  already pointer-transparent. AreaPanel is an intentional interactive drawer/column.
- Closing fullscreen left zero inert elements. At 1280px, focusing the close button
  also moved document scroll from 570 to 0; focus now uses `preventScroll` both ways.
  The expanded area-selection check additionally found that replacing the background
  rankings column while fullscreen was open created a new non-inert sibling. The wrapper
  now observes those insertions and restores each element's original inert state on close.

### Camera and interaction policy

- A single resize observer resizes the existing instance and recomputes the country-fit
  minimum zoom (`cameraForBounds` minus 0.5). Padding is clamped on narrow screens so
  the 368px drawer allowance cannot consume the map's entire width.
- Bounds use Mercator viewport dimensions, recalculated on resize, fullscreen
  enter/exit, and padding changes. A camera-update hook tightens them for each zoom
  before rendering without letting old detail bounds block zoom-out. At detail zoom, each margin is one quarter of the
  viewport. At fit zoom, unavoidable letterboxing is allowed plus a small 15%-of-country
  travel allowance, so the camera does not become horizontally locked on wide screens.
- On `moveend`, a camera retaining less than 40% of the **maximum visible country bounding
  rectangle at its current zoom** eases back inside in 300ms. This is deliberately not
  polygon pixel coverage: literal 40% of the entire viewport is geometrically incompatible
  with showing all of narrow Lebanon at fit-minus-0.5 on wide/portrait screens. The runner
  reports both raw viewport coverage and normalized retention instead of hiding this distinction.
- Cooperative gestures are enabled only in the embedded map using MapLibre's existing
  handler (Ctrl/⌘+wheel, two-finger touch pan, built-in hint), disabled in fullscreen.
  See the [MapLibre gesture API](https://maplibre.org/maplibre-gl-js/docs/API/classes/CooperativeGesturesHandler/).
- A pointer-transparent first-hover/focus hint remembers dismissal in guarded localStorage.
  Empty canvas uses grab/grabbing; regions retain pointer. The focusable canvas has an
  application role and supports arrows and +/−. Rotation stays disabled.
- Button zooms, search, area focus and real gestures mark the camera as user-controlled.
  Closing an area profile does not refit it. Reset clears that state; double-clicking empty
  canvas also resets. Playback wrapping reserves the search/reset column so Reset stays exposed.
- The background and soft outline resolve existing `--color-surface-muted` and
  `--color-accent` tokens, including later theme changes. This application currently has no
  dark theme (per MASTER); no global dark theme was added. No tiles, neighbouring-land
  approximations, or network dependencies were introduced.

### Running the checks

Use a disposable frontend snapshot on port 5180 and the existing read-only API fixtures.
Do not hot-reload source during the run: the verifier intentionally retains the initial
Map object to catch unintended recreation.

```powershell
$env:PLAYWRIGHT_CORE_PATH = "$PWD/.codex-staging/playwright-core"
$env:MAP_SCREENSHOT_DIR = '.codex-staging/map-pan-after'
node scripts/verify_map.cjs
# Optional baseline diagnostics against an unchanged frontend:
$env:MAP_RECON = '1'
$env:MAP_BASE_URL = 'http://127.0.0.1:5173'
node scripts/verify_map.cjs
```

`scripts/map_camera_checks.cjs`, called by the main runner, adds embedded/fullscreen
checks at 1280×800, 1920×1080 and 390×844: real four-direction drags plus extreme pans
at fit/minimum/village zoom; minimum zoom; plain/Ctrl wheel; keyboard zoom; button zoom
preservation on resize; inert cleanup; dragging after fullscreen; area pan/zoom then close;
and dragging on the Map tab. Existing label, URL, focus, offline Arabic and drawer checks remain.
Camera metrics and screenshots are written alongside the existing verification JSON.

The initial typecheck/build exposed four pre-existing unused bindings in the Phase 2 tabs
and page. Only those unused bindings were removed, preserving props and behaviour.
`npm run lint` was attempted: this repository has no lint script, configuration, or ESLint
dependency. No new lint toolchain was added as part of this focused map change.

### Final follow-up results

- `npm run check`: typecheck passed, **158 tests passed**, production build passed.
  Vite retains its existing large-chunk warning.
- Full `node scripts/verify_map.cjs` run: passed, **72 directional camera cases**, zero
  browser errors, zero failed requests, 13 local map asset/label requests.
- Minimum normalized retention across all six size/mode combinations: **56.25%**.
  Raw viewport coverage at the smallest zoom can be below 40% (as low as 17.97%);
  that unavoidable aspect-ratio difference is reported in `verification.json`.
- **22 screenshots** in `.codex-staging/map-pan-after/`: 15 existing label/drawer
  captures, six size/mode camera captures, and a dark-background-token simulation.
  The simulation verifies map paint reacts to token changes; it is not a claim that
  the currently light-only application has a complete dark theme.
- Before/after desktop pairs: `.codex-staging/map-pan-before/1920-before-small.png`,
  `1920-before-full.png`; `.codex-staging/map-pan-after/1920-after-small.png`,
  `1920-after-full.png`. These were visually inspected alongside the phone captures.
- Double-click recovery, defensive snap-back, area-close camera preservation, runtime
  gesture switching, keyboard zoom, background inert restoration, and the original map
  instance surviving fullscreen/tab changes all passed.

No backend changes or production frontend restart were made for this follow-up.

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
