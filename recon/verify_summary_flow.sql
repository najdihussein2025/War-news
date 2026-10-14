-- Read-only summary-flow verification queries. T0 is the deployment backend image creation time:
-- 2026-10-08 11:12:55+00, used because no summary row exists from which to derive an earlier flow timestamp.

-- A1: raw messages per source/hour in the last 72 hours.
SELECT date_trunc('hour', received_at) AS hour_utc, source_name, count(*) AS messages
FROM raw_messages
WHERE received_at >= now() - interval '72 hours'
GROUP BY 1, 2 ORDER BY 1, 2;
SELECT count(*) AS missing_hours FROM generate_series(date_trunc('hour', now() - interval '72 hours'), date_trunc('hour', now()), interval '1 hour') h
WHERE NOT EXISTS (SELECT 1 FROM raw_messages r WHERE r.received_at >= h AND r.received_at < h + interval '1 hour');

-- A2: raw-message status breakdown since T0.
SELECT status::text AS status, count(*) AS messages
FROM raw_messages WHERE received_at >= timestamptz '2026-10-08 11:12:55+00'
GROUP BY 1 ORDER BY 1;

-- A3: non-final raw messages older than two hours (examples).
SELECT id, source_name, status::text, received_at, left(raw_text, 80) AS text
FROM raw_messages
WHERE received_at >= timestamptz '2026-10-08 11:12:55+00' AND received_at < now() - interval '2 hours'
  AND status::text IN ('pending', 'parsed')
ORDER BY received_at LIMIT 5;
SELECT count(*) AS stuck_non_final FROM raw_messages
WHERE received_at >= timestamptz '2026-10-08 11:12:55+00' AND received_at < now() - interval '2 hours'
  AND status::text IN ('pending', 'parsed');

-- A4: normal (non-summary) incident counts by event day since T0 and the preceding seven days.
SELECT CASE WHEN i.created_at >= timestamptz '2026-10-08 11:12:55+00' THEN 'since_T0' ELSE 'prior_7d' END AS period,
       i.created_at::date AS day, count(*) AS normal_incidents
FROM incidents i
WHERE i.created_at >= timestamptz '2026-10-01 11:12:55+00'
  AND i.origin::text IS DISTINCT FROM 'summary'
GROUP BY 1, 2 ORDER BY 1, 2;

-- B1/B4: detected summaries, by channel/status, and any delayed unreconciled summaries.
SELECT channel, status::text, count(*) AS summaries
FROM summary_bulletins WHERE created_at >= timestamptz '2026-10-08 11:12:55+00'
GROUP BY 1, 2 ORDER BY 1, 2;
SELECT id, raw_message_id, channel, status::text, process_after, created_at
FROM summary_bulletins
WHERE created_at >= timestamptz '2026-10-08 11:12:55+00'
  AND status::text NOT IN ('reconciled', 'needs_review', 'failed', 'skipped_repost')
  AND process_after < now() - interval '1 hour'
ORDER BY process_after LIMIT 5;

-- B2: trigger-text messages that were not detected, with normal-path incident count.
SELECT r.id, r.source_name, r.status::text, r.received_at, count(i.id) AS incident_rows, left(r.raw_text, 80) AS text
FROM raw_messages r LEFT JOIN summary_bulletins s ON s.raw_message_id = r.id
LEFT JOIN incidents i ON i.raw_message_id = r.id
WHERE r.received_at >= timestamptz '2026-10-08 11:12:55+00' AND r.raw_text ILIKE '%ملخص%' AND s.id IS NULL
GROUP BY r.id, r.source_name, r.status, r.received_at, r.raw_text ORDER BY r.received_at LIMIT 100;

-- B3: detected summaries that fell back to the normal path.
SELECT s.id, s.raw_message_id, s.channel, s.status::text, r.status::text AS raw_status, count(i.id) AS incident_rows, left(r.raw_text, 80) AS text
FROM summary_bulletins s JOIN raw_messages r ON r.id=s.raw_message_id LEFT JOIN incidents i ON i.raw_message_id=r.id
WHERE s.created_at >= timestamptz '2026-10-08 11:12:55+00'
GROUP BY s.id, s.raw_message_id, s.channel, s.status, r.status, r.raw_text ORDER BY s.id LIMIT 100;

