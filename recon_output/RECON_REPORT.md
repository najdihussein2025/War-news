# Recon report — "ملخص الاعتداءات" summary bulletins

Scope: recon only. No file under `app/` or `frontend/` was modified, no migration, no write SQL, no Ollama call, no commit.
Data: `war_news_dev`, read-only (every script session runs `SET TRANSACTION READ ONLY`). Date of run: 2026-10-07.

## 0. Headlines

1. **The pipeline recovers about 24% of the rows a bulletin implies** (408 of 1,679 expected, 80 scorable bulletins; 29% if soft-deleted rows are counted; 30% on the 20 bulletins whose parse is fully trustworthy). Median bulletin: 21 expected rows, 3 created.
2. **The reference message is not shaped like the pasted example.** The real text (raw_message 40279) puts each `⭕️` header on its own line and separates places with `🔸`. Only **1 of 221** bulletins uses `🔸`; the rest put one place per line (often with `•`/`*`), so "villages separated by spaces" is the exception, not the rule. Multi-word names still matter (`وادي الحجير`, `النبطية الفوقا`) but the line/bullet separators are present in almost every bulletin.
3. **A plain `بين X و Y` anywhere in the message switches off the multi-village rules and triggers a fuzzy-area collapse** (details in §4, F1). For the reference bulletin this is what turned the whole artillery list into "one fuzzy area, alternates: …".
4. **The existing deterministic bulletin fallback (`sectioned_bulletin.py`) does not fire on the reference** and fires on only 46 of 221 bulletins (§1, Q3).
5. **The flare/strike verification reason is message-wide, not row-wide, and survives the Phase 4 policy.** All 8 live rows of message 40279 carry it, not just the flare row (§1, Q6).
6. **No code path turns `بين X و Y` into one row for the whole phrase**: the prompt and the collapse step keep only the first village, while the matcher and the fallback split it into two villages. See Q5.

## 1. Phase 1 — code path

### Q1. Where a raw message enters Tier 1, and the prompt text
- Pipeline worker: `app/news/services/pipeline/pipeline_llm_workers.py:61` calls `classifier.extract_tier1(...)`, then `finalize_extraction_action` at `:66`. The same call exists in `app/llm/actions/extract_incidents_action.py:44,109`.
- `OllamaExtractionService.extract_tier1` — `app/llm/services/ollama_extraction_service.py:473-480` — chooses a flow by settings. Both opt-in flows are **off** in this deployment (`app/core/config.py:57` `tier1_use_combined_presence_extraction=False`, `:63` `tier1_split_phases_enabled=False`), so the live flow is `_extract_tier1_current` (`:482-507`): a presence-gate call (`:494`) plus **one whole-message general call** (`_extract_general_fields`, `:1047-1063`) using `build_stage_system_prompt("tier1_extraction", post_text)`.
- Model: `extraction_ollama_model = qwen2.5:7b` (`config.py:50`), timeout 240 s (`:51`), temperature 0.0.
- Prompt assembly is driven by `app/core/llm_knowledge/index.yaml` (stage `tier1_extraction`, lines 1-18):
  - core: `rules/tier1_general_prompt.md` (23.4 KB source), `rules/condition_action_reconciliation.md`
  - situational: `rules/tier1_multi_village.md` when `is_multi_village_candidate(text)`; `rules/tier1_casualty_transitions.md` when transition wording is present
  - few-shot `fewshot/village_collision_examples.jsonl` (k=3), terminology `role_terms`, `revision_language_markers`, `casualty_gender`
- Rules that bear on bulletins: `tier1_general_prompt.md:26` (fuzzy `بين X وY` → keep only the first village), `:36` (flare ≠ `Bombs`; strike + flare → separate sub_events), `:49` (sub_event locations); `tier1_multi_village.md:9,24` (same fuzzy rule), `:15` (strip `أطراف`/`محيط`/`خراج` prefixes), `:27` (a `(N)` after a place is a strike count, never casualties), `:41-43` (one sub_event per distinct action).

