BEGIN;
CREATE TABLE IF NOT EXISTS casualties_count_missing_backup_20261019 AS SELECT i.*, now() AS backed_up_at FROM incidents i WHERE false;
WITH candidates AS (
 SELECT i.* FROM incidents i WHERE NOT i.is_deleted AND i.casualty_status='none_mentioned'
 AND i.khabar ~ '(إصابات|جرحى|شهداء)' AND i.khabar !~ '[0-9٠-٩]'
), saved AS (
 INSERT INTO casualties_count_missing_backup_20261019 SELECT candidates.*, now() FROM candidates ON CONFLICT DO NOTHING RETURNING id
)
UPDATE incidents i SET casualty_status='count_missing', verification_status='needs_verification', version=i.version+1 FROM saved WHERE i.id=saved.id;
COMMIT;
