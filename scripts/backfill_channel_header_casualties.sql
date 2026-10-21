-- Read-only review queries for scripts/backfill_channel_header_casualties.py.
-- NOT executed by the script or by the assistant: run them yourself, e.g.
--   docker compose exec db psql -U <user> -d war_news_dev -f /path/to/this.sql
-- Nothing here writes; the backfill itself only writes with --apply.

-- 1. Live incidents with deaths whose own message starts with a page header containing «الشهيد».
SELECT i.id, i.event_date, i.village_display_name, i.deaths, i.total_deaths, i.casualty_status, i.raw_message_id
FROM incidents i
JOIN raw_messages r ON r.id = i.raw_message_id
WHERE i.is_deleted = false
  AND COALESCE(i.deaths, 0) > 0
  AND split_part(regexp_replace(r.raw_text, E'\r', '', 'g'), E'\n', 1) ~ 'الإعلامي\s+الشهيد|الاعلامي\s+الشهيد'
ORDER BY i.event_date DESC;

-- 2. Casualty numbers with no casualty keyword anywhere in the stored khabar text.
SELECT i.id, i.event_date, i.village_display_name, i.deaths, i.injuries, i.total_deaths, i.total_injuries
FROM incidents i
WHERE i.is_deleted = false
  AND (COALESCE(i.total_deaths, 0) > 0 OR COALESCE(i.total_injuries, 0) > 0)
  AND i.khabar !~ '(شهيد|شهداء|استشهد|ارتقى|ارتقاء|قتيل|قتلى|جريح|جرحى|مصاب|إصابة|اصابة|جراح)'
ORDER BY i.event_date DESC;

-- 3. Numbers next to casualty_status = 'none_mentioned'.
SELECT i.id, i.event_date, i.village_display_name, i.deaths, i.injuries, i.casualty_status
FROM incidents i
WHERE i.is_deleted = false
  AND i.casualty_status = 'none_mentioned'
  AND (COALESCE(i.deaths, 0) > 0 OR COALESCE(i.injuries, 0) > 0
       OR COALESCE(i.total_deaths, 0) > 0 OR COALESCE(i.total_injuries, 0) > 0);

-- 4. Rows the backfill will skip (admin edit with a user, or verified).
SELECT i.id, i.verified_by_user_id IS NOT NULL AS verified,
       EXISTS (SELECT 1 FROM incident_updates u
               WHERE u.incident_id = i.id AND u.action = 'edit' AND u.performed_by IS NOT NULL) AS admin_edited
FROM incidents i
WHERE i.is_deleted = false
  AND (i.verified_by_user_id IS NOT NULL
       OR EXISTS (SELECT 1 FROM incident_updates u
                  WHERE u.incident_id = i.id AND u.action = 'edit' AND u.performed_by IS NOT NULL));
