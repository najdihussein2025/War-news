# llm_knowledge CHANGELOG

## Policy

Any fix to an extraction, classification, or matching **accuracy bug**
must add an entry here naming: the real bulletin/example that triggered
it, the rule file(s) changed (with a short excerpt of the new rule), and
the regression test(s) that lock the fix in. A code-only guard (a
Python-side keyword list, gate, or override check) does not close this
class of bug on its own — it only patches the one instance found. Flag
any such code-only fix as incomplete until a corresponding prompt/rule
update or a documented rationale for staying code-only is added.

## 2026-09-24 - Evidence-tiered condition/action reconciliation

**Bug / accuracy gap:** Mansouri Sour raw `1235` (`تمشيط من الاباتشي استهدف
المنصوري`) and Haddatha raw `1233` (`قنابل مضيئة`) were materialized as
generic Bombs because CNRS `event_subtype` overwrote the LLM/text action before
condition matching.

**Rule / knowledge files changed:**
- `rules/condition_action_reconciliation.md` documents that text-grounded
  action evidence is Candidate A and source metadata is only a review-required
  Candidate B fallback.
- `terminology/condition_labels.yaml` adds Apache-sweep wording for Aerial
  Sweep matching; `تمشيط مروحي` / Apache sweep resolves to Aerial Sweep, not
  generic Bombs or the broader Sweeping Operations bucket.

**Regression coverage:**
- `tests/test_cnrs_extraction_fallback.py` verifies CNRS subtype metadata is
  stored as a hint and only fills action text when LLM extraction is empty.
- `tests/test_condition_reconciliation.py` covers confident text evidence,
  source fallback with capped confidence, A/B disagreement review, unclassified
  no-match behavior, and the Mansouri/Haddatha real snippets.

## 2026-09-24 - Illumination bombs prefer Flare Bomb over generic Grenades

**Bug / accuracy gap:** A bulletin with `قنابل مضيئة` displayed as generic
Grenades / `قنابل`, even though the canonical reference table has the more
specific Flare Bomb condition `قنابل مضيئة وحارقة`.

**Rule / knowledge files changed:**
- `terminology/condition_labels.yaml` now maps `قنابل مضيئة` and
  `إلقاء قنابل مضيئة` to `قنابل مضيئة وحارقة`, preventing the generic
  `قنابل` condition from winning.

**Regression coverage:**
- `tests/test_condition_repository.py::test_action_aliases_cover_vehicle_movement_detonation_and_bomb_subtypes`

## 2026-09-24 - Per-village action/condition attribution for multi-action bulletins

**Bug / accuracy gap:** A confirmed CNRS bulletin covering Talloussa and Beit
Yahoun was extracted as one root "Sweeping Operations" action with flat village
roles. Talloussa's own sentence described sweeping, while Beit Yahoun's sentence
described illumination/incendiary shelling, so the Beit Yahoun incident row lost
its actual condition.

**Rule / knowledge files changed:**
- `rules/tier1_multi_village.md` now requires one `sub_events` entry per
  distinct action/condition in multi-village bulletins and includes the
  Talloussa/Beit Yahoun wrong-vs-correct output shape.
- `rules/combined_tier1_prompt.md` now states that root `action_description` is
  only a bulletin-level summary when scoped `sub_events` exist or are required.

**Code backstop:**
- Tier 1 extraction now flags multi-village shortcut responses with
  `review_reason="multi_village_no_subevents"` when village-local action
  language differs but the model emitted no `sub_events`.

**Regression coverage:**
- `tests/test_extraction_service.py::test_extract_tier1_talloussa_beit_yahoun_scopes_actions_to_sub_events`
- `tests/test_extraction_service.py::test_multi_village_multi_action_without_sub_events_needs_review`
- `tests/test_sub_event_splitting.py::test_talloussa_beit_yahoun_materializes_distinct_conditions`

## 2026-09-24 - CNRS conflict-attributed fire action extraction

**Bug / accuracy gap:** Real CNRS fire rows such as raw_message_id=1320
(`drone hostile, dropped incendiary material ... fire started`) could reach
fast-path matching without a condition-matchable action when the extractor left
`action_description` null or overly literal, causing `fast_path: unmatched or
missing condition`.