### Q2. How Tier 1 represents multiple (action, village) pairs
- `ExtractionResult` — `app/llm/dtos/extraction_dto.py:210-293`; `ExtractionSubEvent` `:176-207`; `VillageRoleEntry` `:84-92`.
- **Action is per sub_event, not message-level.** `ExtractionSubEvent` = `{locations: [VillageRoleEntry], action_text, casualties, evidence_span, …}`. So N actions × M villages with a different action per village is representable, as one sub_event per action holding that action's locations. Root `action_description` is a message-level summary (`tier1_multi_village.md:41-43`); root `village_roles` is a flat list with no action attached.
- Response schema: `GENERAL_EXTRACTION_RESPONSE_SCHEMA`, `ollama_extraction_service.py:173+` (`sub_events` array, no `maxItems`). `VillageRoleEntry` has **no count field**, so `(٢)` cannot be carried on a row today.
- Downstream: the matcher produces one `VillageMatchResult` per location plus one `SubEventMatchResult` per sub_event for the condition (`app/news/dtos/match_result_dto.py:14-91`; `matching_service.py:363-373,542-567`); materialization fans out one incident per target village.

### Q3. Existing multi-item / bulletin detection
- `is_multi_village_candidate` — `app/core/llm_knowledge/loader.py:40-78` (only gates which rule file is loaded).
- `recover_sectioned_sub_events` — `app/llm/services/sectioned_bulletin.py` (whole file), called from `_build_tier1_result` at `ollama_extraction_service.py:619-627`; it replaces the model's sub_events only when it finds more pairs. Measured on this corpus (pure function, no LLM):
  - fires on **46 / 221** messages (21 / 86 of the materialized ones); **does not fire on the reference**.
  - Why it misses the real shape: `_heading_action` (`:25-38`) uses `fullmatch` on the whole line with a narrow pattern list, so `الغارات من الطيران الحربي`, `الغارات التي نفذها الطيران الحربي المعادي` (98 occurrences) and any header with a trailing location or emoji don't qualify; locations split on `،`/`,` only (`:58`), no `🔸`/`•` handling and no `(N)`; `بين X و Y` is split into **two** locations (`:45-57`).
- `_multi_village_action_scope_review` — `ollama_extraction_service.py:755-785`: only runs when `sub_events` is empty.
- Split-phase segmentation (`split_phase_extraction.py`, `tier1_split_max_segments=10`) exists but is disabled.
- Search for `ملخص`/`bulletin`/`summary`: no code detects "summary bulletin" as a message type; "bulletin" in the codebase means any multi-village post.

### Q4. Token / context limits
- `OLLAMA_NUM_CTX=8192` (`.env:45`, `config.py:44`), applied in `app/core/ollama_client.py:22-42`. **No `num_predict`** is sent (server default). `format` = the JSON schema (`ollama_client.py:83-92`); schema has no length caps. Timeout 240 s.
- Measured locally with `build_stage_system_prompt` for the reference text (no LLM call): `tier1_extraction` system prompt **19,607 chars** (8,705 Arabic letters, 6,196 Latin), roughly **6.5–7.5k tokens** by a chars-per-token heuristic (no tokenizer in the image, so treat as ±20%). Plus ~0.2k for the message, plus a separate presence-gate call (~1.7k).
- Outputs for big bulletins are large: the largest stored Tier 1 results are 12.7k chars (messages 35837, 36363: 20–21 sub_events), roughly 4–5k tokens. Prompt + output for those would exceed 8,192, yet both stored results parsed, and there are **no JSON-parse failures** among the 27 errored bulletins (see §6).
- Verdict: **truncation/context is a possible factor but unproven.** `OllamaChatClient` returns only the message content (`ollama_client.py:96,117`), discarding `done_reason` and `prompt_eval_count`, and the config comment itself warns that an undersized `num_ctx` silently drops the start of the system prompt (`config.py:38-44`). It cannot be confirmed or ruled out from stored data.

