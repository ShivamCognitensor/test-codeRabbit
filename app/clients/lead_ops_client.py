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
    """
    Retrieve the request-scoped token stored in the current context.
    
    Returns:
        token (str | None): The current request token if present, otherwise `None`.
    """
    try:
        return _current_token.get()
    except LookupError:
        return None


def _auth_header(token: str) -> str:
    """
    Normalize a token into a Bearer Authorization header value.
    
    Parameters:
        token (str): Raw token or existing Authorization header value; may be None or empty.
    
    Returns:
        str: A string starting with "Bearer " followed by the token, or an empty string if the input is missing or blank.
    """
    token = (token or "").strip()
    if not token:
        return ""
    return token if token.startswith("Bearer ") else f"Bearer {token}"


class LeadOpsClient:
    def __init__(self):
        """
        Initialize the LeadOpsClient by configuring base URL, request timeout, and the async HTTP client.
        
        Sets:
        - base_url: the service base URL derived from LEAD_OPS_SERVICE_URL or lead_ops_service_url (with trailing slash removed).
        - timeout: request timeout (from REQUEST_TIMEOUT or default).
        - _client: an httpx.AsyncClient configured with the base_url, timeout, and follow_redirects=True.
        """
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
        Selects an authorization token from explicit input, the request context, or optionally a service token.
        
        Parameters:
            user_token (Optional[str]): Explicit token to prefer if provided.
            allow_service (bool): If True, attempt to fetch a service token when no user or context token is available.
        
        Returns:
            Optional[str]: The chosen token string, or `None` if no token could be obtained.
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
        """
        Perform an HTTP request to the Lead Ops service using resolved authentication, with retry and error handling.
        
        Parameters:
        	method (str): HTTP method (e.g., "GET", "POST").
        	url (str): Full request URL or path resolved against the client's base URL.
        	user_token (Optional[str]): Explicit user token to use; if omitted the client will try context token then (if allowed) a service token.
        	allow_service (bool): If True, permit falling back to a service-to-service token when no user/context token is available.
        	params (Optional[dict]): Query parameters to include in the request.
        	json (Optional[dict]): JSON payload to send in the request body.
        	extra_headers (Optional[dict]): Additional headers to merge into the request (overrides default headers).
        
        Returns:
        	Parsed JSON response (dict, list, or primitive) when the request succeeds; an empty dict `{}` when the response has no content; `None` on HTTP 4xx responses, repeated transient failures, or unexpected errors.
        """
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
        """
        Normalize varied response shapes into a list of dictionaries.
        
        Parameters:
            data (Any): Input that may be None, a list of dicts, a dict containing "data", or nested shapes where the list appears under "data", "items", or "results".
        
        Returns:
            List[Dict[str, Any]]: A list containing only dict elements extracted from the input; returns an empty list if no appropriate list of dicts is found.
        """
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
        """
        Extract a dictionary from a possibly wrapped response object.
        
        If `data` is a dict containing a `"data"` key whose value is a dict, return that inner dict. If `data` is a dict without such wrapping, return it unchanged. For any other input, return `None`.
        
        Parameters:
            data (Any): Input value that may be a dict or a wrapper like `{"data": {...}}`.
        
        Returns:
            dict or None: The extracted dictionary, or `None` if no dictionary is present.
        """
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
        """
        Retrieve a list of leads for the authenticated user, optionally filtered by loan type, status, or limit.
        
        Parameters:
            user_token (str): Authorization token to authenticate the request on behalf of the user.
            loan_type_code (Optional[str]): Filter leads by loan type code.
            status_code (Optional[str]): Filter leads by status code.
            limit (Optional[int]): Maximum number of leads to return.
        
        Returns:
            List[Dict[str, Any]]: A list of lead dictionaries matching the filters; empty list if no leads are found.
        """
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
        """
        Retrieve a lead by its ID from the Lead Ops service.
        
        Parameters:
            lead_id (str): The lead identifier to fetch.
            user_token (str): Authorization token to use for the request.
        
        Returns:
            dict: The lead data as a dictionary if found, `None` otherwise.
        """
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
        """
        Evaluate a lead using the business rules engine (BRE) and return the evaluation results.
        
        Parameters:
            lead_id (str): ID of the lead to evaluate.
            user_token (str): Authorization token representing the user context.
            lender_code (Optional[str]): Optional lender identifier to scope the evaluation.
            product_code (Optional[str]): Optional product identifier to scope the evaluation.
            segment (Optional[str]): Optional segment identifier to influence rules selection.
            facts_override (Optional[dict]): Optional dictionary of fact overrides to apply during evaluation.
        
        Returns:
            Optional[Dict[str, Any]]: Evaluation result as a dictionary if an endpoint returns a valid response, `None` if no evaluation could be obtained.
        """
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
        """
        Fetch BRE recommendations for a lead by probing multiple possible endpoints.
        
        Parameters:
            lead_id (str): Lead identifier to fetch recommendations for.
            user_token (str): Authorization token to use for the request.
        
        Returns:
            dict: Recommendations payload normalized as a dictionary if found, `None` otherwise.
        """
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
        """
        Fetch a user's applications from the Lead Ops dashboard by probing known endpoints.
        
        Returns:
            A dict representing the user's applications if found, `None` otherwise.
        """
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
        Create a lead using the internal service flow and return the created lead record.
        
        Parameters:
            payload (Dict[str, Any]): JSON-serializable payload describing the lead to create.
        
        Returns:
            Dict[str, Any]: The created lead as a parsed JSON dict if the request succeeded.
            An empty dict if the service responded with no content.
            `None` if creation failed or no suitable endpoint accepted the request.
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
        """
        Close the underlying HTTPX client and release its network resources.
        """
        await self._client.aclose()

    # -----------------------------
    # New API surface (used by new routers/services)
    # -----------------------------
    async def get_user_leads(self, user_id: UUID, token: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Fetches leads for a user using the provided token and limit.
        
        Parameters:
            user_id (UUID): Identifier for the user (not used by this implementation; the token determines which leads are returned).
            token (str): Authorization token used to retrieve the user's leads.
            limit (int): Maximum number of leads to return.
        
        Returns:
            List[Dict[str, Any]]: A list of lead dictionaries; empty list if no leads are found.
        """
        return await self.list_leads(user_token=token, limit=limit)

    async def get_lead_details(self, lead_id: UUID, token: str) -> Optional[Dict[str, Any]]:
        """
        Fetch lead details for the given lead ID using the provided token.
        
        Parameters:
            lead_id (UUID): The UUID of the lead to retrieve.
            token (str): Authentication token to use for the request.
        
        Returns:
            dict: Lead details if found, `None` otherwise.
        """
        return await self.get_lead(lead_id=str(lead_id), user_token=token)

    async def get_lead_bre_results(self, lead_id: UUID, token: str) -> Optional[Dict[str, Any]]:
        """
        Fetch BRE results or recommendations for a lead by probing known endpoints.
        
        Parameters:
            lead_id (UUID): Identifier of the lead to query.
            token (str): Authentication token to include in the request.
        
        Returns:
            dict: Parsed BRE results or recommendations if found.
            None: If no data was returned from any probed endpoint.
        """
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
        """
        Builds a lead-centric context for a user containing their leads, the active lead, and BRE recommendations.
        
        Parameters:
            user_id (UUID): Identifier of the user whose leads will be fetched.
            token (str): Authorization token used to fetch user-specific lead data.
        
        Returns:
            Dict[str, Any]: A context dictionary with the following keys:
                - "has_leads" (bool): True if the user has any leads, False otherwise.
                - "leads" (List[Dict]): Up to five lead objects for the user.
                - "active_lead" (Dict or None): The active lead's detailed data (a non-terminal lead if present), or None.
                - "recommendations" (List[Dict]): Up to ten BRE recommendation objects for the active lead.
        """
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