**Rule / knowledge files changed:**
- `rules/tier1_general_prompt.md` and `rules/combined_tier1_prompt.md` now
  state that CNRS `event_subtype=fire_incident` rows with explicit
  military/security attribution, such as hostile drone incendiary material or
  fire after shelling/airstrike, must emit a condition-matchable Burning
  Properties action. Ordinary civilian/traffic/weather fires remain excluded.

**Regression coverage:**
- `tests/test_cnrs_extraction_fallback.py::test_cnrs_fire_incident_hostile_drone_materials_sets_burning_properties`
- Existing negative coverage:
  `tests/test_cnrs_extraction_fallback.py::test_cnrs_fire_incident_without_conflict_attribution_rejects_override`

## 2026-09-23 - Confirmed no-ACS local place aliases with news-side display names

**Bug / accuracy gap:** The Wadi el-Selouqi -> Touline fix was a one-off. A confirmed ACS reconciliation spreadsheet supplied 28 local/colloquial names with no ACS row of their own, including `وادي راج` -> Zaoutar Ech-Charqiye (ACS 71367), `الدبشة` and `جبل الرفيع` -> Kfar Roummane (ACS 71133), and `بيوت السياد` -> Mansouri Sour (ACS 62296). Without aliases, fuzzy matching could miss, downgrade, or collapse these news-side place names into only the parent ACS village display.

**Rule / knowledge files changed:**
- `terminology/village_aliases.yaml` and `Data/VillageLocationAliases.json` now include all confirmed no-ACS aliases: `البياضة`, `محمية وادي الحجير`, `محرونة`, `بيوت السياد`, `السماعية`, `المعلية`, `المالكية`, `لبونة`, `الناقورة`, `الدبشة`, `جبل الرفيع`, `وادي راج`, `الوزاني`, `وادي الحير`, `وادي إسطبل`, `وادي الجمل`, `خلة الدواوير`, `عريض الماريحيا`, `حوشين`, `خلة الساقية`, `ابو مكنا`, `شانوح`, `الرمثا`, `وادي حسن`, `جبل الوردة`, and `جسر الخردلي`; existing `وادي السلوقي` remains Touline (ACS 73282).
- `terminology/village_match_exceptions.yaml` removed `بيوت السياد` from no-fuzzy exceptions because the ACS parent is now confirmed.
- `rules/village_matching.md` now documents the general pattern: confirmed no-ACS local names resolve to a parent ACS row for geo/matching/dedup, while the incident display preserves the news-side phrase.

**Code / migration wiring:**
- `MatchResultDTO` carries `alias_matched`; `MatchingService` sets it for exact alias hits.
- `incidents.village_display_name` preserves the alias/raw news phrase at materialization time; list/detail/realtime display uses it before falling back to the ACS village label.
- Alembic migration `20260923_0061_confirmed_no_acs_place_aliases.py` adds `incidents.village_display_name` and upserts the confirmed aliases into `village_location_aliases`; generated only, not run.

**Regression coverage:**
- `tests/test_matching_service.py::test_confirmed_no_acs_aliases_override_similarity`
- `tests/test_matching_service.py::test_wadi_selouqi_alias_overrides_baalbek_slouqi_similarity`
- `tests/test_incident_materialization_service.py::test_alias_matched_village_preserves_news_display_name`
- `tests/test_incident_materialization_service.py::test_direct_village_match_keeps_default_display_fallback`
- `tests/eval_corpus/cases/wadi_raj_zaoutar_alias.json`
- `tests/eval_corpus/cases/kfar_roummane_two_local_aliases.json`
- `eval/corpus/village_matching.jsonl`: `bouyout-sayyad-confirmed-alias`

## 2026-09-23 - Non-Lebanon Gaza scope reject + Wadi el-Selouqi Touline alias

