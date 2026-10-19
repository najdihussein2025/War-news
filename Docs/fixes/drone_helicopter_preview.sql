-- Read-only preview of revision 20261019_0081.
SELECT av.id, av.raw_message_id, av.condition_id AS old_condition_id, 36 AS new_condition_id,
       av.khabar, rm.raw_text
FROM air_violations av LEFT JOIN raw_messages rm ON rm.id=av.raw_message_id
WHERE av.condition_id=38
  AND (av.khabar LIKE '%مسير%' OR av.khabar LIKE '%مسيّر%' OR av.khabar LIKE '%محلقة%'
       OR COALESCE(rm.raw_text,'') LIKE '%مسير%' OR COALESCE(rm.raw_text,'') LIKE '%مسيّر%'
       OR COALESCE(rm.raw_text,'') LIKE '%محلقة%')
  AND av.khabar NOT LIKE '%مروحي%' AND av.khabar NOT LIKE '%هليكوبتر%'
ORDER BY av.id;