-- C1-C6: summary-created totals, duplicate guards, reposts, reconciliation duplication, and casualty fields.
SELECT created_at::date AS day, count(*) AS summary_incidents FROM incidents WHERE origin::text='summary' AND created_at >= timestamptz '2026-10-08 11:12:55+00' GROUP BY 1 ORDER BY 1;
SELECT a.id AS summary_incident_id, b.id AS other_incident_id, v.ref_name_ar AS village, a.condition_id, a.event_date, b.event_date
FROM incidents a JOIN incidents b ON b.id<>a.id AND b.village_id=a.village_id AND b.condition_id=a.condition_id AND b.event_date BETWEEN a.event_date-1 AND a.event_date+1
JOIN villages v ON v.id=a.village_id
WHERE a.origin::text='summary' AND a.created_at >= timestamptz '2026-10-08 11:12:55+00' LIMIT 5;
SELECT village_id, condition_id, event_date, count(*) AS rows FROM incidents WHERE origin::text='summary' AND created_at >= timestamptz '2026-10-08 11:12:55+00' GROUP BY 1,2,3 HAVING count(*)>1 LIMIT 5;
SELECT fingerprint, count(*) AS summaries, count(DISTINCT canonical_summary_id) AS canonical_ids FROM summary_bulletins WHERE created_at >= timestamptz '2026-10-08 11:12:55+00' GROUP BY 1 HAVING count(*)>1 LIMIT 5;
SELECT raw_message_id, count(*) AS reconciliation_rows FROM summary_bulletins WHERE created_at >= timestamptz '2026-10-08 11:12:55+00' GROUP BY 1 HAVING count(*)>1 LIMIT 5;
SELECT id, total_deaths, total_injuries, deaths, injuries, created_at FROM incidents WHERE origin::text='summary' AND created_at >= timestamptz '2026-10-08 11:12:55+00' AND (coalesce(total_deaths,0)<>0 OR coalesce(total_injuries,0)<>0 OR coalesce(deaths,0)<>0 OR coalesce(injuries,0)<>0) LIMIT 5;

-- D1-D2: live rows after a summary-origin incident for the same village/condition/day window.
SELECT s.id AS summary_incident_id, l.id AS live_incident_id, v.ref_name_ar AS village, s.event_date AS summary_day, l.event_date AS live_day, l.source_summary_item_id
FROM incidents s JOIN incidents l ON l.origin::text IS DISTINCT FROM 'summary' AND l.village_id=s.village_id AND l.condition_id=s.condition_id AND l.event_date BETWEEN s.event_date-1 AND s.event_date+1 AND l.created_at>s.created_at
JOIN villages v ON v.id=s.village_id WHERE s.origin::text='summary' AND s.created_at >= timestamptz '2026-10-08 11:12:55+00' LIMIT 5;

-- E1-E3: confirmation-note population and duplicate/field-change proxies.
SELECT count(*) AS confirmation_notes FROM incidents WHERE note ILIKE '%مؤكد في ملخص%' AND updated_at >= timestamptz '2026-10-08 11:12:55+00';
SELECT id, left(note, 160) AS note FROM incidents
WHERE note ILIKE '%مؤكد في ملخص%'
  AND strpos(substring(note FROM strpos(note, 'مؤكد في ملخص') + 1), 'مؤكد في ملخص') > 0 LIMIT 5;

-- F1-F3: soft-delete audit and constraint presence.
SELECT id, deleted_reason, updated_at FROM incidents WHERE is_deleted AND deleted_reason IS NULL AND updated_at >= timestamptz '2026-10-08 11:12:55+00' LIMIT 5;
SELECT coalesce(deleted_reason,'(null)') AS reason, count(*) FROM incidents WHERE is_deleted AND updated_at >= timestamptz '2026-10-08 11:12:55+00' GROUP BY 1 ORDER BY 2 DESC;
SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid='incidents'::regclass AND conname='ck_incidents_deleted_has_reason';

-- G1: review-queue size and one-task-per-summary guard.
SELECT status::text, count(*) FROM summary_review_tasks GROUP BY 1 ORDER BY 1;
SELECT summary_id, count(*) AS review_entries FROM summary_review_tasks GROUP BY summary_id HAVING count(*)>1 LIMIT 5;
