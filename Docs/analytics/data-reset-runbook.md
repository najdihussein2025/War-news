# Analytics data reset runbook

Run on the dev stack first, then on the deployment stack. Nothing here is automatic.
Commands are PowerShell. Dev stack prefix: `docker compose -p war-news-dev -f docker-compose.dev.yml`.
Deployment prefix: `docker compose`. Shown below for the dev stack; drop the `-p ... -f ...` for deployment.

Order matters: the archive must exist and be verified before a single incident is deleted.

1. **Backup** (custom-format dump, kept outside the repo)

   ```powershell
   docker compose -p war-news-dev -f docker-compose.dev.yml exec -T db pg_dump -U postgres -Fc war_news_dev_test -f /tmp/pre_reset.dump
   docker compose -p war-news-dev -f docker-compose.dev.yml cp db:/tmp/pre_reset.dump .\backups\pre_reset.dump
   ```

2. **Archive** all incidents (deleted and rejected included) into `incidents_archive`

   ```powershell
   docker compose -p war-news-dev -f docker-compose.dev.yml exec backend python -m scripts.analytics_archive_incidents --batch pre_reset_2026_10
   docker compose -p war-news-dev -f docker-compose.dev.yml exec backend python -m scripts.analytics_archive_incidents --batch pre_reset_2026_10 --apply
   ```

   It refuses an existing batch name and rolls back unless archive counts per
   verification_status x is_deleted (and deaths/injuries sums) equal the live table.

3. **Verify** the archived counts: the `--apply` output prints them. Compare with the dry-run
   (the recon counted 3,570 incidents) and spot check with SQL:

   ```powershell
   docker compose -p war-news-dev -f docker-compose.dev.yml exec db psql -U postgres -d war_news_dev_test -c "SELECT archive_batch, count(*), min(event_date), max(event_date) FROM incidents_archive GROUP BY 1"
   ```

3b. **Build the frozen archive facts, then refresh live facts** (live facts skip archived ids, so there is no gap or double count):

   ```powershell
   docker compose -p war-news-dev -f docker-compose.dev.yml exec backend python -m scripts.analytics_refresh_sweep --archive-batch pre_reset_2026_10 --apply
   docker compose -p war-news-dev -f docker-compose.dev.yml exec backend python -m scripts.analytics_refresh_sweep --full
   ```

4. **Excel human copy**: export the incidents workbook from the admin panel (or `incident_excel_view`). It is a
   readable copy only; it does not carry ids, verification status or the shared-toll marker.

5. **Reset**, by hand, in one transaction, with the dirty-mark guard on:
   open `scripts/manual/analytics_data_reset_TEMPLATE.sql`, review it, replace `NAME`, uncomment the
   deletes you want, and run it in `psql`. The first statement after `BEGIN` is
   `SET LOCAL analytics.skip_dirty_marks = 'on'`, so the delete does not queue thousands of dates.
   The template ends in `ROLLBACK`; change it to `COMMIT` only when the counts are as expected.

6. **Refresh** live facts after the reset (archive facts stay untouched):

   ```powershell
   docker compose -p war-news-dev -f docker-compose.dev.yml exec backend python -m scripts.analytics_refresh_sweep --full
   ```

Afterwards the Analytics page shows archive history plus live data. The archive cut-off date is
shown in the footer (`GET /api/analytics/meta`).
