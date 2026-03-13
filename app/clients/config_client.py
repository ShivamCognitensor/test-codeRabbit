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
        self._client = httpx.AsyncClient(
            base_url=settings.lms_config_service_url,
            timeout=10.0,
            follow_redirects=True,
        )

    @staticmethod
    def _normalize_drf_list(data: Any) -> list:
        """
        DRF can return:
          - {"count":..., "results":[...]}
          - {"data":[...]}
          - [...]
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
        await self._client.aclose()


config_client = ConfigClient()