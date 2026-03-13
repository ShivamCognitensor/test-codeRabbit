"""
Rate limiting for public chat endpoints.

Uses in-memory storage (can be replaced with Redis for distributed systems).
"""

import logging
import time
from collections import defaultdict
from typing import Optional, Tuple
from datetime import datetime, timedelta

from fastapi import Request, HTTPException, status

from app.core.config import settings

logger = logging.getLogger(__name__)


class RateLimiter:
    """
    Simple in-memory rate limiter for public chat.
    
    Tracks:
    - Requests per IP per minute (sliding window)
    - Total messages per session
    """
    
    def __init__(self):
        # IP -> list of request timestamps
        """
        Initialize the RateLimiter's in-memory tracking state.
        
        Sets up dictionaries for per-IP request timestamps, per-session message counts, and session creation times, and initializes cleanup timing for periodic eviction of stale entries.
        
        Attributes created:
            _ip_requests: maps client IP to a list of request timestamps (float seconds).
            _session_messages: maps session ID to total messages sent.
            _session_created: maps session ID to its creation time (float seconds) for TTL-based cleanup.
            _last_cleanup: wall-clock time when last cleanup ran.
            _cleanup_interval: seconds between automatic cleanup runs (defaults to 300).
        """
        self._ip_requests: dict[str, list[float]] = defaultdict(list)
        # Session ID -> message count
        self._session_messages: dict[str, int] = defaultdict(int)
        # Session ID -> creation time (for TTL)
        self._session_created: dict[str, float] = {}
        # Cleanup interval
        self._last_cleanup = time.time()
        self._cleanup_interval = 300  # 5 minutes
    
    def _cleanup(self):
        """
        Remove stale session and IP request tracking data.
        
        Performs housekeeping if the configured cleanup interval has elapsed: updates the last-cleanup timestamp, removes sessions older than settings.PUBLIC_CHAT_SESSION_TTL (clearing both creation time and message count), and prunes per-IP request timestamps older than two minutes (removing empty IP entries). Emits a debug log when any sessions are removed.
        """
        now = time.time()
        if now - self._last_cleanup < self._cleanup_interval:
            return
        
        self._last_cleanup = now
        cutoff = now - settings.PUBLIC_CHAT_SESSION_TTL
        
        # Clean expired sessions
        expired = [sid for sid, created in self._session_created.items() if created < cutoff]
        for sid in expired:
            self._session_messages.pop(sid, None)
            self._session_created.pop(sid, None)
        
        # Clean old IP records (keep last 2 minutes)
        cutoff_ip = now - 120
        for ip in list(self._ip_requests.keys()):
            self._ip_requests[ip] = [ts for ts in self._ip_requests[ip] if ts > cutoff_ip]
            if not self._ip_requests[ip]:
                del self._ip_requests[ip]
        
        if expired:
            logger.debug(f"Cleaned up {len(expired)} expired sessions")
    
    def check_rate_limit(self, client_ip: str) -> Tuple[bool, int]:
        """
        Determine whether a client IP is within the 1-minute request rate limit.
        
        Returns:
            tuple: `True` if the request is allowed, `False` and the number of seconds to wait before retrying otherwise.
        """
        self._cleanup()
        
        now = time.time()
        window_start = now - 60  # 1 minute window
        
        # Get recent requests
        recent = [ts for ts in self._ip_requests[client_ip] if ts > window_start]
        
        if len(recent) >= settings.PUBLIC_CHAT_RATE_LIMIT:
            # Calculate retry after
            oldest = min(recent)
            retry_after = int(60 - (now - oldest)) + 1
            return False, retry_after
        
        # Record this request
        self._ip_requests[client_ip].append(now)
        return True, 0
    
    def check_session_limit(self, session_id: str) -> Tuple[bool, int, int]:
        """
        Determine whether a session has remaining public-chat messages.
        
        Returns:
            (is_allowed, messages_used, messages_remaining): 
                is_allowed (`True` if the session may send more messages, `False` otherwise),
                messages_used (int): number of messages already sent by the session,
                messages_remaining (int): number of messages remaining for the session (0 if the limit is reached).
        """
        self._cleanup()
        
        if session_id not in self._session_created:
            self._session_created[session_id] = time.time()
        
        count = self._session_messages[session_id]
        remaining = max(0, settings.PUBLIC_CHAT_MAX_MESSAGES - count)
        
        if count >= settings.PUBLIC_CHAT_MAX_MESSAGES:
            return False, count, remaining
        
        return True, count, remaining
    
    def increment_session_count(self, session_id: str):
        """
        Increase the stored message count for a session and ensure the session has a creation timestamp.
        
        If the session does not yet have a recorded creation time, one is set before incrementing the message count.
        
        Parameters:
            session_id (str): Identifier of the session whose message count will be incremented.
        """
        if session_id not in self._session_created:
            self._session_created[session_id] = time.time()
        self._session_messages[session_id] += 1
    
    def get_session_info(self, session_id: str) -> dict:
        """
        Return usage and limit status for the given session.
        
        Returns:
            dict: {
                "messages_used" (int): number of messages sent in the session,
                "messages_remaining" (int): number of messages left (zero or greater),
                "is_limit_reached" (bool): `true` if the session has reached the message limit, `false` otherwise
            }
        """
        count = self._session_messages.get(session_id, 0)
        return {
            "messages_used": count,
            "messages_remaining": max(0, settings.PUBLIC_CHAT_MAX_MESSAGES - count),
            "is_limit_reached": count >= settings.PUBLIC_CHAT_MAX_MESSAGES,
        }


# Singleton instance
rate_limiter = RateLimiter()


def get_client_ip(request: Request) -> str:
    """
    Extract the client's IP address from a request, honoring proxy headers.
    
    Parameters:
        request (Request): Incoming FastAPI/Starlette request.
    
    Returns:
        str: The client IP. Prefers the first value from `X-Forwarded-For`, then `X-Real-IP`, then `request.client.host`; returns `"unknown"` if no address is available.
    """
    # Check X-Forwarded-For header (for requests through proxies)
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        # Take the first IP (original client)
        return forwarded.split(",")[0].strip()
    
    # Check X-Real-IP header
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip
    
    # Fall back to direct client
    return request.client.host if request.client else "unknown"


async def check_public_chat_rate_limit(request: Request) -> str:
    """
    Validate public chat availability and enforce per-IP rate limits for an incoming request.
    
    Parameters:
        request (Request): FastAPI request object used to extract the client IP.
    
    Returns:
        client_ip (str): The resolved client IP address to be used by the caller.
    
    Raises:
        HTTPException: with 403 Forbidden if public chat is disabled.
        HTTPException: with 429 Too Many Requests if the client's IP has exceeded the rate limit; includes a "Retry-After" header indicating seconds until the next allowed request.
    """
    if not settings.PUBLIC_CHAT_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Public chat is disabled",
        )
    
    client_ip = get_client_ip(request)
    
    # Check rate limit
    is_allowed, retry_after = rate_limiter.check_rate_limit(client_ip)
    if not is_allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded. Please try again in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )
    
    return client_ip
