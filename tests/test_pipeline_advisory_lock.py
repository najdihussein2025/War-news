from app.news.services.pipeline_advisory_lock import (
    AdvisoryLockHolder,
    is_stale_pipeline_lock_holder,
)


def test_backend_idle_lock_holder_is_stale() -> None:
    holder = AdvisoryLockHolder(
        pid=15206,
        application_name="war-news-backend",
        state="idle in transaction",
        wait_event_type="Client",
        query="SELECT pg_try_advisory_lock(84729103)",
    )
    assert is_stale_pipeline_lock_holder(holder) is True


def test_live_pipeline_worker_lock_is_not_stale_on_backend_startup() -> None:
    holder = AdvisoryLockHolder(
        pid=99,
        application_name="war-news-pipeline",
        state="idle",
        wait_event_type="Client",
        query="SELECT pg_try_advisory_lock(84729103)",
    )
    assert is_stale_pipeline_lock_holder(holder, reclaim_other_workers=False) is False


def test_singleton_worker_startup_reclaims_other_pipeline_pids() -> None:
    holder = AdvisoryLockHolder(
        pid=99,
        application_name="war-news-pipeline",
        state="idle",
        wait_event_type="Client",
        query="SELECT pg_try_advisory_lock(84729103)",
    )
    assert is_stale_pipeline_lock_holder(holder, reclaim_other_workers=True) is True
