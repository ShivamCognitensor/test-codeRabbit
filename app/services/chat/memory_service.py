from __future__ import annotations

from dataclasses import dataclass

import orjson
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError, TimeoutError as RedisTimeoutError

from app.core.config import get_settings
from app.core.logging import get_logger


logger = get_logger(__name__)


@dataclass
class Message:
    role: str
    content: str


class ConversationMemory:
    """Redis-backed conversation memory (optional). Falls back to in-memory.

    Notes:
    - Always normalizes session_id to str to avoid UUID/str key mismatches.
    - Uses string keys consistently for Redis operations.
    """

    def __init__(self):
        settings = get_settings()
        self._redis_url = settings.redis_url
        self._redis: Redis | None = None
        self._local: dict[str, list[Message]] = {}

    def _key(self, session_id: str) -> str:
        return f"chat:{session_id}"

    async def _get_redis(self) -> Redis | None:
        if not self._redis_url:
            return None
        if self._redis is None:
            self._redis = Redis.from_url(self._redis_url, decode_responses=False)
        return self._redis

    async def get_history(self, session_id: str, limit: int = 20) -> list[Message]:
        sid = str(session_id)
        r = await self._get_redis()
        if not r:
            return self._local.get(sid, [])[-limit:]

        key = self._key(sid)
        try:
            raw = await r.lrange(key, -limit, -1)
        except (RedisConnectionError, RedisTimeoutError, OSError):
            # Redis is down/unreachable; degrade gracefully
            self._redis = None
            return self._local.get(sid, [])[-limit:]

        msgs: list[Message] = []
        for b in raw:
            try:
                obj = orjson.loads(b)
                msgs.append(Message(role=obj["role"], content=obj["content"]))
            except Exception:
                # If one corrupted entry exists, skip it instead of failing the whole request
                continue
        return msgs

    async def append(self, session_id: str, role: str, content: str) -> None:
        sid = str(session_id)
        msg = Message(role=role, content=content)

        # always keep local copy
        self._local.setdefault(sid, []).append(msg)

        r = await self._get_redis()
        if not r:
            return

        key = self._key(sid)
        try:
            await r.rpush(key, orjson.dumps({"role": role, "content": content}))
        except (RedisConnectionError, RedisTimeoutError, OSError):
            self._redis = None

    async def clear(self, session_id: str) -> None:
        sid = str(session_id)

        # always clear local
        self._local.pop(sid, None)

        r = await self._get_redis()
        if not r:
            return

        key = self._key(sid)
        try:
            await r.delete(key)
        except (RedisConnectionError, RedisTimeoutError, OSError):
            self._redis = None
