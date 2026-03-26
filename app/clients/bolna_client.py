"""Bolna.ai API Client for Voice Bot Integration.

This client is used by both:
- New service code (campaign service) 
- Legacy service code (v17 VoiceFin runner/webhooks)

So it supports **both** calling styles:
- New-style: make_call(to_phone=..., agent_id=..., from_phone=..., context=...)
- Legacy-style: make_call(agent_id=..., recipient_phone_number=..., from_phone_number=..., user_data=...)
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class BolnaClient:
    """Async client for Bolna.ai APIs."""

    def __init__(self):
        self.base_url = settings.BOLNA_API_BASE
        self.api_key = settings.BOLNA_API_KEY
        self.default_agent_id = settings.BOLNA_DEFAULT_AGENT_ID
        self.default_from_phone = settings.BOLNA_DEFAULT_FROM_PHONE_NUMBER
        self.timeout = settings.REQUEST_TIMEOUT

        logger.info("bolna api key----------", settings.BOLNA_API_KEY)

    @classmethod
    def from_settings(cls) -> "BolnaClient":
        """Legacy helper: construct client and ensure key exists."""
        if not settings.BOLNA_API_KEY:
            raise RuntimeError("BOLNA_API_KEY is not set")
        return cls()

    @property
    def is_enabled(self) -> bool:
        return bool(self.api_key)

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
        }

    def _json_headers(self) -> Dict[str, str]:
        return {**self._headers(), "Content-Type": "application/json"}

    # ------------------------------------------------------------------
    # Calls
    # ------------------------------------------------------------------
    async def make_call(
        self,
        to_phone: Optional[str] = None,
        agent_id: Optional[str] = None,
        from_phone: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        webhook_url: Optional[str] = None,
        **kwargs,
    ) -> Optional[Dict[str, Any]]:
        """Initiate an outbound call.

        New-style args:
          - to_phone, agent_id, from_phone, context, webhook_url

        Legacy-style kwargs accepted:
          - recipient_phone_number, from_phone_number, scheduled_at, user_data, retry_config
        """
        if not self.is_enabled:
            logger.warning("Bolna is not configured, call skipped")
            return None

        # Legacy arg mapping
        recipient_phone_number = kwargs.pop("recipient_phone_number", None)
        from_phone_number = kwargs.pop("from_phone_number", None)
        scheduled_at = kwargs.pop("scheduled_at", None)
        user_data = kwargs.pop("user_data", None)
        retry_config = kwargs.pop("retry_config", None)

        if recipient_phone_number and not to_phone:
            to_phone = recipient_phone_number
        if from_phone_number and not from_phone:
            from_phone = from_phone_number
        if user_data and context is None:
            context = user_data

        agent_id = agent_id or kwargs.pop("agent_id", None) or self.default_agent_id
        from_phone = from_phone or self.default_from_phone

        if not agent_id:
            raise ValueError("agent_id is required for making calls")
        if not to_phone:
            raise ValueError("to_phone/recipient_phone_number is required")

        payload: Dict[str, Any] = {
            "agent_id": agent_id,
            "recipient_phone_number": to_phone,
        }

        # Some Bolna tenants expect `from_phone_number`, others accept `from`.
        if from_phone:
            payload["from_phone_number"] = from_phone
            payload["from"] = from_phone

        if context:
            payload["user_data"] = context

        if webhook_url:
            payload["webhook_url"] = webhook_url

        if scheduled_at:
            payload["scheduled_at"] = scheduled_at

        if retry_config:
            payload["retry_config"] = retry_config

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.post(f"{self.base_url}/call", json=payload, headers=self._json_headers())

            if r.status_code in (200, 201):
                data = r.json()
                logger.info("bolna_call_started", extra={"execution_id": data.get("execution_id")})
                return data

            logger.error("bolna_call_failed", extra={"status": r.status_code, "body": r.text})
            r.raise_for_status()
            return None

        except Exception as e:
            logger.exception(f"Bolna API error during make_call: {e}")
            return None

    async def stop_call(self, execution_id: str) -> Optional[Dict[str, Any]]:
        if not self.is_enabled:
            return None
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.post(f"{self.base_url}/call/{execution_id}/stop", headers=self._headers())
                if r.status_code in (200, 201):
                    return r.json() if r.content else {}
                return None
        except Exception as e:
            logger.error(f"Failed to stop call {execution_id}: {e}")
            return None

    async def stop_agent_queued_calls(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """Legacy endpoint used in some setups."""
        if not self.is_enabled:
            return None
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.post(f"{self.base_url}/v2/agent/{agent_id}/stop", headers=self._headers())
                if r.status_code in (200, 201):
                    return r.json() if r.content else {}
                return None
        except Exception as e:
            logger.error(f"Failed to stop queued calls for agent {agent_id}: {e}")
            return None

    async def get_execution(self, execution_id: str) -> Optional[Dict[str, Any]]:
        return await self.get_call_status(execution_id)

    async def get_call_status(self, execution_id: str) -> Optional[Dict[str, Any]]:
        if not self.is_enabled:
            return None
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.get(f"{self.base_url}/executions/{execution_id}", headers=self._headers())
                if r.status_code == 200:
                    return r.json()
                return None
        except Exception as e:
            logger.error(f"Failed to get call status: {e}")
            return None

    # ------------------------------------------------------------------
    # Batches
    # ------------------------------------------------------------------
    async def create_batch(
        self,
        agent_id: Optional[str] = None,
        contacts_csv: Optional[bytes] = None,
        campaign_name: Optional[str] = None,
        from_phone: Optional[str] = None,
        webhook_url: Optional[str] = None,
        **kwargs,
    ) -> Optional[Dict[str, Any]]:
        """Create a batch campaign.

        New-style args:
          - agent_id, contacts_csv, campaign_name, from_phone, webhook_url

        Legacy-style kwargs accepted:
          - csv_bytes, file_path, filename, from_phone_number, retry_config
        """
        if not self.is_enabled:
            return None

        # Legacy mapping
        csv_bytes = kwargs.pop("csv_bytes", None)
        file_path = kwargs.pop("file_path", None)
        filename = kwargs.pop("filename", "leads.csv")
        from_phone_number = kwargs.pop("from_phone_number", None)
        retry_config = kwargs.pop("retry_config", None)

        if csv_bytes and contacts_csv is None:
            contacts_csv = csv_bytes

        if file_path and contacts_csv is None:
            p = Path(file_path)
            contacts_csv = p.read_bytes()
            if filename == "leads.csv":
                filename = p.name

        if not contacts_csv:
            raise ValueError("contacts_csv/csv_bytes or file_path is required")

        agent_id = agent_id or self.default_agent_id
        from_phone = from_phone or from_phone_number or self.default_from_phone

        # Bolna expects multipart for file upload
        files = {"file": (filename, contacts_csv, "text/csv")}

        data: Dict[str, Any] = {"agent_id": agent_id}
        if campaign_name:
            data["campaign_name"] = campaign_name
        if from_phone:
            data["from_phone_number"] = from_phone
        if webhook_url:
            data["webhook_url"] = webhook_url
        if retry_config is not None:
            # Some setups require retry_config as JSON string
            try:
                import json

                data["retry_config"] = json.dumps(retry_config)
            except Exception:
                data["retry_config"] = str(retry_config)

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                r = await client.post(f"{self.base_url}/batches", headers=self._headers(), data=data, files=files)

            if r.status_code in (200, 201):
                return r.json()

            logger.error("bolna_create_batch_failed", extra={"status": r.status_code, "body": r.text})
            r.raise_for_status()
            return None

        except Exception as e:
            logger.error(f"Batch creation error: {e}")
            return None

    async def schedule_batch(
        self,
        batch_id: str,
        scheduled_time: Optional[datetime] = None,
        scheduled_at: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Schedule a batch campaign.

        New-style uses JSON with `scheduled_time` (datetime).
        Legacy uses multipart with `scheduled_at` (string).
        """
        if not self.is_enabled:
            return None

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                if scheduled_at and not scheduled_time:
                    # legacy multipart
                    files = {"scheduled_at": (None, scheduled_at)}
                    r = await client.post(f"{self.base_url}/batches/{batch_id}/schedule", headers=self._headers(), files=files)
                else:
                    payload: Dict[str, Any] = {}
                    if scheduled_time:
                        payload["scheduled_time"] = scheduled_time.isoformat()
                    r = await client.post(
                        f"{self.base_url}/batches/{batch_id}/schedule",
                        headers=self._json_headers(),
                        json=payload,
                    )

            if r.status_code in (200, 201):
                return r.json() if r.content else {}

            logger.error("bolna_schedule_batch_failed", extra={"status": r.status_code, "body": r.text})
            return None

        except Exception as e:
            logger.error(f"Failed to schedule batch: {e}")
            return None

    async def stop_batch(self, batch_id: str) -> Optional[Dict[str, Any]]:
        if not self.is_enabled:
            return None
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.post(f"{self.base_url}/batches/{batch_id}/stop", headers=self._headers())
                if r.status_code in (200, 201):
                    return r.json() if r.content else {}
                return None
        except Exception as e:
            logger.error(f"Failed to stop batch: {e}")
            return None

    async def get_batch_status(self, batch_id: str) -> Optional[Dict[str, Any]]:
        if not self.is_enabled:
            return None
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.get(f"{self.base_url}/batches/{batch_id}", headers=self._headers())
                if r.status_code == 200:
                    return r.json()
                return None
        except Exception as e:
            logger.error(f"Failed to get batch status: {e}")
            return None

    async def list_batch_executions(self, batch_id: str) -> Optional[Dict[str, Any]]:
        if not self.is_enabled:
            return None
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.get(f"{self.base_url}/batches/{batch_id}/executions", headers=self._headers())
                if r.status_code == 200:
                    return r.json()
                return None
        except Exception as e:
            logger.error(f"Failed to list batch executions: {e}")
            return None


# Singleton instance
bolna_client = BolnaClient()
