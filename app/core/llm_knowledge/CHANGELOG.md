# llm_knowledge CHANGELOG

## 2026-10-05 - Wadi fuzzy village guard and verification reason cleanup

`Wadi ...` place mentions no longer confidently resolve through fuzzy matching
to an unrelated ACS village whose name also starts with `Wadi`. They must resolve
by exact/compact name or an explicit location alias; otherwise the match is kept
low-confidence for data-quality review. This prevents Wadi el-Houjeir text from
materializing as Ouadi Ed-Deir when the alias path is stale or missing.

Verification recompute also stops preserving legacy cross-source duplicate
reason text below the configured duplicate review threshold. Human-facing
`verification_reason` is now one short review sentence; additional review data
and developer quality flags are stored structurally in `incidents.quality_flags`.## 2026-10-05 — Village phrase normalization and geo-context audit

Tier 1 guidance now asks for cleaner village strings for descriptor prefixes
(`خراج`, `أطراف`, `محيط`, `بلدة`, `مدينة`, `قرية`, `سهل`, `تلة`, `أحراج`),
city-after-dash neighborhoods such as `حي X - النبطية`, and resolvable village
pairs such as `حداثا وحاريص` or `بين القنطرة ودير سريان`. The matcher records
`normalized_from` when it strips descriptor context and records geo-context
resolution distance/anchor when a nearby village disambiguates a collision.

Real examples from the Phase 2 village backlog: `وادي السلوكي-القنطرة` and
`بين القنطرة ودير سريان` should be split/cleaned before matching; `خراج X` and
`أطراف X` should preserve the raw phrase as audit context while matching `X`.

## 2026-10-05 — Drone condition resolution is context-aware

Bare `مسيرة` / `طيران مسير` is no longer an exact alias for `Surveillance
Aircraft`. Drone wording now resolves only when the same action/evidence span
contains context: strike wording maps to `Bombs`, explosive wording maps to
`Suicide Drone`, crash wording maps to `Drone Failure`, and presence-only
wording maps to `Surveillance Aircraft`.

Real database example from the Phase 1 scoring check: `مسيرة` had resolved to
`Surveillance Aircraft` at 1.000 even though a strike bulletin would then be
stored as surveillance. Regression coverage is in
`test_condition_evidence_override.py`.

## 2026-10-05 — Generic attack aliases and informational condition confidence

Generic Arabic attack terms now resolve exactly to `Bombs`, while specific
artillery and flare phrases retain their specific conditions. Bare drone
wording cannot fuzzy-match Drone Failure or Suicide Drone without crash or
explosive evidence; drone-strike phrases resolve to Bombs. Low-confidence
condition matches are informational when the village is confident, while a
truly unresolved condition remains review-required. Regression coverage is in
`test_condition_phase1_rules.py`.

## 2026-10-05 — Casualty review follows unresolved casualty decisions

Casualty-scope validation no longer sends zero-casualty incidents to manual
review. Review is limited to casualty wording without an exact number and a
positive aggregate toll across two or more targets without a per-location
breakdown. Exact single-location and per-village figures are automatic.
Category casualty fields remain suppressed in multi-target bulletins, but the
suppression flags review only when it removed a positive casualty count.

Real database example: raw message `38286` was labeled unsupported aggregate
while most sibling rows had no casualty toll; only its genuinely unallocated
positive toll requires a casualty decision. Tests in
`test_casualty_verification_rules.py` cover zero casualties, exact single
village, aggregate single target, aggregate multi-target, vague wording, and
positive-versus-zero category suppression.

## 2026-10-01 — Air violations: presence-only routing and deterministic regressions

**1. Kinetic/casualty/damage exclusion and post-model reroute.**
The rule now sends strikes, attacks, casualties, and damage to incidents even
when the model selected an air condition. Real regression: «نجاة فريق إسعاف من
غارة نفذتها مروحية أباتشي إسرائيلية ... ميفدون - شوكين». Tests:
`test_air_violation_eligibility.py` and
`test_post_llm_air_result_is_rematched_to_incident`.

**2. Drone is never helicopter.**
طيران مسير/مسيّر/مسيرة/درون is a drone; plain overflight is Surveillance
Aircraft. Helicopter Hovering requires a helicopter noun plus a hover/flight
verb. Real regression: «الطيران المسيّر الاسرائيلي استهدف مدينة النبطية» is a
drone-strike incident. Tests: `test_every_drone_variant_is_surveillance`,
`test_helicopter_requires_and_accepts_flight_language`, and
`test_apache_strike_is_never_helicopter_hovering`.

**3. April-based war month.**
Air-violation API and workbook Month now use the shared numeric war-month
formula. Tests cover all twelve calendar months, the December/January boundary,
and numeric workbook export in `test_air_violation_war_month.py`.

**4. Village identity in surveillance windows.**
Window villages are unique by village ID, keep the earliest report spelling,
and unresolved normalized names cannot collapse with resolved IDs. Tests:
`test_same_village_id_with_different_spellings_appears_once`,
`test_different_ids_with_same_display_name_remain_distinct`, and
`test_window_metadata_dedupes_village_by_id_not_spelling`.

