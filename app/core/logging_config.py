from __future__ import annotations

import logging
import sys

_CONFIGURED = False
_LOG_FORMAT = "%(levelname)s:     %(name)s %(message)s"


def configure_logging(*, level: int = logging.INFO) -> None:
    """Send app loggers to stdout so they appear in `docker compose logs`.

    Without this, INFO lines from `logging.getLogger(__name__)` never reach
    Docker: the root logger has no handlers, so Python's lastResort handler
    only emits WARNING and above (which is why extraction warnings showed up
    while orchestrator INFO lines did not).
    """
    global _CONFIGURED
    if _CONFIGURED:
        return

    root = logging.getLogger()
    root.setLevel(level)

    has_stream_handler = any(
        isinstance(handler, logging.StreamHandler)
        and getattr(handler, "stream", None) in (sys.stdout, sys.stderr)
        for handler in root.handlers
    )
    if not has_stream_handler:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(level)
        handler.setFormatter(logging.Formatter(_LOG_FORMAT))
        root.addHandler(handler)

    logging.getLogger("app").setLevel(level)
    _CONFIGURED = True
