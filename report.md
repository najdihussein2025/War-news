# Incident Verification Reason UI Report

## Phase 0 Recon

1. The Incident records table is rendered in `frontend/src/features/news/pages/IncidentsPage.tsx`. It uses the shared `DataTable` primitive from `frontend/src/components/ui/DataTable.tsx`. In verification grouped mode, `groupColumns` renders the bulletin cell, incidents cell, and event cell; the `DataTable` `actions` prop renders Verify all / Reject all / Open.
2. Inline verification reason text was rendered in the grouped bulletin cell from `group.verification_reasons[0]`, and in the non-grouped verification column from `row.verification_reason`. Frontend shape is free text: `Incident.verification_reason: string | null`; grouped bulletins expose `verification_reasons: string[]`.
3. The frontend API types and hooks do not expose structured reason signals. `getIncidents()` and `getIncidentById()` return the free-text fields above through `useIncidentsQuery()` and `useIncidentQuery()`. No frontend mock hook for this page was present under `frontend/src/mocks/`.
4. Open navigates to `roleBase/incidents/:id` and renders `IncidentDetailPage.tsx`, not a drawer or modal. The page already showed header status, duplicate review, village details, report, casualty demographics, related incidents, bulletin-wide toll, record information, and category details.
5. The grouped "Duplicate?" tag next to `Raw #...` is derived from `group.verification_types.includes("duplicate")`.
6. Reusable primitives found: `StatusBadge`, `DataTable`, `Dialog`, `ConfirmDialog`, `EmptyState`, `Select`, `Input`, `Label`, and `Button`. No existing tooltip/popover/accordion primitive was found; existing native `details` is used elsewhere.
7. Existing related frontend tests covered verification filter logic, opened version locking, incident category rendering, edit helpers, stream filtering, and village match notices. No existing test directly covered the Incident records table row or incident detail review reason section.

## Implemented

- Added `frontend/src/features/news/verificationReasons.tsx` with `summarizeVerificationReasons()`, `summarizeManyVerificationReasons()`, `ReasonChips`, `WhyNeedsReviewSection`, and a small incident flag helper.
- Replaced full inline reason paragraphs with deduped warning chips. The grouped bulletin text is clamped to two lines and rendered RTL.
- Added max two visible reason chips plus a `+N` chip whose `title` and `aria-label` list the remaining labels.
- Collapsed grouped incident cards to the first three by default, with a real `button` and `aria-expanded` to show/hide the rest.
- Added a small warning dot to incident cards that have verification state/reason/open flags.
- Added "Why this needs review" near the top of `IncidentDetailPage.tsx`, with the full Arabic bulletin text, deduped plain-language review lines, duplicate links when an id can be parsed from the free text, and a collapsed raw reason disclosure.
- Updated tests in `frontend/src/features/news/verificationReasons.test.tsx` for summarizer behavior, chip compaction, and detail-section dedupe.
- Updated a stale `VillageMatchNotice` assertion to match the current component copy.

## Verification

- `docker compose -f docker-compose.yml -f docker-compose.dev.yml exec frontend npm run typecheck` passed.
- `docker compose -f docker-compose.yml -f docker-compose.dev.yml exec frontend npm run test` passed: 17 files, 79 tests.
- After the user reported no visible change on `http://localhost:5173`, the edited `frontend/src` was synced into `war-news-frontend-1`, the container serving port 5173. `docker compose exec frontend npm run typecheck` and `docker compose exec frontend npm run test` both passed there too: 17 files, 79 tests.
- There is no `lint` script in `frontend/package.json`, so lint could not be run separately.

## Notes

- No backend, migration, or reason-generation code was changed.
- Because the API currently exposes only free-text reason fields, grouping in the detail page is based on the opened incident's reason text. A true all-incidents bulletin detail view would need structured per-incident reason data or an endpoint that returns every grouped incident with its reasons.
