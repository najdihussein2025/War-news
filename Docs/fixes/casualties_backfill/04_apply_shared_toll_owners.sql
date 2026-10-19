BEGIN;
CREATE TABLE IF NOT EXISTS casualties_shared_toll_backup_20261019 AS
SELECT g.*, now() AS backed_up_at FROM bulletin_casualty_groups g WHERE false;
INSERT INTO casualties_shared_toll_backup_20261019 SELECT g.*, now() FROM bulletin_casualty_groups g
WHERE g.casualty_scope='bulletin_aggregate' ON CONFLICT DO NOTHING;
UPDATE bulletin_casualty_groups g SET owner_incident_id=m.incident_id, owner_village_id=m.village_id
FROM bulletin_casualty_group_members m WHERE m.group_id=g.id AND m.ordinal=0 AND g.casualty_scope='bulletin_aggregate';
UPDATE incidents i SET total_deaths=CASE WHEN i.id=g.owner_incident_id THEN g.total_deaths ELSE NULL END,
 total_injuries=CASE WHEN i.id=g.owner_incident_id THEN g.total_injuries ELSE NULL END,
 casualty_status='aggregate_only', verification_status='needs_verification', version=i.version+1
FROM bulletin_casualty_group_members m JOIN bulletin_casualty_groups g ON g.id=m.group_id
WHERE i.id=m.incident_id AND g.casualty_scope='bulletin_aggregate';
INSERT INTO incident_updates (incident_id, action, old_values, new_values, created_at)
SELECT m.incident_id, 'edit', '{}'::jsonb, jsonb_build_object('reason','shared_toll_owner_backfill','group_id',g.id), now()
FROM bulletin_casualty_group_members m JOIN bulletin_casualty_groups g ON g.id=m.group_id WHERE g.casualty_scope='bulletin_aggregate';
COMMIT;
