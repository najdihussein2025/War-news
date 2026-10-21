SELECT id, message_datetime, left(replace(raw_text, E'\n', ' '), 300) AS raw_text,
       extraction_result
FROM raw_messages
WHERE received_at > now() - interval '48 hours'
  AND raw_text ILIKE '%صفحة الإعلامي الشهيد علي شعيب%'
  AND (
    coalesce((extraction_result #>> '{casualties,deaths}')::integer, 0) > 0
    OR coalesce((extraction_result #>> '{casualties,total_deaths}')::integer, 0) > 0
  )
ORDER BY received_at DESC;
