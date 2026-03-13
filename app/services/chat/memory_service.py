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
        """
        Initialize the ConversationMemory instance and prepare storage backends.
        
        Reads configuration to obtain the Redis URL (may be None), sets the Redis client reference to None for lazy initialization, and creates an empty in-memory local store mapping session IDs to message lists.
        """
        settings = get_settings()
        self._redis_url = settings.redis_url
        self._redis: Redis | None = None
        self._local: dict[str, list[Message]] = {}

    def _key(self, session_id: str) -> str:
        """
        Construct the Redis storage key for the given session ID.
        
        Parameters:
            session_id (str): The session identifier.
        
        Returns:
            str: Redis key in the form "chat:<session_id>".
        """
        return f"chat:{session_id}"

    async def _get_redis(self) -> Redis | None:
        """
        Return a Redis client connected to the configured URL, or `None` if no URL is configured.
        
        Creates and caches the Redis client on first use.
        
        Returns:
            `Redis` client connected to the configured URL, or `None` if no URL is configured.
        """
        if not self._redis_url:
            return None
        if self._redis is None:
            self._redis = Redis.from_url(self._redis_url, decode_responses=False)
        return self._redis

    async def get_history(self, session_id: str, limit: int = 20) -> list[Message]:
        """
        Retrieve the recent conversation messages for a session, using Redis when available and falling back to local memory.
        
        Parameters:
            session_id (str): Session identifier; will be normalized to a string.
            limit (int): Maximum number of most-recent messages to return.
        
        Returns:
            list[Message]: Up to `limit` Message objects ordered from oldest to newest. If Redis is unavailable, returns messages from the in-memory store. Corrupted Redis entries are skipped.
        """
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
        """
        Store a message in the conversation history for the given session, persisting it in the in-memory cache and attempting to append it to the Redis-backed history.
        
        Parameters:
            session_id (str): Identifier for the conversation session.
            role (str): Role of the message author (e.g., "user", "assistant").
            content (str): Message text to store.
        
        Notes:
            - The in-memory history is always updated. If a Redis client is available, the message is pushed to the Redis list for the session.
            - On Redis connection, timeout, or OS errors, the Redis client reference is invalidated and the function returns after the local update.
        """
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
        """
        Clear the conversation history for the given session from both the in-memory store and Redis (if configured).
        
        Parameters:
            session_id (str): Identifier of the session whose history should be cleared.
        """
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
