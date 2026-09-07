from __future__ import annotations

import asyncio
import logging
import select
from collections.abc import Callable
from typing import Any

from sqlalchemy.engine import make_url

from app.core.config import settings

logger = logging.getLogger(__name__)

CHANNEL = "new_incident"


class IncidentEventStream:
    def __init__(
        self,
        *,
        connect: Callable[..., Any] | None = None,
        queue_size: int = 100,
    ) -> None:
        self._connect = connect
        self._queue_size = queue_size
        self._subscribers: set[asyncio.Queue[str]] = set()
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None
        self._stop_event: asyncio.Event | None = None
        self._connection: Any | None = None

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(self._listen_loop(), name="incident-event-listener")

    async def stop(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()
        if self._task is not None:
            await self._task
        self._task = None
        self._stop_event = None
        connection = self._connection
        self._connection = None
        if connection is not None:
            await asyncio.to_thread(connection.close)

    async def subscribe(self) -> asyncio.Queue[str]:
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=self._queue_size)
        async with self._lock:
            self._subscribers.add(queue)
        return queue

    async def unsubscribe(self, queue: asyncio.Queue[str]) -> None:
        async with self._lock:
            self._subscribers.discard(queue)

    async def broadcast(self, payload: str) -> None:
        async with self._lock:
            subscribers = tuple(self._subscribers)
        for queue in subscribers:
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                logger.warning("Dropping new_incident event for slow SSE subscriber")

    async def _listen_loop(self) -> None:
        stop_event = self._stop_event
        if stop_event is None:
            return
        while not stop_event.is_set():
            connection = None
            try:
                connection = await asyncio.to_thread(self._open_connection)
                self._connection = connection
                cursor = connection.cursor()
                cursor.execute(f"LISTEN {CHANNEL};")
                cursor.close()
                logger.info("Listening for Postgres NOTIFY channel=%s", CHANNEL)

                while not stop_event.is_set():
                    ready = await asyncio.to_thread(select.select, [connection], [], [], 1)
                    if not ready[0]:
                        continue
                    connection.poll()
                    while connection.notifies:
                        notification = connection.notifies.pop(0)
                        await self.broadcast(notification.payload)
            except Exception:
                if not stop_event.is_set():
                    logger.exception("Incident event listener failed; retrying")
                    await asyncio.sleep(5)
            finally:
                if self._connection is connection:
                    self._connection = None
                if connection is not None:
                    await asyncio.to_thread(connection.close)

    def _open_connection(self) -> Any:
        connect = self._connect
        if connect is None:
            import psycopg2

            connect = psycopg2.connect

        url = make_url(settings.database_url)
        kwargs: dict[str, Any] = {"application_name": f"{settings.pg_application_name}-incident-listen"}
        if url.host:
            kwargs["host"] = url.host
        if url.port:
            kwargs["port"] = url.port
        if url.database:
            kwargs["dbname"] = url.database
        if url.username:
            kwargs["user"] = url.username
        if url.password:
            kwargs["password"] = url.password

        connection = connect(**kwargs)
        connection.set_isolation_level(0)
        return connection


incident_event_stream = IncidentEventStream()
