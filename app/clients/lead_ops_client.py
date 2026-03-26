"""
Lead Ops Service client.

- Supports legacy + new LeadOps path variants (gateway vs direct).
- Uses AuthClient (client_credentials) for service-to-service auth in webhook/scheduler flows.
- Uses request context token (_current_token) when present (user flows).

Env expected (via settings):
- LEAD_OPS_SERVICE_URL
- AUTH_TOKEN_URL (recommended)  e.g. http://lms-identity:8001/oauth/token
- SERVICE_CLIENT_ID
- SERVICE_CLIENT_SECRET
Optional:
- SERVICE_TOKEN_AUDIENCE / JWT_AUDIENCE
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

import httpx

from app.core.config import settings
from app.clients.auth_client import auth_client
from app.clients.config_client import _current_token  # user token propagation (contextvar)

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 12.0
MAX_RETRIES = 2


def _ctx_token() -> Optional[str]:
    """Get current request token stored by get_current_user()."""
    try:
        return _current_token.get()
    except LookupError:
        return None


def _auth_header(token: str) -> str:
    token = (token or "").strip()
    if not token:
        return ""
    return token if token.startswith("Bearer ") else f"Bearer {token}"


class LeadOpsClient:
    def __init__(self):
        base = getattr(settings, "LEAD_OPS_SERVICE_URL", None) or getattr(settings, "lead_ops_service_url", None) or ""
        self.base_url = base.rstrip("/")

        self.timeout = float(getattr(settings, "REQUEST_TIMEOUT", DEFAULT_TIMEOUT) or DEFAULT_TIMEOUT)
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout,
            follow_redirects=True,
        )

    # -----------------------------
    # Token selection
    # -----------------------------
    async def _pick_token(self, *, user_token: Optional[str] = None, allow_service: bool = False) -> Optional[str]:
        """
        Prefer explicit token -> context token -> service token (optional).
        """
        t = (user_token or "").strip() or (_ctx_token() or "").strip()
        if t:
            return t

        if not allow_service:
            return None

        try:
            # AuthClient returns raw access_token (no "Bearer " prefix)
            svc = await auth_client.get_service_token()
            return svc
        except Exception as e:
            logger.error("Service token fetch failed: %s", str(e))
            return None

    # -----------------------------
    # Low-level request with retries
    # -----------------------------
    async def _request(
        self,
        method: str,
        url: str,
        *,
        user_token: Optional[str] = None,
        allow_service: bool = False,
        params: Optional[dict] = None,
        json: Optional[dict] = None,
        extra_headers: Optional[dict] = None,
    ) -> Optional[Any]:
        token = await self._pick_token(user_token=user_token, allow_service=allow_service)

        headers: Dict[str, str] = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = _auth_header(token)
        if extra_headers:
            headers.update(extra_headers)

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = await self._client.request(method, url, headers=headers, params=params, json=json)

                # Retry on transient 5xx
                if resp.status_code >= 500 and attempt < MAX_RETRIES:
                    logger.warning(
                        "Lead Ops 5xx; retrying",
                        extra={"status_code": resp.status_code, "method": method, "url": url, "body": resp.text},
                    )
                    await asyncio.sleep(0.5)
                    continue

                if resp.status_code >= 400:
                    logger.warning(
                        "Lead Ops HTTP error",
                        extra={"status_code": resp.status_code, "method": method, "url": url, "body": resp.text},
                    )
                    return None

                if not resp.content:
                    return {}

                return resp.json()

            except (httpx.TimeoutException, httpx.ConnectError) as e:
                logger.warning("Lead Ops request failed (attempt %s/%s): %s", attempt, MAX_RETRIES, str(e))
                if attempt == MAX_RETRIES:
                    return None
                await asyncio.sleep(0.5)

            except Exception as e:
                logger.exception("Unexpected Lead Ops error: %s", str(e))
                return None

        return None

    # -----------------------------
    # Normalizers
    # -----------------------------
    @staticmethod
    def _as_list(data: Any) -> List[Dict[str, Any]]:
        if data is None:
            return []
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
        if isinstance(data, dict):
            d = data.get("data")
            if isinstance(d, list):
                return [x for x in d if isinstance(x, dict)]
            if isinstance(d, dict):
                items = d.get("items") or d.get("results")
                if isinstance(items, list):
                    return [x for x in items if isinstance(x, dict)]
        return []

    @staticmethod
    def _as_dict(data: Any) -> Optional[Dict[str, Any]]:
        if data is None:
            return None
        if isinstance(data, dict):
            if "data" in data and isinstance(data["data"], dict):
                return data["data"]
            return data
        return None

    # -----------------------------
    # Legacy / User-auth API surface (used by chat)
    # -----------------------------
    async def list_leads(
        self,
        *,
        user_token: str,
        loan_type_code: Optional[str] = None,
        status_code: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {}
        if loan_type_code:
            params["loan_type_code"] = loan_type_code
        if status_code:
            params["status_code"] = status_code
        if limit:
            params["limit"] = limit

        for path in ("/api/v1/leads", "/leads"):
            data = await self._request("GET", path, user_token=user_token, params=params or None)
            leads = self._as_list(data)
            if leads:
                return leads
        return []

    async def get_lead(self, *, lead_id: str, user_token: str) -> Optional[Dict[str, Any]]:
        for path in (f"/api/v1/leads/{lead_id}", f"/leads/{lead_id}"):
            data = await self._request("GET", path, user_token=user_token)
            d = self._as_dict(data)
            if d is not None:
                return d
        return None

    async def bre_evaluate_lead(
        self,
        *,
        lead_id: str,
        user_token: str,
        lender_code: Optional[str] = None,
        product_code: Optional[str] = None,
        segment: Optional[str] = None,
        facts_override: Optional[dict] = None,
    ) -> Optional[Dict[str, Any]]:
        payload = {
            "lead_id": lead_id,
            "lender_code": lender_code,
            "product_code": product_code,
            "segment": segment,
            "facts_override": facts_override,
        }

        for path in (
            f"/lead-rules-engine/leads/{lead_id}/evaluate",
            f"/api/v1/leads/{lead_id}/bre/evaluate",
        ):
            data = await self._request("POST", path, user_token=user_token, json=payload)
            d = self._as_dict(data)
            if d is not None:
                return d
        return None

    async def bre_get_recommendations(self, *, lead_id: str, user_token: str) -> Optional[Dict[str, Any]]:
        for path in (
            f"/lead-rules-engine/leads/{lead_id}/recommendations",
            f"/api/v1/leads/{lead_id}/bre/recommendations",
            f"/api/v1/leads/{lead_id}/bre/results",
        ):
            data = await self._request("GET", path, user_token=user_token)
            d = self._as_dict(data)
            if d is not None:
                return d
        return None

    async def get_user_applications(self, user_token: str) -> Optional[Dict[str, Any]]:
        for path in ("/dashboard/applications", "/api/v1/dashboard/applications"):
            data = await self._request("GET", path, user_token=user_token)
            d = self._as_dict(data)
            if d is not None:
                return d
        return None

    # -----------------------------
    # Internal lead create (used by VoiceBot webhook / scheduler)
    # -----------------------------
    async def create_lead_internal(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Create a lead from internal service flow.

        - Uses service token if no user token exists (webhook/scheduler).
        - Tries internal endpoints FIRST.
        - Continues fallbacks on 404/405.
        - For 401/403:
            * if internal endpoint returns 401/403 -> auth is broken -> stop
            * if user endpoint returns 401/403 (common for service tokens) -> continue
        """

        token = await self._pick_token(user_token=None, allow_service=True)
        if not token:
            logger.warning("No token available for internal lead creation (service token missing).")
            return None

        headers = {
            "X-Service-Name": "lms-finai",
            "Content-Type": "application/json",
            "Authorization": _auth_header(token),
        }

        # IMPORTANT: internal endpoints first (prevents 401 on /api/v1/leads blocking)
        paths = (
            "/api/v1/internal/leads",
            "/internal/leads",
            "/api/v1/leads",
            "/leads",
        )

        for path in paths:
            try:
                resp = await self._client.post(path, headers=headers, json=payload)

                # 404/405 => try next path
                if resp.status_code in (404, 405):
                    logger.warning("Lead create path not found", extra={"status_code": resp.status_code, "url": path})
                    continue

                # 401/403 logic:
                if resp.status_code in (401, 403):
                    logger.warning(
                        "Lead create unauthorized",
                        extra={"status_code": resp.status_code, "url": path, "body": resp.text},
                    )
                    # If internal endpoint denies -> token/auth is wrong -> stop early
                    if path in ("/api/v1/internal/leads", "/internal/leads"):
                        return None
                    # If user endpoint denies -> expected for service token -> continue fallback
                    continue

                if resp.status_code >= 400:
                    logger.warning(
                        "Lead create failed",
                        extra={"status_code": resp.status_code, "url": path, "body": resp.text},
                    )
                    return None

                if not resp.content:
                    return {}

                data = resp.json()
                return self._as_dict(data) or data

            except (httpx.TimeoutException, httpx.ConnectError) as e:
                logger.warning("Lead create connection error: %s", str(e), extra={"path": path})
                continue
            except Exception:
                logger.exception("Lead create error", extra={"path": path})
                continue

        return None

    async def close(self) -> None:
        await self._client.aclose()

    # -----------------------------
    # New API surface (used by new routers/services)
    # -----------------------------
    async def get_user_leads(self, user_id: UUID, token: str, limit: int = 5) -> List[Dict[str, Any]]:
        return await self.list_leads(user_token=token, limit=limit)

    async def get_lead_details(self, lead_id: UUID, token: str) -> Optional[Dict[str, Any]]:
        return await self.get_lead(lead_id=str(lead_id), user_token=token)

    async def get_lead_bre_results(self, lead_id: UUID, token: str) -> Optional[Dict[str, Any]]:
        for path in (
            f"/api/v1/leads/{lead_id}/bre/results",
            f"/api/v1/leads/{lead_id}/bre/recommendations",
        ):
            data = await self._request("GET", path, user_token=token)
            d = self._as_dict(data)
            if d is not None:
                return d
        return None

    async def get_user_context(self, user_id: UUID, token: str) -> Dict[str, Any]:
        context: Dict[str, Any] = {
            "has_leads": False,
            "leads": [],
            "active_lead": None,
            "recommendations": [],
        }

        leads = await self.get_user_leads(user_id, token, limit=5)
        if not leads:
            return context

        context["has_leads"] = True
        context["leads"] = leads[:5]

        active = None
        for l in leads:
            stage = str(l.get("stage") or l.get("status") or "").upper()
            if stage and stage not in {"CLOSED", "REJECTED"}:
                active = l
                break
        active = active or leads[0]

        lead_id_val = active.get("id") or active.get("lead_id") or active.get("leadId")
        if lead_id_val:
            details = await self.get_lead_details(UUID(str(lead_id_val)), token)
            if details:
                context["active_lead"] = details

            bre = await self.get_lead_bre_results(UUID(str(lead_id_val)), token)
            if bre:
                recs = bre.get("recommendations")
                if isinstance(recs, list):
                    context["recommendations"] = recs[:10]

        return context


# Singleton instance
lead_ops_client = LeadOpsClient()
