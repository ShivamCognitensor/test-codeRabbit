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
        """
        Initialize the client with configuration values loaded from application settings.
        
        Sets these instance attributes from settings:
        - base_url: API base URL.
        - api_key: API key used for Authorization.
        - default_agent_id: default agent identifier.
        - default_from_phone: default originating phone number.
        - timeout: request timeout in seconds.
        
        Also logs the API key value at the info level.
        """
        self.base_url = settings.BOLNA_API_BASE
        self.api_key = settings.BOLNA_API_KEY
        self.default_agent_id = settings.BOLNA_DEFAULT_AGENT_ID
        self.default_from_phone = settings.BOLNA_DEFAULT_FROM_PHONE_NUMBER
        self.timeout = settings.REQUEST_TIMEOUT

        logger.info("bolna api key----------", settings.BOLNA_API_KEY)

    @classmethod
    def from_settings(cls) -> "BolnaClient":
        """
        Create a BolnaClient instance after verifying the BOLNA_API_KEY setting is present.
        
        Returns:
            BolnaClient: A configured BolnaClient instance.
        
        Raises:
            RuntimeError: If BOLNA_API_KEY is not set.
        """
        if not settings.BOLNA_API_KEY:
            raise RuntimeError("BOLNA_API_KEY is not set")
        return cls()

    @property
    def is_enabled(self) -> bool:
        """
        Indicates whether the client has an API key configured.
        
        Returns:
            `True` if an API key is set, `False` otherwise.
        """
        return bool(self.api_key)

    def _headers(self) -> Dict[str, str]:
        """
        Builds the HTTP Authorization header using the client's API key.
        
        Returns:
            dict: Mapping with the `Authorization` header set to "Bearer <api_key>".
        """
        return {
            "Authorization": f"Bearer {self.api_key}",
        }

    def _json_headers(self) -> Dict[str, str]:
        """
        Return HTTP headers combining the client's Authorization header with the JSON content type.
        
        Returns:
            dict: HTTP headers including the Authorization Bearer token and "Content-Type": "application/json".
        """
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
        """
        Initiates an outbound call via the Bolna.ai API for a specified agent and recipient.
        
        Supports both new-style arguments (to_phone, agent_id, from_phone, context, webhook_url)
        and legacy keyword names which are mapped when present.
        
        Parameters:
            to_phone (str | None): Recipient phone number.
            agent_id (str | None): Agent identifier; falls back to the client's default_agent_id if not provided.
            from_phone (str | None): Caller phone number; falls back to the client's default_from_phone if not provided.
            context (dict | None): Arbitrary user data attached to the call (sent as `user_data`).
            webhook_url (str | None): URL to receive call lifecycle webhooks.
            **kwargs: Legacy-style fields accepted and mapped when present:
                - recipient_phone_number: mapped to `to_phone`
                - from_phone_number: mapped to `from_phone`
                - scheduled_at: included in payload as-is
                - user_data: mapped to `context` if `context` is None
                - retry_config: included in payload as-is
        
        Returns:
            dict | None: Parsed JSON response from Bolna on success; `None` if Bolna is not configured, on error, or when the request fails.
        
        Raises:
            ValueError: If `agent_id` is not available after resolution or if no recipient phone number is provided.
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
        """
        Stop a running call execution identified by its execution ID.
        
        Returns:
            dict: JSON response from the API if the request succeeds with content.
            An empty dict if the request succeeds (status 200 or 201) but the response has no content.
            `None` if the client is disabled, the request fails, or the API returns a non-success status.
        """
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
        """
        Stop queued calls for a specific agent using the legacy agent stop endpoint.
        
        Returns:
            dict: Parsed JSON response when the request succeeds (HTTP 200/201).
            {}: Empty dict when the request succeeds but the response has no content.
            None: When the client is disabled, the request fails, or a non-success status is returned.
        """
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
        """
        Fetches the status and details of a call execution identified by execution_id.
        
        Returns:
            dict: Execution details when available, `None` otherwise.
        """
        return await self.get_call_status(execution_id)

    async def get_call_status(self, execution_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve the status of a call execution by its execution ID.
        
        Parameters:
            execution_id (str): Identifier of the call execution to query.
        
        Returns:
            Optional[Dict[str, Any]]: JSON-decoded execution details when available (HTTP 200), `None` otherwise.
        """
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
        """
        Create a batch campaign by uploading a contacts CSV file.
        
        Raises:
            ValueError: if neither `contacts_csv`/`csv_bytes` nor `file_path` is provided.
        
        Returns:
            dict: Parsed JSON response from the API on success.
            None: If the client is disabled or the request failed.
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
        """
        Schedule a batch campaign.
        
        If `scheduled_at` (legacy string) is provided without `scheduled_time`, the request is sent as multipart using `scheduled_at`. Otherwise a JSON payload is sent; if `scheduled_time` is provided it will be converted to ISO 8601 and included as `scheduled_time`.
        
        Parameters:
            batch_id (str): Identifier of the batch to schedule.
            scheduled_time (Optional[datetime]): New-style scheduled time; included in JSON as ISO 8601 when present.
            scheduled_at (Optional[str]): Legacy scheduled time string; when provided (and `scheduled_time` is not) it is sent as multipart.
        
        Returns:
            dict: Parsed JSON response on success, or an empty dict if the successful response has no content.
            None: If the client is disabled or the request fails.
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
        """
        Stop a running batch campaign identified by its batch ID.
        
        Parameters:
            batch_id (str): The identifier of the batch to stop.
        
        Returns:
            dict: Parsed JSON response on success, or an empty dict if the server returned no content.
            None: If the client is disabled, the request failed, or the server did not return a success status.
        """
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
        """
        Fetches the status of a batch campaign from the Bolna API.
        
        Parameters:
            batch_id (str): Identifier of the batch to query.
        
        Returns:
            dict: The API response containing batch status when the request succeeds.
            None: If the client is disabled, the request fails, or a non-200 status is returned.
        """
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
        """
        Fetches the list of executions for the specified batch.
        
        Parameters:
            batch_id (str): Identifier of the batch to list executions for.
        
        Returns:
            dict: Parsed JSON of executions when the request succeeds (HTTP 200).
            None: If the client is disabled, the response status is not 200, or an error occurs.
        """
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
