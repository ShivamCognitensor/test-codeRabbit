# app/clients/auth_client.py
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Optional, Dict, Any
from urllib.parse import urlparse, urlunparse

import httpx
from app.core.config import get_settings

logger = logging.getLogger(__name__)


def _base_from_url(url: str) -> str:
    """
    Return the URL's scheme and network location (scheme://netloc) without any path or trailing slash.
    
    Parameters:
        url (str): The input URL. If falsy (for example, empty string or None), an empty string is returned.
    
    Returns:
        base (str): The base URL composed of the scheme and netloc (e.g., "https://example.com"), or an empty string for falsy input.
    """
    if not url:
        return ""
    p = urlparse(url)
    return urlunparse((p.scheme, p.netloc, "", "", "", "")).rstrip("/")


@dataclass
class TokenCache:
    access_token: Optional[str] = None
    expires_at: float = 0.0


class AuthClient:
    def __init__(self) -> None:
        """
        Initialize the AuthClient by loading settings, determining the token endpoint, and preparing the in-memory token cache and lock.
        
        Determines token_url from an explicit AUTH_TOKEN_URL setting when present; otherwise derives a default from JWKS_URL (appending /oauth/token) or falls back to http://lms-identity:8001/oauth/token. Reads client_id, client_secret, and optional audience from configuration. Sets the HTTP request timeout, initializes an empty TokenCache and an asyncio.Lock to serialize token refreshes, and logs a warning when JWKS_URL is not configured and the fallback token_url is used.
        """
        s = get_settings()

        # ✅ get jwks_url from settings
        jwks_url = getattr(s, "jwks_url", None) or getattr(s, "JWKS_URL", None) or ""
        jwks_base = _base_from_url(str(jwks_url)) if jwks_url else ""

        # ✅ AUTH_TOKEN_URL optional; if missing derive from JWKS base
        explicit = getattr(s, "auth_token_url", None) or getattr(s, "AUTH_TOKEN_URL", None)
        if explicit:
            self.token_url = str(explicit).strip()
        else:
            # default derived endpoint
            self.token_url = f"{jwks_base}/oauth/token" if jwks_base else "http://lms-identity:8001/oauth/token"

        self.client_id: str = getattr(s, "service_client_id", None) or getattr(s, "SERVICE_CLIENT_ID", "")
        self.client_secret: str = getattr(s, "service_client_secret", None) or getattr(s, "SERVICE_CLIENT_SECRET", "")
        self.audience: Optional[str] = getattr(s, "service_token_audience", None) or getattr(s, "jwt_audience", None)

        self.timeout = float(getattr(s, "REQUEST_TIMEOUT", 10.0) or 10.0)

        self._cache = TokenCache()
        self._lock = asyncio.Lock()

        if not jwks_base:
            logger.warning("JWKS_URL not configured; token_url fallback used: %s", self.token_url)

    def _is_valid(self) -> bool:
        """
        Check whether a cached access token is present and still valid beyond a 30-second grace period.
        
        Returns:
            `true` if a non-empty cached access token exists and the current time is at least 30 seconds before its expiration, `false` otherwise.
        """
        return bool(self._cache.access_token) and (time.time() < (self._cache.expires_at - 30))

    async def get_service_token(self, force_refresh: bool = False) -> str:
        """
        Return a valid service access token, using a cached token if still valid.
        
        If `force_refresh` is True or the cached token is expired (considering the configured grace window), a new token is fetched and stored in the internal cache while holding a lock to serialize refreshes.
        
        Parameters:
            force_refresh (bool): If True, bypass the cached token and force fetching a new one.
        
        Returns:
            str: The access token.
        """
        if not force_refresh and self._is_valid():
            return self._cache.access_token  # type: ignore[return-value]

        async with self._lock:
            if not force_refresh and self._is_valid():
                return self._cache.access_token  # type: ignore[return-value]

            token, expires_in = await self._fetch_token()
            self._cache.access_token = token
            self._cache.expires_at = time.time() + float(expires_in or 3600)
            return token

    async def _fetch_token(self) -> tuple[str, int]:
        """
        Fetches a service access token from the configured token endpoint using the client credentials grant.
        
        Attempts the HTTP token request up to 3 times on transient network or timeout errors with incremental backoff. Requires the client credentials and token URL to be configured; on success returns the token and its lifetime in seconds, otherwise raises a RuntimeError.
        
        Returns:
            tuple[str, int]: `(access_token, expires_in)` where `access_token` is the fetched token string and `expires_in` is the lifetime in seconds (defaults to 3600 if not provided by the server).
        
        Raises:
            RuntimeError: If token_url, client credentials are not configured, if the response lacks an access_token, if the endpoint returns an error status, or if all retry attempts fail.
        """
        if not self.token_url:
            raise RuntimeError("token_url not configured")
        if not self.client_id or not self.client_secret:
            raise RuntimeError("SERVICE_CLIENT_ID/SERVICE_CLIENT_SECRET not configured")

        data: Dict[str, Any] = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }
        if self.audience:
            # if your identity supports it; safe to include only if needed
            data["audience"] = self.audience

        last_exc: Optional[Exception] = None
        for attempt in range(1, 4):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.post(
                        self.token_url,
                        data=data,
                        headers={"Content-Type": "application/x-www-form-urlencoded"},
                    )
                    if resp.status_code >= 400:
                        raise RuntimeError(f"Token fetch failed {resp.status_code}: {resp.text}")

                    payload = resp.json()
                    access_token = payload.get("access_token")
                    expires_in = int(payload.get("expires_in") or 3600)
                    if not access_token:
                        raise RuntimeError(f"Missing access_token in response: {payload}")
                    return str(access_token), expires_in

            except (httpx.ConnectError, httpx.TimeoutException, RuntimeError) as e:
                last_exc = e
                logger.warning("Service token fetch error (attempt %s/3): %s", attempt, str(e))
                if attempt < 3:
                    await asyncio.sleep(0.5 * attempt)

        raise RuntimeError(f"Service token fetch failed after retries: {last_exc}")


auth_client = AuthClient()
