# Drone/helicopter reclassification review

Revision `20261019_0081` changes only `air_violations` currently classified as
helicopter (`condition_id = 38`) whose report or linked raw text contains
`مسير`, `مسيّر`, or `محلقة`, excluding report text that explicitly contains
`مروحي` or `هليكوبتر`. Matching rows become surveillance aircraft
(`condition_id = 36`) and their version is incremented.

The original migration was irreversible. It now copies each affected row's ID,
condition and version to `air_violation_drone_reclass_backup_20261019` before
updating. Downgrade restores those exact values and removes the backup table.

Use `drone_helicopter_preview.sql` to review the live candidate set. It is a
read-only `SELECT`; this repository task did not execute it against live.
