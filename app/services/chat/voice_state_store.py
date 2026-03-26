from __future__ import annotations

from dataclasses import dataclass

import orjson
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError, TimeoutError as RedisTimeoutError

from app.core.config import get_settings
from app.core.logging import get_logger


logger = get_logger(__name__)


@dataclass
class VoiceState:
    current_step: str | None
    context: dict


class VoiceStateStore:
    """Ephemeral (Redis-backed) state for VoiceBot calls.

    Why this exists:
    - Chatbot uses DB-backed sessions/state.
    - VoiceBot should NOT create DB sessions, but still needs short-lived state
      across multiple webhook turns in the same call.
    """

    def __init__(self, ttl_seconds: int = 60 * 60):
        settings = get_settings()
        self._redis_url = settings.redis_url
        self._redis: Redis | None = None
        self._local: dict[str, VoiceState] = {}
        self._ttl = int(ttl_seconds)

    def _key(self, call_id: str) -> str:
        return f"voice:state:{call_id}"

    async def _get_redis(self) -> Redis | None:
        if not self._redis_url:
            return None
        if self._redis is None:
            self._redis = Redis.from_url(self._redis_url, decode_responses=False)
        return self._redis

    async def get(self, call_id: str) -> VoiceState:
        cid = str(call_id)
        r = await self._get_redis()

        if not r:
            return self._local.get(cid, VoiceState(current_step=None, context={}))

        key = self._key(cid)
        try:
            raw = await r.get(key)
            if not raw:
                return VoiceState(current_step=None, context={})
            obj = orjson.loads(raw)
            return VoiceState(
                current_step=obj.get("current_step"),
                context=obj.get("context") or {},
            )
        except (RedisConnectionError, RedisTimeoutError, OSError, Exception):
            self._redis = None
            return self._local.get(cid, VoiceState(current_step=None, context={}))

    async def set(self, call_id: str, *, current_step: str | None, context: dict) -> None:
        cid = str(call_id)
        state = VoiceState(current_step=current_step, context=context or {})
        self._local[cid] = state

        r = await self._get_redis()
        if not r:
            return

        key = self._key(cid)
        try:
            await r.set(key, orjson.dumps({"current_step": current_step, "context": state.context}), ex=self._ttl)
        except (RedisConnectionError, RedisTimeoutError, OSError):
            self._redis = None