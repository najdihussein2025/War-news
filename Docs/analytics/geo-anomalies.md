# Geo anomalies

## Hardine / Haddatha review (October 2026)

The reported cluster in **Hardine, El Batroun** is a matching anomaly requiring review, not evidence of confirmed activity in North Lebanon. The original investigation identified the likely intended village as **Haddatha, Bint Jbeil**: the source spelling `حداثا` can be transliterated by the LLM as `Hardinga`, after which trigram matching can select the similarly named Hardine record.

### Deployment evidence (SELECT-only, 2026-10-21)

The following query was run against `war_news_dev`; it returned **25 active rows**, resolving the earlier 21-versus-25 count discrepancy:

```sql
SELECT i.event_date, c.action_en, left(i.khabar, 200) AS khabar
FROM incidents i
JOIN villages v ON v.id = i.village_id
JOIN conditions c ON c.id = i.condition_id
WHERE v.ref_name_en ILIKE 'Hardine%' AND NOT i.is_deleted
ORDER BY i.event_date;
```

The evidence is unambiguous: the first row (2026-08-27) says “Artillery shelling between the towns of Haris and Hadatha”; later rows explicitly say `قصف مدفعي اسرائيلي استهدف حداثا` (5 October), `غارة على حداثا` (18 October), and “between Haddatha and Haris” (16 October). The rows run from 27 August through 19 October and contain artillery shelling, bombs, and flares, not 21 actual Hardine airstrikes.

No incident data was changed. Before a separately approved correction, export the affected incident IDs together with the raw village string and match score so the reassignment remains auditable.

Proposed matching fix: add Haddatha aliases for the observed Latin spellings, including `Hardinga`, in the LLM terminology and village alias catalog, then add a matching regression test. This is a future-ingestion fix only; it must not silently rewrite historical rows.

Existing incident rows were deliberately not moved in this change. They need a separately reviewed data-correction run, with the original message, match score, and affected incident IDs retained as evidence before any reassignment.

## Automated review

The Analytics data-quality endpoint lists villages outside the configured conflict-zone cazas when their incident count exceeds `analytics_geo_anomaly_min_incidents` for the selected period. This is a review signal, not an automatic correction.