### Q5. How `بين X و Y` and `اطراف X` are handled
`بين X و Y` (four places, with different outcomes):
1. **Prompt**: one fuzzy location, keep the first village only (`tier1_general_prompt.md:26`, `tier1_multi_village.md:9,24`).
2. **Loader**: `is_multi_village_candidate` **returns False** as soon as `_FUZZY_AREA_RE` matches a non-route `بين X و` (`loader.py:58-65`), so the multi-village rule file is not even loaded. For the reference text it returns False; over the corpus it is True for 114 and False for 107 messages.
3. **Post-processing**: `_collapse_fuzzy_area_locations` (`ollama_extraction_service.py:1732-1785`, called at `:609` and, per sub_event, `:635`). It takes the **first** `بين|محيط|قرب` in the text, takes everything after it up to the next `،؛.!؟` or newline as the "tail", and if ≥2 extracted villages appear in the tail it keeps the first and moves the rest into `location_alternatives` (dropped from the village list). With `🔸`-style single-line lists the tail is the rest of the whole line.
4. **Matching**: `_split_village_pair_text` (`matching_service.py:263-276`) + `_split_if_resolvable_pair` (`:652-664`) split `بين X و Y` back into two villages when both resolve. The sectioned fallback (`sectioned_bulletin.py:45-57`) also splits it into two.

`اطراف X`: no extraction-stage code; handled only at matching by `_strip_generic_descriptors` (`matching_service.py:239-250`, applied around `:726-735`) using `terminology/village_descriptors.yaml` (`أطراف`, `اطراف`, `مشارف`, `ضواحي`, `أحراج`, `سهل`, `تلة`, `محيط`, `مرتفعات`, `تلال`, `جرود`, `خراج`, `أراضي`, `بلدة`, …). The descriptor is dropped only if the stripped name resolves better. `village_aliases.py:68-69` notes the generic-descriptor strip was a pending task. A few aliases like `محيط النبطية الفوقا` exist in `village_location_aliases`.

`(N)`: only mentioned as a rule ("never casualties"), no representation.

### Q6. Where "Message mentions both flare bombs and strikes" comes from
- Wording is front-end only: `frontend/src/features/news/verificationReasons.tsx:65-66` (key `flare_strike_wording` when the stored reason contains flare/phosph **and** strike/raid) and `:161`.
- The stored reason is `FLARE_GUARD_REVIEW_REASON` ("Flare wording appears together with strike language; verify whether this message contains both a strike and flare bombs.") — `app/llm/services/action_finalization.py:11-15`.
- Trigger: `finalize_extraction_action`, `action_finalization.py:61-70`, runs after Tier 1: if the **root** `action_description` is `"Bombs"` and `has_flare_language(post_text)` and `has_strike_language(post_text)` (`condition_evidence_override.py:132-139`, regexes over the **whole message**) then `needs_review=True` on the whole `ExtractionResult`.
- It becomes a verification reason through `_extraction_review_reason` (`incident_materialization_service.py:161-176`; used at `:567`, `:730`, `:1324`) and is stamped on **every row** built from that extraction.
- Evidence (message 40279): all 8 live incidents (airstrike, artillery and flare rows alike) are `needs_verification` with this reason. The user-reported "flare row flagged" is the visible one of eight.
- Policy mismatch: `verification_signals.py:342-355` says flare/strike wording is now a quality flag only (Phase 4, decided 2026-10-05), and `Incident.quality_flags` documents the same (`incident.py:112-117`), but the extraction-level `needs_review` path above is separate and still produces a review reason. Across the corpus it affects 8 of 448 live rows (all one message) and 4 stored Tier 1 results.

### Q7. Condition taxonomy (`conditions` table)
Columns are `id, action_en, action_ar` (there is no `name_ar`/`name_en`). 46 rows:

