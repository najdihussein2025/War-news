import logging

logger = logging.getLogger("uvicorn.error")

_scheduler = None


def start_scheduler() -> None:
    logger.info("CNRS polling scheduler disabled; webhook ingestion remains active")


def stop_scheduler() -> None:
    return
