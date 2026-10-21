# Analytics page: overrides on MASTER.md

Layout (top to bottom, 1024px minimum width, no horizontal scroll, content max-width 1440px):

1. **Sticky filter bar** (`top-0`, z-20, `bg-surface-raised`, bottom border): date presets, level switch
   (segmented), family multi-select with colour dots, metric select, include-pending toggle with the
   pending count, reset. All state in the URL query string.
2. **Heat map**: full width, 560px tall (min 420). Legend bottom-left, zoom/reset/search top-right,
   play controls bottom-center. Side panel (360px) slides over the map's right edge on area click.
3. **KPI row**: 6 cards in a 6-column grid (3 columns under 1280px). Value, delta chip (up = danger
   color for incidents/deaths, neutral grey for "affected" counts), 40px sparkline.
4. **Timeline** full width (320px), **Peaks** two cards beside it at >= 1280px.
5. **Rankings** tabs + DataTable (left, 7/12) and **Action x caza matrix** (right, 5/12 at >= 1280px,
   stacked below that). Matrix cells use the 7-step sequential scale scaled per table.
6. **Air violations** section: breaches by type over time + by mohafaza/caza + methodology note.
7. **Footer strip**: freshness, archive cut-off, methodology link, Export to Excel.

Interaction rules: hover tooltip = name_ar (rtl) over name_en, metric value, top families; click = filter
the page to the area and open the side panel; the rankings table rows do the same (keyboard path).
Unsupported air levels are `aria-disabled` buttons with a tooltip stating the counting rule.
