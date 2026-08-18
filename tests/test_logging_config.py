from __future__ import annotations

import io
import logging

import app.core.logging_config as logging_config
from app.core.logging_config import configure_logging


def test_configure_logging_routes_info_to_stdout(monkeypatch) -> None:
    logging_config._CONFIGURED = False
    stream = io.StringIO()
    monkeypatch.setattr("sys.stdout", stream)

    root = logging.getLogger()
    existing_handlers = list(root.handlers)
    for handler in existing_handlers:
        root.removeHandler(handler)

    try:
        configure_logging()
        logging.getLogger("app.news.services.pipeline_orchestrator").info(
            "Pipeline sweep triggered max_rows=%s",
            1,
        )
        output = stream.getvalue()
    finally:
        for handler in list(root.handlers):
            if handler not in existing_handlers:
                root.removeHandler(handler)
        for handler in existing_handlers:
            root.addHandler(handler)
        logging_config._CONFIGURED = False

    assert "Pipeline sweep triggered max_rows=1" in output
    assert "app.news.services.pipeline_orchestrator" in output
