import json
import logging
from typing import Any

from redis import Redis
from redis.exceptions import RedisError

from app.core.config import settings

logger = logging.getLogger(__name__)

redis_client = Redis.from_url(
    settings.redis_url,
    decode_responses=True,
)


def get_json(key: str) -> Any | None:
    if not settings.cache_enabled:
        return None

    try:
        value = redis_client.get(key)
        return json.loads(value) if value is not None else None
    except (RedisError, json.JSONDecodeError):
        logger.warning("Redis cache read failed key=%s", key)
        return None


def set_json(key: str, value: Any, ttl_seconds: int) -> None:
    if not settings.cache_enabled:
        return

    try:
        redis_client.setex(
            key,
            ttl_seconds,
            json.dumps(value, default=str),
        )
    except RedisError:
        logger.warning("Redis cache write failed key=%s", key)


def delete_keys(*keys: str) -> None:
    if not settings.cache_enabled or not keys:
        return

    try:
        redis_client.delete(*keys)
    except RedisError:
        logger.warning("Redis cache deletion failed keys=%s", keys)


def increment(key: str) -> int:
    if not settings.cache_enabled:
        return 0

    try:
        return int(redis_client.incr(key))
    except RedisError:
        logger.warning("Redis increment failed key=%s", key)
        return 0


def get_cache_version(key: str) -> int:
    if not settings.cache_enabled:
        return 0

    try:
        value = redis_client.get(key)
        return int(value or 0)
    except (RedisError, ValueError):
        logger.warning("Redis version read failed key=%s", key)
        return 0


def redis_is_available() -> bool:
    if not settings.cache_enabled:
        return False

    try:
        return bool(redis_client.ping())
    except RedisError:
        return False
