# Tier 1 situational rules — multi-village bulletins

Load when the message appears to name multiple target locations.

## Detection signals

- Two or more place names in separate clauses (semicolon, colon, or list).
- Explicit route/path endpoints only: `طريق … X - Y`, `طريق عام X - Y`, or `طريق بين X و Y` → two distinct villages/endpoints.
- Fuzzy area references are one location, not a village list: `في محيط X وY`, `محيط X وY`, `قرب X وY`, `بالقرب من X وY`, or plain `بين X وY` when no route/path is named. Keep the first-mentioned village as the primary attribution and mark the location low-confidence with the other village as reviewable context.
- A distinct-event connector introduces a genuinely separate second target, not a qualifier: `كما طال القصف/الغارة/الاستهداف ... بلدة Y` after an already-described strike on `X` means two separately scoped locations, each with its own action/evidence — this is the opposite of a محيط/بين vicinity phrase describing one fuzzy place.
- Every other dash phrase defaults to one target on the left and qualifier context on the right: `بلدة X - حي Y`, `مزرعة X - Y`, `بلدة X - قضاء Y`, or `بلدة X - [neighborhood/hamlet]`.
- In `مزرعة X - Y وZ`, the complete `Y وZ` tail is qualifier context, not two additional targets.
- Multiple `target` entries in expected extraction.

## Extraction rules

1. Each target village gets its own `village_roles` entry.
2. Route endpoints (`طريق X - Y`, `طريق عام X - Y`, or `طريق بين X و Y`): emit both `X` and `Y` as separate target locations (and inside the same `sub_event.locations` if a single route action occurred). Plain `بين X و Y`, `بين بلدتي X و Y`, and `في المنطقة الواقعة بين X و Y` without a road/route are one fuzzy target attributed to the first village with the other village kept as review context.
3. For every non-route dash phrase, emit only the left side as the target and preserve the entire right side as `qualifier_text`, including any `و`-joined parts.
4. Copy per-village deaths/injuries only from that village's sentence or phrase.
5. If only a shared toll is given covering all villages → `casualty_scope: bulletin_aggregate`.
6. Put shared figures in `casualties.total_deaths` / `total_injuries`; leave `deaths`/`injuries` null.
7. `casualty_scope_evidence` must be the full clause showing whether the toll is shared or per-village.

8. If the bulletin describes more than one distinct action/condition across the villages, emit one `sub_events` item per distinct action. Each item must have only that action's own `locations`, a condition-matchable `action_text`, and an `evidence_span` from that action's sentence or clause. Do not rely on one root `action_description` plus flat `village_roles` for multi-action bulletins.
9. For multi-action bulletins, root `action_description` is a bulletin-level summary for humans only, for example "multiple actions across 2 villages". It must not be treated as the per-village condition source when `sub_events` exist or should exist.
10. A single target village must not appear in two conflicting `sub_events` unless the text explicitly uses revision/follow-up language showing that the later action updates or supersedes the earlier one.

## Examples

**Per-village exact:**
«المنصوري: شهيد و3 جرحى؛ مجدل زون: 4 جرحى»

**Bulletin aggregate:**
«غارة على المنصوري ومجدل زون أدت إلى 5 شهداء» (no per-village breakdown)

**One fuzzy area, not two incidents:**
«القوات الإسرائيلية أحرقت حقول الزيتون وبساتين الحمضيات في محيط مجدل زون وبيوت السياد بإطلاق قنابل فوسفورية» → one target location, `مجدل زون`, with `بيوت السياد` retained as an alternate area candidate and manual review required. Do not emit two target entries and do not set the bulletin as a genuine multi-village event.

«قصف قرب X وY» and «قصف بين X وY» without a named road or route likewise describe one fuzzy area. A route such as «قصف على طريق عام X - Y» remains two endpoints in one event.

**Two genuine strikes, distinct-event connector:**
«...طالت الغارات أطراف بلدة زوطر الشرقية في اتجاه ميفدون... كما طال القصف حرج بلدة عيتا الجبل في قضاء بنت جبيل» → two target villages, `زوطر الشرقية` and `عيتا الجبل`, each with its own village_roles entry (and, if described as separate actions, its own sub_event). Do not drop the second village and do not collapse it the way a محيط/بين phrase is collapsed — «كما طال» explicitly marks it as a second, separately scoped strike.

**Two villages, two different actions:**
Confirmed failure shape: a CNRS bulletin named Talloussa and Beit Yahoun. Talloussa's sentence described `ØªÙ…Ø´ÙŠØ·` / sweeping operations. Beit Yahoun's sentence described `Ù‚Ù†Ø§Ø¨Ù„ Ù…Ø¶ÙŠØ¦Ø© ÙˆØ­Ø§Ø±Ù‚Ø©` / illumination-incendiary shelling.

Wrong output: `action_description="Sweeping Operations"`, flat `village_roles` containing both Talloussa and Beit Yahoun, and `sub_events=[]`. This incorrectly stamps sweeping onto Beit Yahoun.

Correct output: `action_description="multiple actions across 2 villages"` plus two `sub_events`: one with `locations=[{"village":"Talloussa","role":"target",...}]`, `action_text="ØªÙ…Ø´ÙŠØ·"`, and the Talloussa sentence as `evidence_span`; one with `locations=[{"village":"Beit Yahoun","role":"target",...}]`, `action_text="Ù‚Ù†Ø§Ø¨Ù„ Ù…Ø¶ÙŠØ¦Ø© ÙˆØ­Ø§Ø±Ù‚Ø©"`, and the Beit Yahoun sentence as `evidence_span`.

**Dash route / endpoints:**
«استهدف دراجة نارية على طريق عام مرج حاروف - زبدين» → village=["حاروف","زبدين"] (two target endpoints)
«غارة بين كفرتبنيت وزوطر الشرقية» → village=["كفرتبنيت"] with `زوطر الشرقية` as review context (one fuzzy target, not two endpoint incidents)
«غارة على طريق بين كفرتبنيت وزوطر الشرقية» → village=["كفرتبنيت","زوطر الشرقية"] (two route endpoints in one route event)

**Single target with qualifier / neighborhood:**
«غارة على بلدة كفررمان - حي الميدان» → village=["كفررمان"], village_roles=[{"village":"كفررمان","role":"target","qualifier_text":"حي الميدان"}]
«قصف على مزرعة حلتا - كفرشوبا» → village=["مزرعة حلتا"], village_roles=[{"village":"مزرعة حلتا","role":"target","qualifier_text":"كفرشوبا"}]
«غارة على مزرعة الحمرا - زوطر وتلة علي الطاهر» → village=["مزرعة الحمرا"], village_roles=[{"village":"مزرعة الحمرا","role":"target","qualifier_text":"زوطر وتلة علي الطاهر"}]
«غارة على بلدة المنصوري - حي غزاله» → village=["المنصوري"], qualifier_text="حي غزاله"
«غارة على بلدة كفررمان - النبطية» → village=["كفررمان"], qualifier_text="النبطية"
«غارة على بلدة الرمادية - قضاء صور» → village=["الرمادية"], qualifier_text="قضاء صور"
«غارة على بلدة المنصوري - بيوت السياد» → village=["المنصوري"], qualifier_text="بيوت السياد"

## Materialization note (downstream)

Multi-village bulletins suppress per-category casualty fields at Tier 2 until manually confirmed per village.
