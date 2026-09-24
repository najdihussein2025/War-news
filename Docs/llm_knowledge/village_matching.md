# Village matching rules

## Fuzzy match thresholds

- `MATCH_THRESHOLD = 0.6` for confident match.
- `LOW_CONFIDENCE_THRESHOLD = 0.35` for review-tier match.
- `MATCH_TIE_MARGIN = 0.05` - if top two scores differ by less than this at >=0.6, demote to `matched_low_confidence`.

## Collision detection

When >=2 candidates share the same `ref_name_ar` prefix as the mention (e.g. five *النبطية* villages at ~0.615), treat as collision-like and demote confidence.

## Location aliases

Evidence-backed aliases in `village_location_aliases` resolve exact normalized mentions to a parent village ACS row (e.g. «النبطية» -> Nabatieh Et-Tahta 71111, «حي المسلخ» -> same).

Do not fuzzy-match bare ambiguous tokens without alias when multiple ACS rows tie.

No-ACS local/colloquial names that have been confirmed against an ACS parent must be exact aliases, not fuzzy matches. The news-side phrase remains the incident display label, while matching, caza/mohafaza, coordinates, condition logic, and dedup use the parent ACS village row. `terminology/village_aliases.yaml` and `Data/VillageLocationAliases.json` are the source of truth for these mappings.

Specific collision guards:
- «وادي السلوقي», «السلوقي», and spelling/Latin variants in recurring south-Lebanon Wadi el-Selouqi bulletins resolve to Touline / تولين (ACS 73282). Do not allow trigram similarity to resolve those mentions to Slouqi/Slouky Baalbek (ACS 53423).
- Confirmed no-ACS aliases such as «وادي راج» -> Zaoutar Ech-Charqiye (ACS 71367), «الدبشة» and «جبل الرفيع» -> Kfar Roummane (ACS 71133), and «بيوت السياد» -> Mansouri Sour (ACS 62296) must resolve through aliases. Preserve each distinct Arabic news phrase as the displayed village name.
- News-form ACS spelling gaps: bare «دبل» resolves to Debl (ACS 72281; ACS Arabic is «دبل امية»), and «الجبين» resolves to Jibbayn (ACS 62292; ACS Arabic is «جبين»). Prefer exact aliases over fuzzy for short definite-article or truncated gazetteer forms.

## Geo-context disambiguation

When fuzzy scores tie and candidates have coordinates:
- Prefer candidate nearest to an already-resolved anchor village in the same bulletin.
- Requires minimum distance advantage over original top candidate.

## Condition disambiguation tokens

Some condition IDs require distinguishing substrings in the action text:
- ID 2 (warning raid): requires «تحذيريه»
- ID 39 (feigned attack): requires «وهميه»

## Dash-route extraction (upstream)

Before matching, Tier 1 should split `طريق ... X - Y` into two village mentions for separate match attempts.