**Bugs:** Real production misses from the admin UI:
- Incident `b8d802ad-baa8-40e7-b5f4-8631062d3278` was materialized as Zaoutar Ech-Charqiye / Bombs even though the bulletin text says the firing was toward Beit Lahia, north Gaza Strip: `... مشروع بيت لا.هيا شمال قطاع غز.ة`.
- A recurring bulletin phrase `إلقاء قنابل مضيئة معادية باتجاه وادي السلوقي لجهة طلوسة` matched the unrelated ACS row `Slouqi/Slouky` in Baalbek instead of the intended south-Lebanon parent `تولين` / Touline (ACS 73282).

**Rule / knowledge files changed:**
- `rules/relevance_filter_prompt.md` - added an explicit geographic scope gate requiring the event location to be Lebanon or ambiguous-plausibly Lebanon, plus the Beit Lahia / Gaza negative example.
- `terminology/village_aliases.yaml` and `Data/VillageLocationAliases.json` - added `وادي السلوقي`, `السلوقي`, `وادي سلوقي`, `wadi selouqi`, and `wadi salouqi` as aliases for Touline (ACS 73282).
- `rules/village_matching.md` - documented the Wadi el-Selouqi -> Touline collision guard and the Slouqi/Slouky Baalbek false target.

**Code / migration wiring:**
- `lebanon_scope_filter.py` now includes Gaza obfuscation variants, Beit Lahia, Rafah, Khan Younis, Syria, Iraq, and Yemen markers.
- `match_incident_action.py` short-circuits explicit non-Lebanon raw text to an unmatched match result before `MatchingService` can fuzzy-match a Lebanese village.
- Alembic migration `20260923_0060_add_wadi_selouqi_touline_aliases.py` inserts the Touline aliases into `village_location_aliases`; generated only, not run.

**Regression coverage:**
- `tests/test_trusted_source_bypass.py::test_gaza_beit_lahia_bulletin_overrides_cnrs_include_true`
- `tests/test_matching_service.py::test_action_short_circuits_non_lebanon_raw_text_before_matching`
- `tests/test_matching_service.py::test_wadi_selouqi_alias_overrides_baalbek_slouqi_similarity`
- `tests/eval_corpus/cases/gaza_beit_lahia_scope.json`
- `tests/eval_corpus/cases/wadi_selouqi_touline_alias.json`
- `eval/corpus/relevance_filter.jsonl`: `gaza-beit-lahia-non-lebanon-scope`
- `eval/corpus/village_matching.jsonl`: `wadi-selouqi-touline-alias`

## 2026-09-21 - Curated matching exceptions and district-hint guard

**Bugs:** Real/confirmed matching-layer failures:
- `بيوت السياد` had no confirmed ACS row or alias and could still silently resolve through fuzzy village matching to `المنصوري`.
- `النيران تلتهم سيارة في العباسية... حريق كبير شرق صور` could resolve to condition_id 21 / "Mining & Detonation" despite no conflict attribution.
- A mention with a `قضاء ...` qualifier could bypass the no-reference-overlap village guard because district membership artificially raised a weak lexical candidate above `MATCH_THRESHOLD`.

**Knowledge files added:**
- `terminology/village_match_exceptions.yaml` - `بيوت السياد` as `village_do_not_fuzzy_match` / `needs_review`.
- `terminology/condition_match_exceptions.yaml` - Abbasiyeh car-fire phrasing as `condition_do_not_match_without_attribution` / `needs_review`.

**Matching-code wiring:**
- `matching_service.py` now loads both exception files through `load_terminology()` and short-circuits village exceptions before alias, trigram, or district-hint matching; condition exceptions block effect-defined condition matches in `_condition_match_allowed()`.
- District-hint boosting now requires lexical overlap with the candidate name fields; district membership alone cannot manufacture a confident village match.
- The duplicated conflict marker tuple was consolidated into `app/news/services/matching/conflict_attribution.py`; both `matching_service.py` and `cnrs_extraction_fallback.py` use the shared helper.

**Regression coverage:**
- `tests/test_matching_service.py::test_village_exception_overrides_alias_and_similarity`
- `tests/test_matching_service.py::test_qada_hint_does_not_force_unrelated_candidate_without_name_overlap`
- `tests/test_matching_service.py::test_condition_exception_blocks_even_with_conflict_attribution`
- `eval/corpus/village_matching.jsonl`: `bouyout-sayyad-village-exception` and `district-hint-no-reference-overlap`

