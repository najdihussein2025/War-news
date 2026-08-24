-- Opt-in: mark a source as trusted so Step A relevance classification is skipped.
-- Do not run this as part of a pipeline reset. Review the source id first.
--
-- Example: CNRS Webhook (source id 3):
--   UPDATE sources SET config = config || '{"trusted": true}'::jsonb WHERE id = 3;
--
-- Any source can be marked the same way. The pipeline reads sources.config.trusted
-- as a JSON boolean (Python `is True`), not the string 'true'.

UPDATE sources
SET config = config || '{"trusted": true}'::jsonb
WHERE id = 3;
