from __future__ import annotations

from typing import Any, Dict, Optional
import httpx
from contextvars import ContextVar

from app.core.config import get_settings
from app.core.logging import get_logger

settings = get_settings()
logger = get_logger(__name__)

_current_token: ContextVar[Optional[str]] = ContextVar("_current_token", default=None)


class ConfigClient:
    """Client for Config Service."""

    def __init__(self) -> None:
        """
        Initialize the ConfigClient by creating an httpx.AsyncClient configured for the Config Service and storing it on `self._client`.
        
        The client is created with the base URL taken from application settings, a 10-second timeout, and automatic redirect following enabled.
        """
        self._client = httpx.AsyncClient(
            base_url=settings.lms_config_service_url,
            timeout=10.0,
            follow_redirects=True,
        )

    @staticmethod
    def _normalize_drf_list(data: Any) -> list:
        """
        Normalize DRF-style responses into a flat list.
        
        Parameters:
            data (Any): Response payload which may be None, a list, or a dict that contains a list under the "results" or "data" keys.
        
        Returns:
            list: The extracted list from `data` — if `data` is a list it is returned as-is; if `data` is a dict with a list under "results" or "data" that list is returned; otherwise an empty list.
        """
        if data is None:
            return []
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            if "results" in data and isinstance(data["results"], list):
                return data["results"]
            if "data" in data and isinstance(data["data"], list):
                return data["data"]
        return []

    async def _request(
        self,
        method: str,
        url: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
        use_user_token: bool = True,
    ) -> Optional[Any]:
        """
        Make an HTTP request to the Config Service, optionally attaching the current user token and normalizing DRF-style URLs.
        
        Parameters:
            method (str): HTTP method name (e.g., "GET", "POST").
            url (str): Endpoint path or URL; a trailing slash will be appended if missing.
            params (Optional[Dict[str, Any]]): Query parameters to include in the request.
            json (Optional[Dict[str, Any]]): JSON body to include in the request.
            use_user_token (bool): If True, add an `Authorization: Bearer <token>` header when a token is present in the module's context var.
        
        Returns:
            The parsed JSON response on success, an empty dict if the response has no content, or `None` if an HTTP error or other exception occurred.
        """
        headers: Dict[str, str] = {}

        if use_user_token:
            token = _current_token.get()
            if token:
                headers["Authorization"] = f"Bearer {token}"

        # Django/DRF usually expects trailing slash
        if url and not url.endswith("/"):
            url = url + "/"

        try:
            resp = await self._client.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                json=json,
            )
            resp.raise_for_status()
            if not resp.content:
                return {}
            return resp.json()

        except httpx.HTTPStatusError as e:
            logger.error(
                "Config service HTTP error",
                extra={
                    "status_code": e.response.status_code,
                    "url": url,
                    "body": e.response.text,
                },
            )
            return None
        except Exception as e:
            logger.exception("Config service unexpected error", exc_info=e)
            return None

    async def get_permissions(self, role_code: str) -> Dict[str, Any]:
        """
        Fetches permissions for the given role code from the Config Service.
        
        Parameters:
            role_code (str): Identifier code of the role whose permissions are requested.
        
        Returns:
            dict: Permissions data for the role, or an empty dict if the request failed or no data was returned.
        """
        result = await self._request(
            "GET",
            f"/roles/{role_code}/permissions",
            use_user_token=True,
        )
        return result or {}

    # -----------------------------
    # Lead Statuses (from Config)
    # -----------------------------
    async def get_lead_status(self, code: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve a lead status by its code from the config service.
        
        Parameters:
            code (str): The lead status code to look up.
        
        Returns:
            Optional[Dict[str, Any]]: The first matching lead status as a dictionary if found, `None` otherwise.
        """
        data = await self._request(
            "GET",
            "/lead-statuses",
            params={"code": code},
            use_user_token=True,
        )
        items = self._normalize_drf_list(data)
        if not items:
            return None
        return items[0] if isinstance(items[0], dict) else None

    async def get_loan_type(self, code: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve a loan type resource that matches the provided code.
        
        Parameters:
            code (str): The loan type code to look up.
        
        Returns:
            dict: The first matching loan type object if found, `None` otherwise.
        """
        data = await self._request(
            "GET",
            "/loan-types",
            params={"code": code},
            use_user_token=True,
        )
        items = self._normalize_drf_list(data)
        if not items:
            return None
        return items[0] if isinstance(items[0], dict) else None

    async def close(self) -> None:
        """
        Close the underlying HTTPX AsyncClient and release its network resources.
        """
        await self._client.aclose()


config_client = ConfigClient()