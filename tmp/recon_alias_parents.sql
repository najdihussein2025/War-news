SELECT id, acs_code, acs_name, ref_name_ar, caza_ar
FROM villages
WHERE id IN (1228, 144, 970, 1397, 678);

SELECT COUNT(*) AS qantara_to_akkar_14d
FROM raw_messages r
WHERE r.message_datetime >= NOW() - INTERVAL '14 days'
  AND r.match_result @> '[{"matched_village_id": 1229}]'::jsonb
  AND (
    r.raw_text ILIKE '%القنطرة%'
    OR r.extraction_result::text ILIKE '%القنطرة%'
  );
