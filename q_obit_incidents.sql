WITH hits AS (
  SELECT id, message_datetime, left(replace(raw_text, E'\n', ' '), 300) AS raw_text
  FROM raw_messages
  WHERE (raw_text ILIKE '%جثمان%' OR raw_text ILIKE '%ينعى%' OR raw_text ILIKE '%تنعى%' OR raw_text ILIKE '%تزف%')
    AND received_at > now() - interval '60 days'
  ORDER BY received_at DESC
  LIMIT 50
)
SELECT h.id AS raw_message_id, h.message_datetime, i.id AS live_incident_id,
       i.deaths, i.total_deaths, i.casualty_status, i.casualty_deaths_status,
       i.verification_status
FROM hits h
LEFT JOIN incidents i ON i.raw_message_id = h.id AND NOT i.is_deleted
ORDER BY h.message_datetime DESC, i.id;
