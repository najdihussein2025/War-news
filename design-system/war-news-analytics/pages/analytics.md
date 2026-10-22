# Analytics page: overrides on MASTER.md

Rendered by `AnalyticsLayout` (no admin sidebar), under the same role guard as the rest of the panel.
Container `max-w-[1800px]`, gutters `px-4` / `sm:px-6`, a 12-column grid with `gap-4`. No horizontal page scroll
from tablet (768px) up; the root uses `overflow-x-clip` so the sticky bars keep working.

Sizes below use this app's spacing tokens: `h-7` = 32px, `h-8` = 40px, `h-9` = 48px (not Tailwind's defaults).

1. **Top bar** (sticky `top-0`, 56px): `← Dashboard` (`aria-label="Back to dashboard"`), CNRS/NCNE logos (md+),
   title "Analytics"; right side: freshness ("Updated N h ago · N dates queued", warning colour after 15 min),
   Methodology, Export to Excel, user name / role badge / sign out. The page renders its actions into the bar
   through `TopBarActions` (a portal), so the layout stays free of page state.
2. **Filter block** (sticky under the top bar): one row of 40px controls from 1440px (wraps below):
   period presets, war month, from/to dates, level segment, families, metric, air type (breaches only),
   include pending + count. Second row: section tabs (left) and removable active-filter chips plus
   "Reset all" (right); with no chips it states the defaults.
3. **KPI row**: 6 equal-height cards (`auto-rows-fr`, 2 / 3 / 6 columns). Value `text-h3`, delta chip, sparkline,
   one caption line. Casualty methodology lives in an ⓘ popover (hover + keyboard focus); the M/F/children/
   not-stated split is always visible, never hover-only.
4. **Map row**: map 8 columns × 640px (xl), side column 4 columns × 640px. Side column = Top 10 areas for the
   current level and metric (mini bars coloured by most frequent action, action-mix bar pinned at the bottom);
   on area click it becomes the area profile. Overlays sit where Lebanon's bounding box is empty:
   legend top-left (sea), search/zoom/reset bottom-right, play bottom-centre, frame label top-centre.
   Map tab: the same map instance full width, `100dvh − 13rem` tall (600–920px), profile as an overlay.
5. **Timeline** full width, 320px. **Peaks** one row of 6 compact cards below it (worst day/week × incidents,
   deaths, air breaches, top cazas on one line).
6. **Rankings** and **Action × caza** full width, stacked (side by side once rankings show 25 rows).
7. Empty sections show a fixed 80px `EmptyState`, never a tall blank card.

Interaction rules: hover tooltip = name_ar (rtl) over name_en, metric value, top families; click = filter
the page to the area and open the profile; ranking rows and Top 10 rows do the same (keyboard path).
Unsupported air levels are `aria-disabled` buttons with a tooltip stating the counting rule.