| id | action_en | action_ar |
|---|---|---|
| 2 | Warning Raid | غارة تحذيرية |
| 3 | Drone Failure | سقوط مسيّرة |
| 4 | Suicide Drone | مسيرة مفخخة |
| 5 | Artillery Shelling | قصف مدفعي |
| 6 | Tank Fire | قذائف الدبابات |
| 7 | Phosphorus Bombs | قذائف فوسفورية |
| 8 | Smoke Grenades | قنابل دخانية |
| 9 | Flare Bomb | قنابل مضيئة وحارقة |
| 10 | Sound Bombs | قنابل صوتية |
| 11 | Cluster Bombs | قنابل عنقودية |
| 12 | Nail bombs | قنابل مسمارية |
| 13 | Grenades | قنابل |
| 14 | Fissile Shells | قذائف انشطارية |
| 15 | Decoy Flares | القاء بالونات حرارية |
| 16 | Hand Grenades | قنابل يدوية |
| 17 | Shooting | إطلاق نار |
| 18 | Sweeping Operations | عملية تمشيط |
| 19 | Aerial Sweep | عملية تمشيط مروحي |
| 20 | Ground Incursion | توغل بري |
| 21 | Mining & Detonation | تلغيم وتفجير |
| 22 | Stationing | تمركز |
| 23 | Naval Incursion | توغل بحري |
| 24 | Road Blockage | قطع طريق |
| 25 | Bulldozing | حفر وجرف |
| 26 | Cutting Trees | قطع اشجار |
| 27 | Burning Properties | احراق ممتلكات |
| 28 | Raiding & Stealing Homes | اقتحام/ سرقة منازل |
| 29 | Arrest Operation | عملية احتجاز |
| 30 | Kidnapping | خطف |
| 31 | Ambushes | كمائن |
| 32 | Releasing Cattle | تسريح ماشية |
| 33 | Installing Surveillance Devices | اجهزة تجسس |
| 34 | Spy Balloon | منطاد تجسسي |
| 35 | Warplane | طيران حربي |
| 36 | Surveillance Aircraft | طيران استطلاعي |
| 37 | Supersonic boom | خرق جدار الصوت |
| 38 | Helicopter Hovering | طيران مروحي |
| 39 | Feigned Attacks | غارات وهمية |
| 40 | Interceptor Missile | صاروخ اعتراضي |
| 41 | Unexploded Shells | قذائف لم تنفجر |
| 42 | Throwing Foreign Objects / Substances | رمي أجسام/ مواد مجهولة |
| 43 | Broadcast Provocative Statements / Warning Messages | عبارات / مناشير تحريضية / اتصالات تحذيرية |
| 44 | Obstructing Duties | عرقلة مهام |
| 45 | Air Activity - Needs Verification | نشاط جوي بحاجة إلى التحقق |
| 46 | Bombs | قصف وغارات |
| 87 | Unclassified / Needs Review | غير مصنف / بحاجة إلى مراجعة |

Mapping notes (facts about the taxonomy, not a proposal): there is no dedicated "airstrike" condition — strikes land on 46 `Bombs / قصف وغارات`; "demolition/explosion" corresponds to 21 `Mining & Detonation`; flare 9 and phosphorus 7 are separate ids, while 9's Arabic name is `قنابل مضيئة وحارقة`. Headers with no obvious condition in the corpus: `غالونات متفجرة` (16), `قنابل «لانشر»` (9), `القنابل المتفجرة` (5), `القصف من مروحيات اباتشي` (4), and drone-strike headers (`الغارات التي نفذها الطيران المسير المعادي`, 22; no drone-strike condition besides 46).

## 2. Corpus (Phase 2)

Script: `scripts/recon/export_summary_bulletins.py`. Tables/columns used: `raw_messages` (`raw_text`, `status`, `filter_result`, `extraction_result`, `match_result`, `message_datetime`, `received_at`, `origin_account`, `duplicate_of_id`), `sources.name`, `incidents.raw_message_id` (link back), `villages`, `conditions`. Match: normalized text (tatweel stripped, `أإآ→ا`, `ة→ه`, `ى→ي`, whitespace collapsed) contains any of the five phrases; SQL prefilter, Python re-verification.