**Eval gap:** `llm_knowledge/eval/` still has no dedicated condition-matching corpus file, so the Abbasiyeh condition exception is locked by unit test rather than a corpus row.

## 2026-09-21 — Fuzzy-area "محيط X وY" false multi-village split

**Bug:** بلاغ real bulletin — «القوات الإسرائيلية أحرقت حقول الزيتون
وبساتين الحمضيات في محيط مجدل زون وبيوت السياد بإطلاق قنابل فوسفورية» —
was extracted as two separate target villages/incidents (مجدل زون +
بيوت السياد) instead of one fuzzy-area mention, because the existing
"بين X وY" two-endpoint rule didn't distinguish a real road/route from a
vague "vicinity of X and Y" phrase.

**Rule files changed:**
- `rules/tier1_general_prompt.md` — narrowed the route rule to require an
  explicit path marker (`طريق بين X و Y`, not bare `بين X و Y`), and added:
  *"عبارات المساحة التقريبية «في محيط X وY» ... من دون طريق أو مسار صريح
  تصف موقعاً ضبابياً واحداً، وليست حادثين أو هدفين. احتفظ بأول بلدة
  مذكورة فقط ... وضعها في حالة مراجعة منخفضة الثقة."*
- `rules/tier1_multi_village.md` — added a "Fuzzy area references are one
  location, not a village list" detection signal + worked example for
  `محيط`/`قرب`/`بالقرب من`/plain `بين` without a named route.

**Code guard:** `matching_service.py::match()` now reads
`extraction_result.location_ambiguity` and forces all village matches to
`matched_low_confidence` + `village_review_required=True` when set, and
`MatchResultDTO` carries `location_ambiguity_evidence`/
`location_alternatives` through to materialization.

**Regression tests:**
- `tests/test_extraction_service.py::test_fuzzy_area_phrase_collapses_to_first_village_with_alternate`
- `tests/test_extraction_service.py::test_plain_between_phrase_collapses_without_route`
- `tests/test_matching_service.py::test_fuzzy_area_village_is_one_low_confidence_match`
- `tests/test_village_role_materialization.py::test_fuzzy_area_materializes_one_reviewable_incident_with_alternate_note`

## 2026-09-21 — CNRS "Burning Properties" over-classification without war attribution

**Bug:** CNRS fallback extraction was materializing plain civilian/traffic
fires as war incidents ("Burning Properties") with no stated military
cause. Real false positives: «احتراق سيارة عند جسر المدفون ... اندلع
حريق بسيارة», «احتراق سيارة على أوتوستراد المدفون باتجاه بيروت», «حريق
داخل منزل في البحصة – طرابلس».

**Code guard (committed e682d3a):** `app/llm/services/cnrs_extraction_fallback.py`
adds `has_conflict_attribution()` and requires it for `event_subtype ==
"fire_incident"` before `trusted_cnrs_action()` returns "Burning
Properties" — checks `mentions_israeli_actor`/`event_domain == "conflict"`
metadata or an explicit conflict-action marker (قصف، غارة، مسيّرة، دبابة،
فوسفور...) in the post text.

