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
        self._ip_requests: dict[str, list[float]] = defaultdict(list)
        # Session ID -> message count
        self._session_messages: dict[str, int] = defaultdict(int)
        # Session ID -> creation time (for TTL)
        self._session_created: dict[str, float] = {}
        # Cleanup interval
        self._last_cleanup = time.time()
        self._cleanup_interval = 300  # 5 minutes
    
    def _cleanup(self):
        """Remove expired entries."""
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
        Check if IP is within rate limit.
        
        Returns:
            (is_allowed, retry_after_seconds)
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
        Check if session is within message limit.
        
        Returns:
            (is_allowed, messages_used, messages_remaining)
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
        """Increment message count for a session."""
        if session_id not in self._session_created:
            self._session_created[session_id] = time.time()
        self._session_messages[session_id] += 1
    
    def get_session_info(self, session_id: str) -> dict:
        """Get session usage info."""
        count = self._session_messages.get(session_id, 0)
        return {
            "messages_used": count,
            "messages_remaining": max(0, settings.PUBLIC_CHAT_MAX_MESSAGES - count),
            "is_limit_reached": count >= settings.PUBLIC_CHAT_MAX_MESSAGES,
        }


# Singleton instance
rate_limiter = RateLimiter()


def get_client_ip(request: Request) -> str:
    """Extract client IP from request, considering proxies."""
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
    Dependency to check rate limits for public chat.
    
    Raises HTTPException if rate limit exceeded.
    Returns client IP.
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
