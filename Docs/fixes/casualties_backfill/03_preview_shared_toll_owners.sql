-- Read-only preview. Ordinal zero is first mention and therefore owner.
SELECT g.id AS group_id, g.raw_message_id, m.incident_id AS computed_owner_incident_id,
       m.village_id AS computed_owner_village_id, g.total_deaths, g.total_injuries
FROM bulletin_casualty_groups g
JOIN bulletin_casualty_group_members m ON m.group_id=g.id AND m.ordinal=0
WHERE g.casualty_scope='bulletin_aggregate'
ORDER BY g.id;
