SELECT id, message_datetime, left(replace(raw_text, E'\n', ' '), 300)
FROM raw_messages
WHERE (raw_text ILIKE '%جثمان%' OR raw_text ILIKE '%ينعى%' OR raw_text ILIKE '%تنعى%' OR raw_text ILIKE '%تزف%')
  AND received_at > now() - interval '60 days'
ORDER BY received_at DESC
LIMIT 50;
