# Casualty backfill

After taking and verifying a database backup, run `01` and review every row.
Run `02` only for the reviewed contamination set. Review `03`, then run `04`
to establish first-mentioned owners and members. Run `05` for numberless
mentions, and finish with read-only `06`.

The write scripts use transactions and retain before-images in dated backup
tables. To roll back data, restore matching rows from those backup tables in a
new reviewed transaction and add compensating `incident_updates` audit rows.
Do not delete the backup tables until the live review is complete.
