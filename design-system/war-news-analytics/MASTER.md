# War News Analytics: design system (MASTER)

Generated with UI/UX Pro Max (query: conflict monitoring research analytics dashboard, data-dense,
geographic heat map, trustworthy, serious) and then **adapted to the admin panel's existing tokens**
(`frontend/src/styles/tokens.css`, `tailwind.config.js`). Where the generator disagreed with the app
(Fira Sans/Code, `#1E40AF` blue, `#D97706` amber, dark mode) the app wins, so the page looks like
part of the same product. Style retained from the generator: **Data-Dense Dashboard** (KPI cards,
tight padding, tables next to charts, hover tooltips, visible focus, reduced motion respected).

## Foundations (reuse, do not redefine)

| Concern | Decision |
|---|---|
| Fonts | Noto Sans + Noto Sans Arabic (already loaded). No new web fonts |
| Colors | `--brand-navy #082d6f` primary, `--brand-gold #bc8e38` highlight, cool-grey neutrals `--gray-*`, semantic `--color-*` |
| Mode | The admin panel has **no dark mode**; analytics is light only. Tokens are CSS variables, so a future dark mode only needs new values |
| Spacing | `--space-1..10` (0.25rem steps). Data-dense: cards use `p-4`, gaps `gap-4` |
| Radius / shadow | `rounded-md/lg`, `--shadow-raised` for cards, `--shadow-overlay` for drawers and tooltips |
| Numbers | Always `font-variant-numeric: tabular-nums` (class `.tnum`), thousands separators via `Intl.NumberFormat` |
| Arabic | Per element `dir="rtl" lang="ar"` (no i18n library); never flip the page |
| Focus | 2px `--color-focus-ring` outline, 2px offset, on every interactive element |
| Motion | 150-200ms transitions; everything respects `prefers-reduced-motion` (global rule exists) |
| Icons | Inline SVG (lucide style, 1.5px stroke). No emojis |

## Type scale (existing Tailwind sizes)

`caption 12` footnotes and axis labels, `small 14` table text and controls, `body 16`, `h4 20` card
titles and KPI labels, KPI value `text-h2` (31px) semibold tabular, page title `h3`.

## Heat map color scale (7 steps, sequential, colorblind-safe)

ColorBrewer **YlOrRd-7**, ordered by luminance so it survives grayscale and the common color-vision
deficiencies. Classes are **quantile** breaks computed on the values returned by `/map` (7 classes,
fewer when there are few distinct values).

| Step | Hex | Text on it |
|---|---|---|
| 1 | `#ffffb2` | dark |
| 2 | `#fed976` | dark |
| 3 | `#feb24c` | dark |
| 4 | `#fd8d3c` | dark |
| 5 | `#fc4e2a` | light |
| 6 | `#e31a1c` | light |
| 7 | `#b10026` | light |

* **No data / zero**: `#e6ebf0` (neutral cool grey) with the legend label "No incidents".
* **Disputed areas** (Chebaa Farms, "Litige" shapes): diagonal hatch (`#8ca0af` 1px lines, 45 degrees, 6px
  pitch) drawn over the base fill via a `fill-pattern`; legend entry "Disputed area".
* **Outlines**: village borders `rgba(8,45,111,.15)` 0.4px; caza `rgba(8,45,111,.45)` 0.9px; mohafaza `#082d6f` 1.6px.
* **Hover / selected**: 2px `--brand-gold` outline. Color is never the only signal: values are in the
  tooltip, the legend shows ranges, and the rankings table is the keyboard alternative.

## Categorical palette (10 action families, stable everywhere)

Okabe-Ito based, checked against deuteranopia/protanopia; the same family always gets the same color
in the filter chips, stacked timeline, matrix headers, area side panel and tooltips.

| Family code | Hex |
|---|---|
| airstrikes | `#d55e00` |
| drone_strikes | `#0072b2` |
| artillery | `#cc79a7` |
| flares_phosphorus | `#e69f00` |
| demolitions | `#8c5a2b` |
| gunfire | `#009e73` |
| incursions | `#56b4e9` |
| air_violations | `#082d6f` |
| other | `#7f8c8d` |
| unclassified | `#b9aec9` (hatched in charts, since it is "pending") |

Air breach types (own series): spy balloon `#56b4e9`, warplane `#082d6f`, surveillance/drone `#0072b2`, helicopter `#e69f00`.

## Chart rules

* Timeline: stacked bars by family + 7-day moving average line in `--gray-900`; peaks annotated with a
  dot and value; days with no ingestion are drawn as a light hatched band, distinct from a zero bar.
* Always sort rankings descending and show the number next to the bar.
* Axes: `--gray-600` 12px, grid `--gray-200`. Tooltips: white card, `--shadow-overlay`, value + share.
* Every chart has a table or text alternative on the page (rankings, matrix, KPI split).

## States

Loading = skeleton blocks (`bg-gray-100 animate-pulse`, static under reduced motion); empty = `EmptyState`
with the filter that produced it; error = card with message + Retry (`role="alert"`); stale data = footer
"updated N min ago" turns warning color after 15 minutes.
