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
    """http://host:port/path -> http://host:port"""
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
        return bool(self._cache.access_token) and (time.time() < (self._cache.expires_at - 30))

    async def get_service_token(self, force_refresh: bool = False) -> str:
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