- **221 bulletins** (source rows: `CNRS Webhook` 215, `CNRS Webhook (backfill)` 6). By originating channel (`origin_account`): nabatiehchannel 51, alichoeib1970 44, mehwaralmokawma 43, Janoubana 38, sameralhajali 32, hashemsayed 11, bintjbeilnews 1, almanarnews 1.
- Pipeline status: materialized 86, **duplicate 107**, error 27, rejected 1. Duplicates are mostly the same bulletin re-posted by other channels (91 point at a representative that is itself in the corpus); their rows, if any, live on the representative.
- Live incidents: 448 (431 from materialized messages, 17 from errored ones). Soft-deleted: 104 (`deleted_reason` is NULL on all of them; who deleted them is not recorded here). Average 2.03 live incidents per bulletin; **143 bulletins have 0** = 107 duplicate + 26 error + 1 rejected + 9 materialized (those 9 only have soft-deleted rows).
- Errored bulletins (27): 12 `fast_path: unmatched or missing condition`, 8 `fast_path: exact hash already materialized`, 6 `fast_path: no materializable village match`, 1 extraction `ConnectError`. These are materialization failures, not LLM failures.
- Tier 1 `sub_events` present in only 81/221 messages; 41 of the 86 materialized bulletins have none.
- Layout of the 221: sectioned list (header, then places) 195; timeline/prose with no list headers 26 (e.g. `الساعة ٥:١٠ … تفجيرات في بلدة المنصوري`). `🔸` appears in 1 message (the reference).
- Outputs: `summary_bulletins.jsonl` (2.8 MB, contains full message texts), `summary_bulletins_overview.csv`.

## 3. Structure analysis and recall (Phase 3)

Script: `scripts/recon/analyze_bulletin_structure.py`. Parsing is heuristic (no LLM): a header is a line ending in `:` that contains action vocabulary, or a colon-less line made only of action words; locations are split on newline, `•`, `*`, `🔸`, `،`; `بين X و Y` is one segment, `(N)` is a count not a row, `اطراف/محيط/خراج X` is a modifier; a trailing `لجهة/عند/قرب …` is a qualifier. Expected rows = Σ over sections of (segments × actions in the header). **The parser reproduces the reference answer: 20 expected rows** for message 40279.

