SELECT id, message_datetime, left(replace(raw_text, E'\n', ' '), 1200) AS raw_text
FROM raw_messages
WHERE id IN (31824, 31831, 31018, 28576)
ORDER BY id;
