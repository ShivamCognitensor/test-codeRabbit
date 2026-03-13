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
        """
        Initialize the VoiceStateStore with a local cache and optional Redis backend.
        
        Parameters:
            ttl_seconds (int): Time-to-live for stored voice state entries in seconds; used when persisting to Redis.
        """
        settings = get_settings()
        self._redis_url = settings.redis_url
        self._redis: Redis | None = None
        self._local: dict[str, VoiceState] = {}
        self._ttl = int(ttl_seconds)

    def _key(self, call_id: str) -> str:
        """
        Builds the namespaced Redis key for a voice call.
        
        Parameters:
            call_id (str): Unique identifier for the voice call.
        
        Returns:
            str: Redis key in the form "voice:state:{call_id}".
        """
        return f"voice:state:{call_id}"

    async def _get_redis(self) -> Redis | None:
        """
        Return the Redis client associated with the configured Redis URL, creating it on first use.
        
        Returns:
            Redis | None: A Redis client instance connected to the configured URL, or `None` if no Redis URL is configured.
        """
        if not self._redis_url:
            return None
        if self._redis is None:
            self._redis = Redis.from_url(self._redis_url, decode_responses=False)
        return self._redis

    async def get(self, call_id: str) -> VoiceState:
        """
        Retrieve the VoiceState for the given call identifier, using Redis when available and falling back to the in-memory cache.
        
        Parameters:
            call_id (str | int): Identifier of the call; will be normalized to a string.
        
        Returns:
            VoiceState: The stored state for the call. If no state exists returns VoiceState(current_step=None, context={}). If Redis is unavailable or an error occurs, returns the in-memory cached state or the same default.
        """
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
        """
        Store voice state for a call in the local cache and attempt to persist it to Redis with the configured TTL.
        
        Constructs a VoiceState from the provided current_step and context, saves it into the in-memory cache keyed by call_id, and attempts to write the same JSON payload to Redis under the instance's namespaced key with the instance TTL. If Redis is not configured or unavailable the function returns after updating the local cache. On Redis connection, timeout, or OS-level errors, the Redis client reference is cleared so subsequent operations will fall back to the local cache.
        
        Parameters:
            call_id (str): Identifier for the call; converted to string for storage.
            current_step (str | None): Current step name or None.
            context (dict): Context dictionary to store alongside the current step.
        """
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