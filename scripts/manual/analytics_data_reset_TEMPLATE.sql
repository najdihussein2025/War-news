-- ============================================================================
-- MANUAL ONLY. DO NOT RUN FROM ANY SCRIPT, WORKER OR CI.
-- Template for the analytics data reset. Hussein reviews and edits this, then
-- runs it by hand inside psql, ONLY after the runbook steps 1-4
-- (Docs/analytics/data-reset-runbook.md): backup, archive --apply, archive
-- verified, Excel copy, archive facts built.
-- ============================================================================
BEGIN;

-- Without this, the mass delete would queue every date in analytics_dirty_dates.
SET LOCAL analytics.skip_dirty_marks = 'on';

-- Safety gate: abort unless the archive holds exactly what is about to be deleted.
-- Replace NAME with the archive batch.
DO $$
DECLARE live_rows bigint; archived bigint;
BEGIN
    SELECT count(*) INTO live_rows FROM incidents;
    SELECT count(*) INTO archived FROM incidents_archive WHERE archive_batch = 'NAME';
    IF live_rows <> archived OR archived = 0 THEN
        RAISE EXCEPTION 'archive (%) does not match incidents (%); aborting reset', archived, live_rows;
    END IF;
END $$;

-- Deleting incidents cascades to incident_details, incident_updates, duplicate_matches and
-- incident_verification_flags; bulletin members/owners and summary_items are SET NULL.
-- DELETE FROM incidents;

-- DECIDE (not part of the analytics design): raw_messages, summary_bulletins, bulletin_casualty_groups,
-- air_violations. Air-violation facts are rebuilt from air_violations, so keep it unless you
-- intend to reset that history too.

-- Inspect, then COMMIT (or ROLLBACK).
-- SELECT count(*) FROM incidents;
ROLLBACK;  -- change to COMMIT only when you are certain
