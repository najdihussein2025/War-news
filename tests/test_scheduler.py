from app.core import scheduler
from app.core.config import settings
from types import SimpleNamespace


class _FakeThread:
    def __init__(self, *, target, name, daemon) -> None:
        self.target = target
        self.name = name
        self.daemon = daemon
        self.started = False
        self.joined = False
        self._alive = False

    def start(self) -> None:
        self.started = True
        self._alive = True

    def is_alive(self) -> bool:
        return self._alive

    def join(self, timeout=None) -> None:
        self.joined = True
        self._alive = False


def test_cnrs_webhook_source_is_not_polled() -> None:
    assert scheduler._uses_cnrs_polling(
        SimpleNamespace(config={"delivery_method": "webhook"})
    ) is False
    assert scheduler._uses_cnrs_polling(
        SimpleNamespace(config={"delivery_method": "polling"})
    ) is True


def test_start_scheduler_skips_when_red_alert_disabled(monkeypatch) -> None:
    scheduler.stop_scheduler()
    monkeypatch.setattr(settings, "red_alert_enabled", False)

    scheduler.start_scheduler()

    assert scheduler._scheduler_thread is None
    assert scheduler._scheduler_stop_event is None


def test_start_scheduler_can_leave_red_alert_to_dedicated_collector(monkeypatch) -> None:
    scheduler.stop_scheduler()
    monkeypatch.setattr(scheduler.settings, "red_alert_enabled", True)

    scheduler.start_scheduler(start_red_alert=False)

    assert scheduler._scheduler_thread is None
    assert scheduler._scheduler_stop_event is None


def test_start_scheduler_starts_background_thread(monkeypatch) -> None:
    scheduler.stop_scheduler()
    monkeypatch.setattr(settings, "red_alert_enabled", True)
    monkeypatch.setattr(scheduler.threading, "Thread", _FakeThread)

    scheduler.start_scheduler()

    assert scheduler._scheduler_stop_event is not None
    assert scheduler._scheduler_thread is not None
    assert scheduler._scheduler_thread.started is True
    assert scheduler._scheduler_thread.name == "red-alert-scheduler"
    assert scheduler._scheduler_thread.daemon is True

    scheduler.stop_scheduler()


def test_stop_scheduler_joins_running_thread(monkeypatch) -> None:
    scheduler.stop_scheduler()
    monkeypatch.setattr(settings, "red_alert_enabled", True)
    monkeypatch.setattr(scheduler.threading, "Thread", _FakeThread)
    scheduler.start_scheduler()

    thread = scheduler._scheduler_thread
    scheduler.stop_scheduler()

    assert thread is not None
    assert thread.joined is True
    assert scheduler._scheduler_thread is None
    assert scheduler._scheduler_stop_event is None
