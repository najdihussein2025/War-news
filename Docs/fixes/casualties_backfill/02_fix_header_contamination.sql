BEGIN;
CREATE TABLE IF NOT EXISTS casualties_header_fix_backup_20261019 AS
SELECT i.*, now() AS backed_up_at FROM incidents i WHERE false;
WITH candidates AS (
  SELECT i.* FROM incidents i
  WHERE NOT i.is_deleted AND (COALESCE(i.quality_flags::text, '') ILIKE '%header%' OR COALESCE(i.quality_flags::text, '') ILIKE '%memorial%')
), saved AS (
  INSERT INTO casualties_header_fix_backup_20261019 SELECT candidates.*, now() FROM candidates
  ON CONFLICT DO NOTHING RETURNING id
), changed AS (
  UPDATE incidents i SET total_deaths=NULL, total_injuries=NULL, deaths=NULL, injuries=NULL, casualty_status='none_mentioned', version=i.version+1
  FROM saved WHERE i.id=saved.id RETURNING i.id
)
INSERT INTO incident_updates (incident_id, action, old_values, new_values, created_at)
SELECT b.id, 'edit', jsonb_build_object('total_deaths',b.total_deaths,'total_injuries',b.total_injuries), jsonb_build_object('total_deaths',NULL,'total_injuries',NULL,'reason','header_contamination_backfill'), now()
FROM casualties_header_fix_backup_20261019 b JOIN changed c ON c.id=b.id;
COMMIT;