| Measure | Value |
|---|---|
| Segments parsed | 4,309 |
| Fully matched in gazetteer (villages `ref_name_ar`/`acs_name` + `village_location_aliases`, after the matcher's descriptor strip) | 3,595 (83.4%); 45 of them only after descriptor strip |
| Unmatched segments | 706 |
| Scorable bulletins (materialized, ≥1 expected row) | 80 |
| Expected rows / created rows (capped per bulletin) | 1,679 / 408 → **24.3%** |
| Same, counting soft-deleted rows | 28.7% |
| Clean-parse subset (every segment is a known place) | 20 bulletins, 113 / 379 → 29.8% |
| Mean "village presence" recall (share of expected places that appear anywhere in Tier 1 names or incident names) | 64.1% |
| Recall by expected size | ≤10 rows: 59/166 (35.5%); 11–25: 216/580 (37.2%); >25: 133/933 (14.3%) |
| Recall by channel | alichoeib1970 36.3%, Janoubana 26.4%, nabatiehchannel 23.1%, mehwaralmokawma 18.7%, hashemsayed 16.7%, sameralhajali 15.6% |

Modifier frequencies over the 4,309 segments (`bulletin_modifiers.csv`): `بين X و Y` 151 (38 of them as `بين X-Y`), `اطراف` 209, `محيط` 16, `خراج` 4, `(N)` 35, `لجهة/عند/قرب` qualifier 143, dash compounds `A-B` 84, space-separated list that needed gazetteer splitting 3.

Caveats on these numbers:
- Count-based recall measures how many rows exist, not whether they are right.
- The expected-row estimate is inflated for long narrative bulletins (mixed headers plus prose lines such as `تحركات وآليات العدو`), which is why the 20-bulletin clean subset is reported next to it. The ">25" bucket is the least reliable.
- 9 materialized bulletins show 0 live rows because their rows were soft-deleted; 92 more soft-deleted rows sit on other materialized bulletins. Cause not investigated.
- Duplicate bulletins are excluded from scoring (their rows belong to the representative).

Files: `bulletin_headers.csv`, `bulletin_unmatched_tokens.csv`, `bulletin_recall.csv` (30 worst), plus `bulletin_recall_all.csv` and `bulletin_failure_examples.jsonl` (per-bulletin evidence) as extras.

## 4. Failure modes, with real examples

Counts are over the 80 scorable bulletins and are detection heuristics, not exact.

**F1. Dropped locations (73 of 80 bulletins miss at least one listed place in Tier 1).**
- Reference 40279: 18 location mentions (20 rows); Tier 1 emitted 4 sub_events holding 9 locations. Never extracted as a location: المنصوري (both sections), اطراف شقرا, النبطية الفوقا, بيت ياحون, وادي زبقين, الخيام, and حاريص/حداثا only as the corrupted `Hardinga`/`حدثا`. (ارنون was extracted but lost later, see below.) Tier 1 stored `qualifier_text: "fuzzy area; alternate: المنصوري, بين حداثا و حاريص, اطراف شقرا, النبطية الفوقا, بيت ياحون, وادي زبقين, اطراف ميفدون, اطراف برعشيت"` on `ميفدون` — i.e. the artillery list was collapsed by `_collapse_fuzzy_area_locations` because the section contains `بين حداثا و حاريص` and, in the single-line layout, everything after it is "the tail" (Q5-3). The multi-village rule file was not loaded either (Q5-2).
- 29730 (sameralhajali): 41 expected rows, 3 created, Tier 1 `sub_events=0`.
- 31404 / 31412 / 31714: 35 expected rows each, 0 live rows, `sub_events=0`.
- A second, later loss: for 40279 the matcher produced 10 village matches (including كفرتبنيت, matched 1.0, and ارنون) but only **8 incidents** exist. Which stage dropped those two was not established.

**F2. Merged / lost actions (48 of 80 have fewer Tier 1 sub_events than sections; 37 have none).**
- 1115 (mehwaralmokawma): 5 sections (artillery, detonations, flares, sweeping, launcher bombs), 10 expected rows; 0 sub_events; the 3 rows are all `Artillery Shelling` (القنطرة, علي الطاهر, حولا). Detonation, flare and `الخيام` rows are absent.
- 28038 (alichoeib1970): 36 expected, 9 created, all `Bombs` regardless of section.
- 29730: rows typed `Sweeping Operations` for ميفدون and دوحة كفررمان, which come from different sections.
- 27996 (hashemsayed): 10 expected, 1 row, `Bombs`.
- Reference 40279: two sections reached the right conditions (46, 5, 21, 9) via sub_events, but `قنابل مضيئة و فسفورية` produced a single `Flare Bomb` row for مجدل زون (phosphorus missing) and the root action was `Bombs`.

**F3. `بين` phrases split into two villages (15 bulletins show one side of a `بين` phrase as its own place).**
- 40279: `بين محيبيب و برعشيت` → two rows: محيبيب (Marjaayoun) and برعشيت (Bint Jubail), 1.0 score each. Expected: one row.
- 1240 (alichoeib1970): `بين برعشيت و كونين` → two `Mining & Detonation` rows; the next line was glued on, producing raw name `كونين المنصوري` resolved to المنصوري (Sour).
- 29730: `بين ميفدون وزوطر الشرقية` → a single ميفدون row typed `Sweeping Operations`.
- 28038: `بين حداثا و حاريص` → only حاريص survives.

**F4. Wrong-district / wrong-village matches (40 of 80 have a row resolved to a village not named in the bulletin; a share of these are the by-design `وادي X → parent village` alias, e.g. `وادي الحجير → قبريخا`, `وادي السلوقي → تولين`, score 1.0, see CHANGELOG line ~741).** Weak ones accepted at low score:
- `حدثا` (model's misspelling of حداثا) → `حدث`, **Baabda**, 0.50 (40279).
- `Hardinga` (model output for حاريص) → `حردين`, **Batroun**, 0.545 (40279, 28044, 30354, 34551).
- `وادي السلوقي` → `وادي الحور` (Akkar, 0.41; 28044), `وادي الست` (Chouf, 0.53; 1276, 28038).
- `مزرعة بسطرة` → `مزرعة طمره` (Jezzine, 0.44; 1276); `دوبيه` → `دبية` (Chouf, 0.375; 30629); `حانين` → `حنين` (0.375; 32249).
- Several matches have `matched_low_confidence` status at confidence 1.0 and `exact` method (5 of the 10 matches in 40279: محيبيب, برعشيت, ميفدون, ارنون, مجدل زون). Cause not verified.

**F5. Invented / non-source names (29 of 80 bulletins contain a Tier 1 name that is not in the text; 9 of those are Latin-script).**
- `Hardinga` (4 bulletins), `Benton Jbeil` / `Benton Jibail` (33170, 34437; the model transliterates بنت جبيل, and 33170 yields three `بلاط` (Jubail, 0.41) rows), `حدثا` for حداثا.
- Typos from the sources themselves also flow through: `صريين` for صربين, `دوحه كفرمان` for دوحة كفررمان, `ميوفدون`.

**F6. Wrong verification flags.** 40279: 8 of 8 live rows `needs_verification` with the flare/strike reason (Q6). Across the corpus only 20 of 448 live rows are `needs_verification`: 12 duplicate-related, 8 flare/strike (all in this message). No row carries the correct policy reasons for the dropped rows because they were never created.

**F7. Rows lost after Tier 1.** 27 errored bulletins (mostly fast-path materialization failures: no condition, exact-hash collision, no village), 107 deduplicated bulletins, 104 soft-deleted rows. These are outside LLM recall but they bound what a bulletin yields.

## 5. Header dictionary and unmatched tokens

48 distinct normalized headers over 195 sectioned bulletins; 3 contain ` و ` (`القصف المدفعي و الفوسفوري` ×3, `قنابل مضيئه و فسفوريه` ×1, plus one clause that is not a compound action). Top headers (full list with sources and heuristic condition hints in `bulletin_headers.csv`):

| freq | header (normalized) | heuristic condition |
|---|---|---|
| 122 | القصف المدفعي المعادي | 5 Artillery Shelling |
| 99 | التفجيرات التي نفذها العدو في البلدات الجنوبيه | 21 Mining & Detonation |
| 98 | الغارات التي نفذها الطيران الحربي المعادي | 46 Bombs |
| 57 | القصف المدفعي | 5 |
| 42 | التفجيرات | 21 |
| 41 | القنابل المضيئه | 9 Flare Bomb |
| 29 | التمشيط بالاسلحه الرشاشه | 18 Sweeping |
| 26 | القنابل الصوتيه | 10 Sound Bombs |
| 26 | الغارات الحربيه | 46 |
| 22 | الغارات التي نفذها الطيران المسير المعادي | 46 (no drone-strike condition) |
| 16 | غالونات متفجره | unmapped |
| 15 | الغارات من الطيران الحربي | 46 |
| 9 | قنابل «لانشر» | unmapped |
| 4 | القصف الفوسفوري | 7 Phosphorus Bombs |
| 4 | القصف من مروحيات اباتشي | unmapped |

Note: headers are not the whole picture. 26 bulletins have no list headers, and lines such as `زوطر الشرقيه مدفعي فوسفوري` / `قصف مدفعي يستهدف المنصوري` are per-event lines (action and place together), not sections.

Unmatched gazetteer entries (top segments; the real matcher's descriptor strip already applied; `bulletin_unmatched_tokens.csv` has top 50 segments plus top 50 words):

| count | segment | note |
|---|---|---|
| 35 | مشاع المنصوري | prose-like place qualifier |
| 33 | عيتا الجبل | ref name is `عيتا الجبل الزط` (id 78) |
| 21 | الطيبه | refs are `طيبة بعلبك` / `طيبة مرجعيون` |
| 18 | مزرعه بسطره | |
| 16 | يحمر الشقيف | |
| 12 | سدانه | |
| 11 | وادي السلوقي-القنطره | dash compound |
| 10 | علمان الشومريه | |
| 9 | وادي مظلم-بيت ليف | dash compound |
| 8 | صريين | source typo of صربين |
| 8 | دوحه كفرمان | source typo of دوحة كفررمان |
| 7 | حداثا وحاريص | two places joined by `و` with no space |
| 5 | حولا ووادي السلوقي | same |

Many of the remaining entries are prose fragments from narrative lines (`تقدم معاد من بلده حداثا`, `قنبله صوتيه`), not place names.

## 6. Truncation and context limits

- Configuration makes a context problem plausible: `num_ctx=8192` with a ~6.5–7.5k-token system prompt for this flow, plus up to ~5k tokens of JSON output for 20-sub_event bulletins (Q4). No `num_predict` is set, so output length is not capped by the client.
- Evidence against output truncation: the largest stored results (12.7k chars, 20–21 sub_events) are valid JSON; none of the 27 errored bulletins failed on JSON parsing (one `ConnectError`, the rest fast-path materialization errors).
- Not verifiable here: whether the head of the system prompt is being dropped, because `done_reason` and `prompt_eval_count` are discarded by the client and the Ollama server was not called. Separately, for the reference bulletin the multi-village rule file is **not** in the prompt (Q5-2), which is a prompt-content problem independent of context size.

## 7. Open questions this recon could not answer

- Which stage dropped كفرتبنيت and ارنون between 10 village matches and 8 incident rows in message 40279.
- Why 104 incident rows from these bulletins are soft-deleted with no `deleted_reason`.
- Why rows with exact name match and score 1.0 are `matched_low_confidence`.
- Whether prompt truncation occurs at `num_ctx=8192` on the Ollama server.
- How many expected rows in the no-header/timeline bulletins (26) are legitimate; they are excluded from recall.

## 8. Method notes and deviations from the brief

- `docker compose exec backend` runs the image-baked code (the backend service has no bind mount), so the two new scripts were `docker compose cp`'d into the running `backend` container before running; the outputs were copied back. Nothing else in the container was changed.
- Test suite: `docker compose exec backend pytest -q` would run integration tests against the live `war_news_dev` URL. Instead the working tree was copied into a throwaway container with a dummy `DATABASE_URL` (the approach in the project notes). Result: **1643 passed, 3 failed, 14 skipped** (`tests/test_pipeline_health_route.py::test_pipeline_health_requires_super_admin`, `tests/test_pipeline_jobs.py::test_enqueue_coalesces_pending_jobs`, `tests/test_pipeline_jobs.py::test_reclaim_orphaned_running_jobs`; the last two raise SQLAlchemy errors, consistent with the dummy DB URL). This recon changed no application or test code, so the result reflects the existing working tree. The throwaway container was removed.
- `git status` shows only `recon_output/` as new; the two new scripts under `scripts/recon/` do **not** appear because `.gitignore:14` (`recon/`) ignores them (the four existing files in that folder were force-added). `.gitignore` was left alone. The `M` entries for two `frontend/` files and `report.md` were already in the working tree before this work.
- Extra files beyond the brief, all under `recon_output/`: `bulletin_recall_all.csv`, `bulletin_modifiers.csv`, `bulletin_failure_examples.jsonl`.