**5. Hashtag-only alerts are not empty text.**
Stripping hashtags protects against trailing tag lists («#الشهيد») being read as
an event, but a Red Alert post is nothing but hashtags, so stripping left no
text and every such alert was rerouted to incidents as `empty_text`. Real
regression: «#مقاتلات_حربية #الجنوب». The tags are now unwrapped and kept as the
content whenever removing them would leave nothing. Tests:
`test_hashtag_only_alert_keeps_its_tags_as_content`,
`test_hashtag_only_alert_still_rejects_kinetic_tags`, and the Red Alert routing
tests for caza-only, south-region and Lebanon-region alerts.

**6. Recon phrases still reach Surveillance Aircraft.**
Routing drone words through their own context-gated branch accidentally skipped
condition 36 in the keyword table, so the recon phrases «طيران استطلاعي» and
«طائرة استطلاع» classified as nothing at all. Real regression: «طائرة استطلاع
فوق صور» → 36. Only Helicopter (38) is now skipped in that table, since hover
language decides it earlier; bare drone words stay context-gated, and the
unambiguous tokens (درون, drone, uav, مسير) match on whole words so the feminine
«مسيرة» (also "march") keeps needing context. Tests:
`test_classifies_supported_air_violation_actions`,
`test_source_enrichment_fills_only_missing_dates_and_times`.

**8. Only a kinetic report is an incident.**
Rejecting a row said nothing about where it should go, so end-of-day digests,
channel housekeeping posts and bare hashtags were all headed for the incident
pipeline. `EligibilityResult.belongs_in_incidents` now marks the one exclusion
that means "a real event happened": strike, casualty or damage. Everything else
goes to a human. Real regressions: «إحصاءات نهاية اليوم ... غارات جوية: ٧»
(a digest) and «كل من ارسل بلاغا عن طائرة مسيرة، او حربي، او غارة» (the
channel's thank-you post listing what people may report). Tests:
`test_non_event_notices_are_not_incidents`,
`test_a_real_strike_still_belongs_in_incidents`.

**9. A bare hashtag is a label, not a casualty.**
Keeping tags as content when stripping them would leave nothing meant a post of
only «#الشهيد» read as a casualty report. Hashtag-only text that trips a kinetic
term now returns `excluded_hashtag_only_ambiguous`, which never reaches
incidents, and the reroute no longer infers an incident action from it. Tests:
`test_bare_tags_are_never_read_as_an_incident`.

**10. Place names that merely contain a strike word.**
Terms match as substrings so Arabic inflections all count, which made
«نهر المغارة» (a river) look like a «غارة». Real regression: air violation 1394,
a Red Alert drone map, was being moved to incidents on that one word. Tests:
`test_place_names_that_merely_contain_a_strike_word_are_not_strikes`,
`test_a_real_strike_near_that_place_is_still_a_strike`.

**7. Khabar import no longer rejects rows that have no source link.**
The enrichment-text screen ran even when enrichment returned no text, so every
row without a link failed as `empty_text`. The screen now runs only when there
is enrichment text. Tests: `test_air_violation_khabar_import.py`.

## 2026-09-30 — Village verification flags: general matching rules (Phase 2)

Recon: `Docs/recon/village-verification.md`. 354 live incidents carried the
"Low-confidence village match" flag in 2026-08-20..09-30; 170 were already
resolved by the current matcher (flags never recomputed) and the rest came from
the causes below. Each fix is a general rule, not a per-village alias.

**1. Definite-article fold (`village_match_key`).**
Example: `الرمادية` scored 0.45 against `رمادية` (14 incidents); `الحنية` scored
0.40 against `حنية` (5); `عرب الصاليم` vs `عرب صاليم` (3). The key drops a
leading `ال` on every word of both the mention and the reference names; scoring
takes the max over the plain, compact and key forms. Seven reference pairs
collide under the key (`القنطرة`/`قنطرة`, `الرمانة`/`رمانة`, `الخريبة`/`خريبة`,
...); they are not merged, and a plain-exact match wins the ordering.
Tests: `tests/test_village_match_key.py`,
`test_definite_article_variant_is_a_normalized_match`.

**2. Generic location descriptors** (`terminology/village_descriptors.yaml`).
Example: `أطراف ميفدون`, `مرتفعات حلتا`, `أطراف طلوسة`. A leading descriptor is
stripped only when the remaining name resolves better; `مدينة الصناعية` keeps
matching as written. Tests: `test_leading_descriptor_is_stripped_and_raw_mention_is_kept`,
`test_descriptor_before_an_ambiguous_name_stays_flagged`,
`test_real_name_that_starts_with_a_descriptor_still_matches_as_written`.

**3. Flag decision rule.** A village is low confidence only when there is no
candidate, the best score is under 0.5 (`VILLAGE_CONFIDENT_FLOOR`), or it is
within 0.05 (`MATCH_TIE_MARGIN`) of a second distinct place, at every score
level. A mention equal to exactly one reference name wins over longer names that
contain it (`صور`, `بعلبك`, `جنين`); a region-suffixed twin (`عرمون` next to
`عرمون كسروان`, `زبدين` next to `زبدين النبطية`) and two villages with the same
name (`الطيبة`) stay reviewable, and an exact winner can still be overridden by a
nearby geo anchor (`القصير`, raw 10395). Each match now stores
`village_match_method` and, for accepted matches under 0.6, a soft
`village_match_note`. Tests: `test_tie_between_distinct_villages_is_flagged_even_below_old_threshold`,
`test_clear_best_match_below_old_threshold_is_accepted_with_a_note`,
`test_exact_name_wins_over_longer_names_that_contain_it`,
`test_two_villages_with_the_same_exact_name_stay_flagged`,
`test_parent_and_child_names_are_not_a_tie`.

**4. Multi-village bulletins.** `location_ambiguity` downgrades only the
villages named in the ambiguity evidence or alternatives (all of them when the
extraction does not say which). Example: «محيط مجدل زون وبيوت السياد» marks
`مجدل زون` and leaves a sibling village confident. Tests:
`test_location_ambiguity_downgrades_only_the_named_village`,
`test_location_ambiguity_without_a_locatable_village_downgrades_all`. The
per-incident review signal is scoped to the incident's own village in
`verification_signals.py` (covered by `tests/test_village_verification_scoping.py`).

**5. Tie resolution from bulletin context.** No new rule: the existing distance
based geo-context path works (15 mentions in the flagged bulletins) and now
records `village_match_method = "geo_context"`. Ties without an anchor, or where
no candidate is clearly closer (`الفوقا`: two candidates in the same district),
stay flagged. Test: `test_geo_context_resolution_records_the_geo_context_method`.

**6. Foreign places and lexical overlap** (`terminology/non_lebanese_places.yaml`).
Example: `الناصرة` scored 0.42 against `الناقورة` and `خان يونس` 0.38 against
`بيت يونس`. A mention equal to a listed foreign place, with no exact Lebanese
homonym, is now "no candidate". The overlap guard needs a shared whole word on
the match key, not shared letters (`مرج` is not `مرجعيون`). Tests:
`test_known_foreign_place_is_not_matched_to_a_lebanese_village`,
`test_foreign_place_name_with_an_exact_lebanese_homonym_still_matches`,
`test_shared_letters_do_not_count_as_lexical_overlap`.

**7. Extraction rule: verbatim village names.** `rules/tier1_general_prompt.md`,
`rules/tier1_event_prompt.md` and `rules/combined_tier1_prompt.md` now require the
model to copy village names exactly as written in the source, in the source's
script, and never translate, transliterate, correct or guess. Real failure: raw
messages 37597 and 37706, «استهدفت أطراف بلدتي حداثا وحاريص», returned
`village=["Harir"]` (37591: `["Harires"]`). Expected `["حداثا","حاريص"]`. Names the
matcher cannot resolve are flagged by matching, not by the extraction. The
extraction prompt has no unit test; the matching-side regression tests above
cover the behaviour that depends on it, and the re-extraction effect must be
checked on the next live sample.

## 2026-09-30 — Fix Red Alert Latin alias matching on multi-village crops

**Bug:** Since `29426c2` (2026-09-29), Latin OCR aliases were matched with a
word-boundary regex against `normalize_latin_location_token`, which strips all
spaces. A red-zone crop such as `Qaraoun Machghara Sohmor Ain El Tineh Libbaya`
became one run-on string, so no alias matched. Since `c3d39ac` red-zone
matching is alias-only, so such alerts were rejected with "Location could not
be identified reliably from the alert image". The short-alias guard also
tested for a space that could no longer exist.

**Fix:** `app/sources/services/red_alert_collector.py` now splits Latin text
into normalized words before stripping, and an alias matches only a run of
whole candidate words (spacing differences such as `Kfarkila`/`kfar kila` still
match; an alias never matches inside a longer word). Aliases under 5 letters
must match word for word. Arabic matching and the alias-only red-zone rule are
unchanged.

**Regression tests:** `tests/test_red_alert_collector.py` covers the
multi-village crop, substring rejection, and whole-word short aliases.
Alerts rejected between 2026-09-29 and this fix are not reprocessed here.

## 2026-09-30 — Remove CodeCraft relevance backend

Relevance classification is local-only (`local_llm` or `cnrs_provided`). The
external CodeCraft classifier, its `CODECRAFT_*` settings and the
local-vs-codecraft comparison script were removed. `RELEVANCE_CLASSIFIER_BACKEND=codecraft`
now fails at startup with a clear error.

## 2026-09-30 — Require event-bearing Tier 1 sub-event evidence

**Bug / accuracy gap:** Real daily-summary extractions for duplicate matches #8099
and #7933 emitted bare sub-event evidence (`وادي الحجير` and `قصف`). The
deterministic segment-review scorer then treated those fragments as standalone
event descriptions and assigned 1.00 containment similarity to unrelated
reports.

**Rule files changed:** `rules/tier1_general_prompt.md`,
`rules/combined_tier1_prompt.md`, and `rules/tier1_multi_village.md` now require
each sub-event `evidence_span` to be a complete phrase connecting action and
location, never a generic action token or bare place name.

**Regression tests:** `tests/test_segment_review_dedup.py` covers the real
#7763, #8099, and #7933 shapes plus a genuine cross-source positive control;
`tests/test_llm_knowledge_rule_integrity.py` continues to validate rule text.

## Policy

Any fix to an extraction, classification, or matching **accuracy bug**
must add an entry here naming: the real bulletin/example that triggered
it, the rule file(s) changed (with a short excerpt of the new rule), and
the regression test(s) that lock the fix in. A code-only guard (a
Python-side keyword list, gate, or override check) does not close this
class of bug on its own — it only patches the one instance found. Flag
any such code-only fix as incomplete until a corresponding prompt/rule
update or a documented rationale for staying code-only is added.

## 2026-09-28 - Test triage: dead branch in the CNRS fire-attribution override

**Bug / accuracy gap** (test triage, baseline failure `test_eval_corpus_case[burning-properties-tp-conflict]`
plus `test_cnrs_fire_incident_with_conflict_attribution_accepts_override` /
`..._hostile_drone_materials_sets_burning_properties`):
`trusted_cnrs_action` gated on `verdict_from_cnrs_classification` before its
own `fire_incident` branch could run. Since `39f79d5f` (2026-09-21) that
verdict function rejects any `event_domain=fire` classification unless the
CNRS `mentions_israeli_actor` flag is set — it never reads the post text. So
"اندلاع حريق في منزل في عيتا الشعب إثر قصف مدفعي إسرائيلي" (fire from Israeli
artillery shelling; CNRS flag false, text explicit) and "درون معادية القت
مواد حارقة" (hostile drone dropped incendiary materials) were rejected before
`has_conflict_attribution`'s own text check ever ran, making that branch dead
for every fire attributed only in the source text.

**Rule / knowledge files changed:** none. This is a control-flow bug in the
deterministic CNRS override (`cnrs_extraction_fallback.py`), not a model
prompt or terminology gap; `has_conflict_attribution` (text + flag) already
encodes the correct rule and needed no change.

**Code paths fixed:** `trusted_cnrs_action` now branches on `has_conflict_attribution`
for `fire_incident` instead of the blanket domain-based verdict gate; every
other subtype is unaffected.

**Regression tests (already existed, now pass for the right reason):**
`tests/eval_corpus/cases/burning_properties_tp_conflict.json`,
`tests/test_cnrs_extraction_fallback.py::test_cnrs_fire_incident_with_conflict_attribution_accepts_override`,
`tests/test_cnrs_extraction_fallback.py::test_cnrs_fire_incident_hostile_drone_materials_sets_burning_properties`,
`tests/test_cnrs_extraction_fallback.py::test_cnrs_fire_incident_without_conflict_attribution_rejects_override` (still passes, confirms no regression on the false-positive side).

## 2026-09-28 - Lost incidents: dead alias keys, unmatched places parked in error, un-retried disconnects

**Bug / accuracy gap** (read-only recon of the 1,875 `status=error` messages):
- 13 of 49 `village_location_aliases` rows (all from migration 0061) stored
  `alias_normalized` verbatim, e.g. «الدبشة» instead of «الدبشه», so exact
  alias lookup never hit. «الدبشة» alone left 29 errored messages
  (e.g. 28838, 28898, 29109: «غارات استهدفت … محيط الدبشة»).
- A usable extraction whose only target place was missing from the gazetteer
  went to terminal `error` ("no materializable village match"), e.g. 29077
  «قصف مدفعي يستهدف وادي الحجير لجهة بلدة الغندورية». Nobody could see or re-run it.
- 11 messages failed with httpx `RemoteProtocolError` stored as «Server
  disconnected without sending a response.»; no transient marker matched, so
  the extraction retry reset never picked them up.

**Rule / knowledge files changed:** none. Rationale for staying code-only:
none of the three is model behavior. The alias key is a lookup/data bug
(fixed at read time plus `scripts/fixes/out/proposed_village_aliases.sql`),
the hold is a pipeline status policy, and the retry marker classifies a
transport error. The LLM-side gaps found in the same recon (English
transliterations such as «Tbaineen»/«Tabbin» for تبنين, truncations such as
«شقا» for شقرا, and villages dropped entirely, e.g. 31548 «رئيس بلدية كفررمان…
ارتقاء 11 شهيداً») are NOT fixed here and remain open for a Tier 1 prompt change.

**Code paths fixed:**
- `village_repository.py`: `resolve_alias` / `find_geo_conditional_aliases`
  also compare `normalize_arabic_sql(alias_text)` to the normalized mention.
- `fast_path_eligibility.py`: `HELD_UNMATCHED_PLACE` + `terminal_status_for_reason`;
  a named-but-unresolved target place maps to `held_for_review` in both the
  per-message path and the bulk terminalize SQL (live sweep uses the same map).
- `transient_llm_errors.py`: «server disconnected» / `RemoteProtocolError`
  are transient.

**Regression tests:** `tests/test_village_location_aliases.py::test_resolve_alias_also_matches_alias_text_normalized_at_read_time`,
`tests/test_fast_path_eligibility.py::test_unmatched_named_place_is_held_not_errored`
(+ origin-only, status map, bulk SQL), `tests/test_transient_llm_errors.py`
(disconnect cases), `tests/test_incident_materialization_service.py::test_unmatched_village_or_condition_is_skipped` (updated expectation).

## 2026-09-28 - Casualty data foundations: dual/singular words, strike lists, vague phrases, zeros

**Bug / accuracy gap** (read-only recon `Docs/recon/casualty_verification_recon.md`):
- Dual/singular words missed: only 16 of 32 messages with a dual death form
  were extracted as 2. Msg 31539 «وزارة الصحة اللبنانية: شهيدان في غارة
  إسرائيلية استهدفت دراجة نارية في بلدة كفررمان» and 30335 «شهيدان جراء غارة
  معادية على دراجة نارية في كفررمان» → all counts null.
- Strike counts read as deaths: msg 32708 «عمليات التفجير : • حولا (٢)» → deaths=2.
- Vague phrases read as numbers: 30496 «وقوع إصابات في غارة كفررمان» →
  injuries=1; 31816 «عشرات الجرحى، بينهم أطفال ونساء» → injuries=10,
  children=6; 31315 «… ووقوع إصابات» → injuries=0.
- The count backstop kept a value when its digit appeared anywhere in the
  text (dates, clock times, links), and every stored 0 was an extraction error.
- `casualty_gender.yaml` listed «مصابين» as both dual and plural.

**Rule / knowledge files changed:**
- `rules/tier1_general_prompt.md` (live Tier 1) and `rules/combined_tier1_prompt.md`
  (flagged-off path, kept in sync): «شهيد/جريح = 1، شهيدان/جريحان/مصابان = 2؛
  مصابين جمع»; «الرقم بين قوسين بعد اسم بلدة في قائمة غارات أو قصف أو تفجيرات
  هو عدد الغارات لا عدد الضحايا»; «وقوع إصابات / سقوط ضحايا / عدد من الجرحى →
  null، لا 1 ولا 0»; «اكتب 0 فقط مع نفي صريح (دون تسجيل إصابات)».
- `rules/tier1_multi_village.md` rule 4: per-village dual/singular example
  («النبطية الفوقا: شهيدان وجريحان» → 2/2) and the strike-list rule.
- `terminology/casualty_gender.yaml`: «مصابين» is plural only (removed from
  `male_injury_dual`).
- New `terminology/casualty_wording.yaml` (code-only, not in `index.yaml`):
  page header «صفحة الإعلامي الشهيد علي شعيب», casualty verbs, demographic
  nouns, vague quantifiers, explicit-none phrases, obituary markers,
  strike-list headings, spelled-out numbers 2–10.

**Code paths fixed** (deterministic, post-LLM):
- `casualty_text.py`: single source of truth for the wording above.
- `casualty_count_backstop.py`: no "digit anywhere" fallback. A count is kept
  only when its value sits next to a matching casualty noun, in the evidence
  span or (span missing) in a local source phrase that becomes the evidence.
  Dates, times, links and «place (n)» entries never validate a count; 0 needs
  an explicit-none phrase. Implicit counts that stay valid (found by the
  cleanup dry-run on real rows): «استشهاد مسعف» = 1 (31492), «وقوع إصابة» = 1
  (28394; not «إصابة مباشرة»), «انتشال جثمانَي …» = 2 (28576), «⭕شهيدان»
  with a glued emoji (31537), and one named victim with a death verb in the
  same sentence («الشهيدة إسراء بهجة… إرتقت», 31703) — the last one supports a
  kept LLM value but never triggers the fill.
- `casualty_count_fill.py`: fills null deaths/injuries from singular/dual words
  or «ثلاثة شهداء» only for single-target messages, same sentence as the
  target, never for obituaries, named victims, the page header or when an
  explicit-none phrase covers that type. Logs `casualty_count_fill filled ...`.
- `tier2_detail_fill_service.py`: only `None` is "empty"; a stated 0 is kept.

**Regression tests added:**
- `tests/test_casualty_text.py` (all helpers, incl. 29191, 30616, 31831, 32708)
- `tests/test_casualty_count_fill.py::test_dual_death_single_village_fills_two_with_evidence` (31539)
- `tests/test_casualty_count_fill.py::test_dual_death_with_later_plural_mention_still_fills` (30335)
- `tests/test_casualty_count_fill.py::test_multi_village_bulletin_is_never_filled` (29191)
- `tests/test_casualty_count_fill.py::test_singular_death_fills_and_vague_injuries_stay_null` (31495)
- `tests/test_casualty_count_fill.py::test_obituary_line_is_not_filled`, `::test_page_header_only_is_not_filled`
- `tests/test_extraction_service.py::test_extract_tier1_fills_dual_death_word_the_model_left_null`
- `tests/test_casualty_count_backstop.py::test_strike_count_list_number_is_not_a_death_count` (32708)
- `tests/test_casualty_count_backstop.py::test_vague_waqu_isabat_never_becomes_one` (30496)
- `tests/test_casualty_count_backstop.py::test_dozens_injured_without_evidence_never_becomes_ten` (31816)
- `tests/test_casualty_count_backstop.py::test_zero_without_explicit_none_is_nulled` (31315)
- `tests/test_casualty_count_backstop.py::test_date_time_or_url_digit_never_validates_a_count`
- `tests/test_tier2_detail_fill.py::test_single_village_stated_zero_is_not_overwritten_by_root_toll`
- `tests/test_max_preserving_empty.py` (NULL/0 merge semantics, unchanged)

Existing rows are corrected by `scripts/fixes/casualty_cleanup.py` (dry-run by default).

## 2026-09-28 - Flare Bomb vs Bombs and skipped extraction override path

**Bug / accuracy gap:** Mansouri, Sour on 2026-09-26
(`الطائرات الإسرائيلية تلقي قنابل مضيئة على بلدة المنصوري في قضاء صور`) and
Haddatha on 2026-09-17 (`الاحتلال يلقي قنابل مضيئة في محيط حداثا`) were
materialized as `Bombs` even though runtime evidence override already matched
the stored text as `Flare Bomb`. Phase A found the regex did not miss; the
pipeline sweep extraction path saved the model's literal `action_description =
"Bombs"` without calling the final action override used by the worker path.

**Rule / knowledge files changed:** `rules/condition_action_reconciliation.md`,
`rules/tier1_general_prompt.md`, and `rules/combined_tier1_prompt.md` now state
that `قنابل مضيئة`, `قنابل إنارة`, `قنابل ضوئية`, `بالونات حرارية`, `flares`,
and `illumination flares` are `Flare Bomb`, not plain `Bombs`, unless an actual
strike/shelling/targeting/explosion/fire/damage/casualty is described. Sound,
smoke, and tear-gas bombs are not plain `Bombs` without strike language. Mixed
strike + flare bulletins must produce separate sub-events or be reviewed.

**Code path fixed:** both `ExtractIncidentsAction` and
`pipeline_llm_workers.run_tier1_extraction_for_message` now share the same
final action override. The deterministic flare guard relabels clean flare-only
`Bombs` results and flags mixed strike + flare text for verification.

**Regression tests added:**
- `tests/test_pipeline_llm_workers.py::test_sweep_extraction_path_relabels_mansouri_flare_bombs`
- `tests/test_pipeline_llm_workers.py::test_sweep_extraction_path_relabels_haddatha_flare_bombs`
- `tests/test_pipeline_llm_workers.py::test_mixed_strike_and_flares_stays_bombs_but_needs_review`
- `tests/test_pipeline_llm_workers.py::test_plain_drops_bombs_without_qualifier_stays_bombs`
- `tests/test_pipeline_llm_workers.py::test_sound_and_smoke_bombs_do_not_resolve_to_plain_bombs`
- `tests/test_pipeline_llm_workers.py::test_incendiary_strike_with_damage_is_not_flare_bomb`

## Backfilled entries for rule commits made without a CHANGELOG entry

Reconstructed on 2026-09-24 from `git show` (audit §4.5). Real examples are the
ones the commits themselves put in the rules; none of these commits added a
rule-text regression test.

- `c60f40e` (2026-09-14) — added `rules/story_revision_prompt.md` and the
  `story_revision` stage. Marker list: `حصيلة أولية`, `تحديث الحصيلة`,
  `ارتفاع عدد`, named-victim `تنعى`. Never invoked until the 2026-09-24
  borderline fallback (opt-in).
- `3480afb` (2026-09-16) — multi-village rewrite of `tier1_multi_village.md`,
  `tier1_general_prompt.md`, `combined_tier1_prompt.md`: only explicit route
  endpoints (`طريق X - Y`, `بين X و Y`) split into two villages; every other
  dash phrase is one target plus `qualifier_text`; per-village counts only from
  that village's clause; a shared toll → `bulletin_aggregate` with figures in
  `total_*`.
- `6b1a0fa` (2026-09-16) — `village_roles` shape with per-village counts and
  `qualifier_text`, `sub_events[].locations`, the Kfar Roummane house+car
  two-sub-event example, parenthetical qualifiers; `قتيل` added to
  `casualty_gender.yaml`; condition label additions.
- `109a2f7` (2026-09-17) — air-violation exclusions (UNIFIL aircraft,
  "من فلسطين باتجاه لبنان" route wording, sector phrases) in relevance and
  Tier 1 prompts. The Tier 1 general copy was written as `?????`; repaired
  2026-09-24 (see "Repair corrupted default Tier 1 prompt").
- `4ce5cd2` (2026-09-21) — conflict attribution for effect-defined actions:
  civilian/accidental fires, traffic accidents and routine works are not war
  events without a stated military actor; negative examples (`احتراق سيارة على
  أوتوستراد المدفون باتجاه بيروت`) and positive ones (`حريق ... إثر قصف مدفعي`).
- `a4db207` (2026-09-21) — extends the effect-attribution list (`تلغيم/تفجير`,
  unexploded ordnance) and adds the distinct-event connector rule
  (`كما طال القصف ... بلدة Y` = second target), example Zawtar ash-Sharqiyah /
  Aitaa al-Jabal.
- `ddc85b2` (2026-09-24) — `بين X و Y` without a road marker is one fuzzy
  location; only `طريق بين X و Y` splits (`غارة بين كفرتبنيت وزوطر الشرقية` vs
  `غارة على طريق بين كفرتبنيت وزوطر الشرقية`).

## 2026-09-24 - Knowledge base cleanup: situational transitions, dead files, few-shot schema

**Bug / accuracy gap:** Every Tier 1 call carried the full casualty-transition
doctrine and the whole condition-label glossary (Tier 1 is told not to classify
conditions). `condition_action_reconciliation.md` was never loaded, so the
Mansouri Sour (raw `1235`, `تمشيط من الاباتشي استهدف المنصوري`) text-over-subtype
rule reached no model. Few-shot `sub_events` used `action_description` while the
prompt schema requires `action_text`, and `village_collision_examples.jsonl`
served a non-extraction `village_match_note` example to Tier 1.

**Rule / knowledge files changed:**
- New `rules/tier1_casualty_transitions.md`: the mandatory transition rules and
  the five transition examples moved out of `tier1_general_prompt.md`
  unchanged. Loaded by the new `has_casualty_transition_language` trigger
  (`متأثر`, `فارق الحياة`, `أحد الجرحى/جريحي/المصابين`, rising/updated toll,
  `بقي N جرحى`, or the transition backstop). The `casualty_transitions` field
  definition stays in the core prompt.
- `index.yaml`: `tier1_extraction` no longer loads `condition_labels.yaml`;
  it now loads `condition_action_reconciliation.md` as core. The never-built
  `casualty_scope`, `casualty_transitions` and `village_matching` stages were
  removed.
- `casualty_merge.md` and `village_matching.md` moved to `Docs/llm_knowledge/`
  (they document code behaviour; no LLM consumed them). `tier1_core.md` deleted
  (orphaned since Phase 3, superseded by `tier1_general_prompt.md`).
- `fewshot/*.jsonl`: `sub_events[].action_description` → `action_text`;
  the `village_match_note` example removed.
- `combined_tier1_prompt.md`: duplicated intro (lines 1-13 repeated at 15-27,
  byte-identical) removed.
- Measured effect (assembled system prompt, ~4 chars/token English, ~2.5
  Arabic): single-village post 14,401 → 14,083 chars (~4.6k → ~4.5k tokens);
  multi-village 22,663 → 22,345; a transition follow-up grows 14,466 → 15,418
  because it now also gets the reconciliation rule. The prompt was already
  ~4.5-7k tokens once the Phase 1 duplication was removed, not 9-11k.

**Regression coverage:**
- `tests/test_llm_knowledge_loader.py::test_transition_rules_load_only_with_transition_language`
- `tests/test_llm_knowledge_loader.py::test_tier1_does_not_load_condition_label_glossary`
- `tests/test_llm_knowledge_loader.py::test_build_loads_core_rules`
- `tests/test_llm_knowledge_rule_integrity.py` (allowlist for
  `combined_tier1_prompt.md` removed)
- Live gate still open: `python -m app.core.llm_knowledge.eval.run_eval --live`
  must show no regression before these rule moves are treated as final.

## 2026-09-24 - Story revisions: no silent downward revisions, recency required

**Bug / accuracy gap:** A sparse report (`ووقوع اصابات`) with embedding
similarity ≥ 0.40 to a prior incident was classified as a revision and
`apply_story_revision` overwrote counts unconditionally, so a late "2 injured"
could replace "5 injured" (audit F1-12). No check that the report was newer.

**Rule / knowledge files changed:** `rules/story_revision_prompt.md` is now
wired as an opt-in fallback (`STORY_REVISION_LLM_FALLBACK_ENABLED`, off by
default) for the borderline band 0.40-0.55 only; its answer must name a marker
to count as a revision. Code: heuristic-only revisions are tagged; one that
would lower a count is held (`needs_verification`, proposed values recorded)
instead of applied; a report not newer than every source already merged into
the incident is not a revision. Threshold kept at 0.40: the corpus has no
similarity-scored revision pairs to justify a different number.

**Regression coverage:** `tests/test_story_revision_guards.py`

## 2026-09-24 - Tier 2 receives the multi-village context

**Bug / accuracy gap:** Tier 2 runs per category on the whole post without
knowing it is a multi-village bulletin, so a bulletin-wide toll could be
returned as a category's casualties (audit F2-06).

**Rule / knowledge files changed:** `tier2_category_detail_prompt.md` and
`tier2_batched_category_detail_prompt.md` gain a multi-village rule; the user
message now starts with a Tier 1 context block (villages + casualty_scope) when
the bulletin names 2+ villages. Per-village *attribution* of category
casualties is not possible yet: the category schema has no village field, so
multi-village category casualties are still suppressed and flagged in code.

**Regression coverage:** `tests/test_tier2_scope_context.py`

## 2026-09-24 - Eval corpus fixes

`eval/corpus/relevance_filter.jsonl` started with a UTF-8 BOM, which made
`run_eval.py` fail on line 1 (`Unexpected UTF-8 BOM`); stripped.
`village_matching.jsonl` row 6 (`وادي السلوقي`) now expects ACS 73282 per the
2026-09-23 alias; row 7 (bare `وادي الحجير`) is left unresolved because only
`محمية وادي الحجير` is aliased. Added real-pattern cases: Talloussa/Yahoun
per-village actions, Mansouri raw `1235`, the Majdal Zoun fuzzy-area bulletin
and a civilian car fire. Corpus: 41 cases, offline harness 41/41.

## 2026-09-24 - Repair corrupted default Tier 1 prompt and multi-village example

**Bug / accuracy gap:** `rules/tier1_general_prompt.md` (the default Tier 1
general-fields prompt) contained the whole prompt twice after merge commit
`ffa2576`. Copy 1 stopped mid-schema at `"casualty_scope": "unspecified",` and
was the only copy with the fuzzy-area rule («في محيط X وY»), the effect-attribution
rule and its fire/قطع طريق examples, and the Majdal Zoun / بيوت السياد negative
example; copy 2 was the only one with the CNRS fire safety rule. Commit
`109a2f7` also wrote the air-violation exclusion lines with `"?? ?????? ?????? ?????"`
and `"?????? ??????"` instead of Arabic (they were never clean in git). In
`rules/tier1_multi_village.md` the Talloussa/Beit Yahoun example from `4edc7f0`
carried double-encoded text (`ØªÙ…Ø´ÙŠØ·`).

**Rule / knowledge files changed:**
- `rules/tier1_general_prompt.md`: one copy, copy 2's structure and complete
  schema, with copy 1's unique guardrails merged back in. Copy 2's variant of the
  road rule was split back into copy 1's road rule plus the fuzzy-area rule, which
  now also lists «بين بلدتي X وY» and «في المنطقة الواقعة بين X وY». The garbled
  lines now read "من فلسطين باتجاه لبنان" and "القطاع الشرقي", "القطاع الغربي",
  "القطاع الأوسط", copied from the same rule in `combined_tier1_prompt.md:42-43`.
- `rules/tier1_multi_village.md`: example restored to `تمشيط` and
  `قنابل مضيئة وحارقة` (decoded from the mojibake).

**Regression coverage:**
- `tests/test_llm_knowledge_rule_integrity.py` fails on `???`, mojibake, a
  repeated opening line, or any repeated line of 40+ characters in `rules/*.md`.
  `combined_tier1_prompt.md` is allowlisted until its duplicated intro is fixed.

## 2026-09-24 - Tier 1 is_relevant=false now rejects the post

**Bug / accuracy gap:** Tier 1 returns `is_relevant`, but nothing downstream read
it, so a post the model itself judged irrelevant (UNIFIL, Palestine-route,
civilian-fire or Gaza exclusions) was still matched and materialized whenever it
also filled `village`/`action_description` (audit F1-07). Separately, relevance
errors (e.g. `ConnectError` during an Ollama outage) were reset straight to
`parsed` and skipped the relevance filter entirely.

**Rule / knowledge files changed:** none. Documented rationale for staying
code-only: the exclusion rules already exist in `relevance_filter_prompt.md` and
the Tier 1 prompts; the defect was that their `is_relevant` output was ignored.
`MatchIncidentAction` now rejects it the same way the relevance filter does
(status `rejected`, `filter_result.verdict="reject"`), except after an admin
restore. Error rows record `failed_stage`; only extraction failures are reset to
`parsed`, relevance failures go back to `pending`.

**Regression coverage:**
- `tests/test_relevance_gate_bypass.py`

## 2026-09-24 - Tier 2 no longer stamps the bulletin toll onto every village

**Bug / accuracy gap:** For a multi-village bulletin (e.g. one CNRS post naming
Talloussa and Beit Yahoun with a single total of 5 killed), fast-path correctly
left each village's `deaths` as `None`, but Tier 2 detail fill then copied the
root toll onto every village row whose value was `None` or `0` unless
`casualty_scope` was exactly `bulletin_aggregate`. An `unspecified` scope, or a
`bulletin_aggregate` claim downgraded to `unspecified` by the scope backstop,
therefore gave each village the full toll (audit F1-02).

**Rule / knowledge files changed:** none. Documented rationale for staying
code-only: the model's scope label was not the driver. Materialization already
treats a multi-village per-village `None` as meaningful regardless of scope;
Tier 2 was the one path that re-applied the root count. `tier2_detail_fill_service`
now never backfills root counts onto multi-village incidents (a `None` or an
explicit `0` is final). Single-village backfill is unchanged.

**Regression coverage:**
- `tests/test_tier2_detail_fill.py::test_multi_village_unspecified_scope_does_not_stamp_root_toll`
- `tests/test_tier2_detail_fill.py::test_multi_village_explicit_zero_is_not_overwritten_by_root_toll`
- `tests/test_tier2_detail_fill.py::test_multi_village_aggregate_downgraded_to_unspecified_does_not_stamp`
- `tests/test_tier2_detail_fill.py::test_single_village_still_backfills_root_toll`

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