**Prompt-level status:** this fix is currently **code-only** — there is
no corresponding Tier 1/Tier 2 prompt rule stating the war-attribution
requirement for fire/property-damage actions. `rules/tier1_general_prompt.md`
does carry an adjacent, independently-added rule ("الأفعال المعرّفة
بالأثر تحتاج إسناداً صريحاً للنزاع...") covering حريق/قطع طريق/قطع أشجار/
حفر وجرف/إطلاق نار/قذائف لم تنفجر for the *general extraction* stage, but
no changelog entry previously linked it to this incident. Logged here to
close the gap and connect the two fixes.

**Regression tests:**
- `tests/test_cnrs_extraction_fallback.py::test_cnrs_fire_incident_without_conflict_attribution_rejects_override`
- `tests/test_cnrs_extraction_fallback.py::test_cnrs_fire_incident_with_conflict_attribution_accepts_override`

## Open gaps (logged, not fixed)

Found while cross-checking `rules/` against code-side accuracy guards —
candidates for a future documentation pass, not fixed in this entry:

- Closed 2026-09-21: duplicated conflict-attribution token lists were consolidated into `app/news/services/matching/conflict_attribution.py`; `matching_service.py` and `cnrs_extraction_fallback.py` now share the same helper.
- `CONDITION_DISTINGUISHING_TOKENS` (`تحذيريه` for Warning Raid, `وهميه`
  for Feigned Attacks) — numeric IDs are intentionally code-only per the
  2026-09-14 B.3 decision below, but there's no eval-corpus entry
  exercising the *false-negative* case (a warning/feigned raid missing
  its distinguishing token and falling through to no match).

## 2026-09-14 — B.3 confirm air-violation / special condition IDs

**Decision (reconfirmed):** condition IDs `2`, `35`, `36`, `38`, `39`, `45` remain Python/SQL constants for deterministic routing, distinguishing-token gates, fast-path exclusion, and unclassified fallback. They must not move into PromptBuilder as authoritative IDs.

**Prompt gap closed:** added `condition_id_label` rows in `terminology/condition_labels.yaml` with Arabic surface forms + documented `condition_id=N` notes for LLM explanation only. Wired `condition_labels.yaml` into `tier1_extraction` index terminology.

## 2026-09-14 — B.2 expand terminology coverage

| Change | Reason |
|--------|--------|
| `casualty_gender.yaml`: occupation×status compounds + جندية/اطفائية/مسعفة | Document unambiguous role×death patterns for prompts; flag مدني/طفل as ambiguous |
| `org_types.yaml`: sharpen الرسالة vs الهيئة الصحية notes | Confirm two distinct orgs (scout_paramedic vs health_organization), not merged |
| `revision_language_markers.yaml`: تنعي/الشهيده + مراجعة/تصحيح الحصيلة | Orthography used by backstop regex + common revision phrasing from audits |
| `role_terms.yaml`: مسيرة/مسيّرة/طيران حربي/مروحية | Air-platform nouns from real bulletin text for prompt glossary |

## 2026-09-14 — B.1 eval corpus from historical bugs

| Corpus file | Entries (approx) | Coverage |
|-------------|------------------|----------|
| `tier1_extraction.jsonl` | 11 | vague quantifiers, gender/occupation, transitions |
| `casualty_scope.jsonl` | 6 | multi-village misattribution, null-not-shared, merge-before-max-wins |
| `village_matching.jsonl` | 9 | maslakh/nabatieh/qantara/aynata/kafra + ambiguous negatives |
| `revision_detection.jsonl` | 5 (new) | preliminary toll, named victim, rising toll markers |

Tagged `source: real_bug` with `bug_ref` for each historical accuracy class named in the enrichment prompt.

## 2026-09-14 — Completeness audit A.2 stragglers

| Fragment | Destination | Status |
|----------|-------------|--------|
| Tier 2 category detail prompts | `rules/tier2_*_prompt.md` + PromptBuilder | migrated |
| Relevance classification prompt | `rules/relevance_filter_prompt.md` + PromptBuilder | migrated |
| Presence heuristic literals (road/escort/hospital) | `terminology/role_terms.yaml` | migrated |
| CNRS motorcycle/tank markers | load from `role_terms.yaml` | migrated |
| Dash-route `_ROUTE_AREA_PREFIXES` | load from `role_terms.yaml` | migrated |
| Import ACS aliases كفره/شعث/النبطيه | `terminology/village_aliases.yaml` | migrated |


Resolved all 8 recon "needs clarification" items in
`Docs/recon/llm_knowledge_migration_recon.md`. Summary: category_mapper
keywords, numeric condition IDs, boilerplate strip, Red Alert OCR aliases,
and evidence-override control flow stay **code-only**; Arabic labels/phrases
migrate; uncertain aliases → eval negatives; legacy extraction_instruction.txt
stays scripts-only until harness update.

## 2026-09-14 — Batch 3.1 pure terminology

| Fragment source | New location | Status |
|-----------------|--------------|--------|
| Full `_EXPLICIT_FORMS` + duals + plurals + count words | `terminology/casualty_gender.yaml` | completed |
| Full `_MALE_ROLE_NOUNS` / `_FEMALE_ROLE_NOUNS` | `terminology/casualty_gender.yaml` | completed |
| All revision + transition labels | `terminology/revision_language_markers.yaml` | completed |
| Named orgs from EmergencyOrganizations.json | `terminology/org_types.yaml` | completed (prior expand) |
| `load_terminology` / `terms_by_category` / `terms_by_meaning` API | `loader.py` | added for 3.4/3.5 wiring |

## 2026-09-14 — Batch 3.2 Tier 1 prompt + fewshot

| Fragment source | New location | Status |
|-----------------|--------------|--------|
| Inline `GENERAL_EXTRACTION_PROMPT` | `rules/tier1_general_prompt.md` | migrated verbatim |
| `combined_tier1_presence_extraction_instruction.txt` | `rules/combined_tier1_prompt.md` | migrated verbatim |
| `build_stage_system_prompt()` | `prompt_assembly.py` | wired |
| `ollama_extraction_service` Tier 1 + combined calls | uses `PromptBuilder` via prompt_assembly | wired |
| Prompt few-shot examples | `fewshot/scope_examples.jsonl` | expanded |

## 2026-09-14 — Batch 3.3 matching aliases

| Fragment source | New location | Status |
|-----------------|--------------|--------|
| `CONDITION_ALIASES` phrases | `terminology/condition_labels.yaml` | migrated; `condition_aliases.py` loads YAML |
| Distinguishing tokens `تحذيريه`/`وهميه` | `terminology/condition_labels.yaml` | migrated; IDs stay in `matching_service` |
| Air keyword Arabic phrases | `terminology/condition_labels.yaml` | migrated; IDs + OCR typos stay in Red Alert |
| `PROPOSED_VILLAGE_LOCATION_ALIASES` | `terminology/village_aliases.yaml` | migrated; `village_aliases.py` loads YAML |
| Uncertain alias notes | `eval/corpus/village_matching.jsonl` negatives | documented |

## 2026-09-14 — Batch 3.4 presence gate

| Fragment source | New location | Status |
|-----------------|--------------|--------|
| `MUNICIPAL_*` / `VILLAGE_*` / `TARGETING_*` / `VEHICLE_*` | `terminology/role_terms.yaml` | migrated |
| `CIVIL_DEFENSE_ORG_TERMS` | `terminology/org_types.yaml` | migrated |
| Proximity / negative / direct impact term lists | `terminology/role_terms.yaml` | migrated |
| `presence_gate_instruction.txt` | `rules/presence_gate_prompt.md` | migrated |
| `_is_context_only_evidence` branching | stays in Python | code-logic (Phase 2.5) |
| Presence chat system prompt | `build_stage_system_prompt("presence_gate")` | wired |

## 2026-09-14 — Batch 3.5 backstop terminology

| Fragment | Classification | Action |
|----------|----------------|--------|
| Explicit gender term lists | knowledge | load from `casualty_gender.yaml` |
| Role noun lists | knowledge | load from YAML |
| `_standalone` / cover-total / apply_* | code-logic | unchanged behavior, uses loaded terms |
| Transition regex patterns | code-logic | kept in Python |
| Transition labels | knowledge | mirrored in YAML; `keyword_labels()` prefers YAML |
| Revision regex patterns | code-logic | kept in Python |
| Revision labels | knowledge | mirrored in YAML |
| `casualty_count_backstop` count words | knowledge | load from YAML |

## 2026-09-14 — Phase 2 architecture (additive seed)

Initial structure under `app/core/llm_knowledge/`. See earlier commits.
## 2026-09-21 - Burning Properties relevance guard

Added explicit LLM knowledge that ordinary civilian fires, car fires, traffic accidents, electrical faults, and property fires are not war-news incidents and must not map to `Burning Properties` unless the text explicitly ties the damage to Israeli, military, or security action.

Updated:
- `rules/relevance_filter_prompt.md`
- `rules/tier1_general_prompt.md`
- `rules/combined_tier1_prompt.md`
- `rules/tier1_core.md`
- `terminology/condition_labels.yaml`
