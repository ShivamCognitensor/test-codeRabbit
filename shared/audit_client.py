"""Audit Service client for logging events - Shared across all services."""

import logging
from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID

import httpx

logger = logging.getLogger(__name__)


class AuditClient:
    """
    Client for Audit Service.
    
    Usage:
        from shared.audit_client import AuditClient
        
        audit_client = AuditClient(
            audit_service_url="http://localhost:8004",
            service_name="lms-identity",
        )
        
        await audit_client.log_event(
            event_type="LOGIN",
            action="user.login",
            entity_type="user",
            entity_id=str(user_id),
            actor_user_id=user_id,
            new_value={"method": "email"},
        )
    """
    
    def __init__(
        self,
        audit_service_url: str,
        service_name: str,
        timeout: float = 30.0,
    ):
        """
        Create an AuditClient configured to send audit events to a central Audit Service.
        
        Parameters:
            audit_service_url (str): Base URL of the Audit Service (including scheme) where events will be POSTed.
            service_name (str): Logical name of the calling service to include in each audit payload.
            timeout (float): HTTP request timeout in seconds for calls to the Audit Service (default 30.0).
        """
        self.base_url = audit_service_url
        self.service_name = service_name
        self.timeout = timeout
    
    def _get_headers(self) -> Dict[str, str]:
        """
        Return HTTP headers used for service-to-service audit requests.
        
        Returns:
            Dict[str, str]: Mapping of header names to values, including `Content-Type: application/json` and `X-Service-Name` set to the client's service name.
        """
        return {
            "Content-Type": "application/json",
            "X-Service-Name": self.service_name,
        }
    
    async def log_event(
        self,
        event_type: str,
        action: str,
        entity_type: Optional[str] = None,
        entity_id: Optional[str] = None,
        actor_user_id: Optional[UUID] = None,
        actor_user_type: Optional[str] = None,
        actor_role: Optional[str] = None,
        actor_csp_code: Optional[str] = None,
        old_value: Optional[Dict[str, Any]] = None,
        new_value: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        status: str = "SUCCESS",
        error_message: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> bool:
        """
        Send an audit event payload to the configured Audit Service.
        
        On HTTP 200 the method returns True; on any non-200 response or exception it logs a warning and returns False (audit failures are non-fatal to the caller).
        
        Parameters:
            event_type (str): High-level category of the event (e.g., CREATE, UPDATE, DELETE, AUTH, CONFIG).
            action (str): Specific action identifier (e.g., "user.login", "lead.status_change").
            status (str): Result of the action, typically "SUCCESS", "FAILED", or "ERROR".
            correlation_id (str, optional): Request correlation ID to link related logs and events.
        
        Returns:
            True if the audit service accepted the event (HTTP 200), False otherwise.
        """
        try:
            payload = {
                "service_name": self.service_name,
                "event_type": event_type,
                "action": action,
                "timestamp": datetime.utcnow().isoformat(),
                "status": status,
            }
            
            if correlation_id:
                payload["correlation_id"] = correlation_id
            if entity_type:
                payload["entity_type"] = entity_type
            if entity_id:
                payload["entity_id"] = str(entity_id)
            if actor_user_id:
                payload["actor_user_id"] = str(actor_user_id)
            if actor_user_type:
                payload["actor_user_type"] = actor_user_type
            if actor_role:
                payload["actor_role"] = actor_role
            if actor_csp_code:
                payload["actor_csp_code"] = actor_csp_code
            if old_value:
                payload["old_value"] = old_value
            if new_value:
                payload["new_value"] = new_value
            if metadata:
                payload["metadata"] = metadata
            if error_message:
                payload["error_message"] = error_message
            
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/internal/audit/events",
                    json=payload,
                    headers=self._get_headers(),
                )
                
                if response.status_code == 200:
                    logger.debug(f"Audit event logged: {action}")
                    return True
                else:
                    logger.warning(f"Failed to log audit event: {response.status_code}")
                    return False
                    
        except Exception as e:
            # Don't fail the main operation if audit logging fails
            logger.warning(f"Failed to log audit event: {e}")
            return False
    
    async def log_user_event(
        self,
        action: str,
        user_id: UUID,
        actor: Dict[str, Any],
        old_value: Optional[Dict[str, Any]] = None,
        new_value: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Log a user-related audit event with actor details and optional old/new values or metadata.
        
        Parameters:
            action (str): Action name (e.g., "user.update.email"); used to derive the event type.
            user_id (UUID): Identifier of the user the event is about.
            actor (Dict[str, Any]): Actor details; optional keys used are:
                - "user_id": actor's user id (string UUID)
                - "user_type": type/category of the actor
                - "role_code": actor's role code
            old_value (Optional[Dict[str, Any]]): Previous state of the entity, included in the payload when provided.
            new_value (Optional[Dict[str, Any]]): New state of the entity, included in the payload when provided.
            metadata (Optional[Dict[str, Any]]): Additional contextual data to include in the audit payload.
        
        Returns:
            true if the audit service accepted the event (HTTP 200), false otherwise.
        """
        event_type = action.split(".")[0].upper() if "." in action else "UPDATE"
        
        return await self.log_event(
            event_type=event_type,
            action=action,
            entity_type="user",
            entity_id=str(user_id),
            actor_user_id=UUID(actor.get("user_id")) if actor.get("user_id") else None,
            actor_user_type=actor.get("user_type"),
            actor_role=actor.get("role_code"),
            old_value=old_value,
            new_value=new_value,
            metadata=metadata,
        )
    
    async def log_auth_event(
        self,
        action: str,
        user_id: Optional[UUID] = None,
        email: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        status: str = "SUCCESS",
        error_message: Optional[str] = None,
    ) -> bool:
        """
        Log an authentication-related audit event for a user.
        
        Parameters:
            action (str): Identifier of the authentication action (e.g., "login.success", "login.failure").
            user_id (Optional[UUID]): UUID of the affected user, included as entity_id and actor_user_id when provided.
            email (Optional[str]): User email to include in the event's new_value payload.
            ip_address (Optional[str]): IP address associated with the authentication attempt.
            user_agent (Optional[str]): Client user agent string included in event metadata.
            status (str): Outcome of the action, such as "SUCCESS" or "FAILURE".
            error_message (Optional[str]): Error details to include when the status indicates a failure.
        
        Returns:
            bool: `true` if the audit service accepted the event (HTTP 200), `false` otherwise.
        """
        return await self.log_event(
            event_type="AUTH",
            action=action,
            entity_type="user",
            entity_id=str(user_id) if user_id else None,
            actor_user_id=user_id,
            new_value={
                "email": email,
                "ip_address": ip_address,
            },
            metadata={
                "user_agent": user_agent,
            },
            status=status,
            error_message=error_message,
        )
    
    async def log_config_event(
        self,
        action: str,
        config_type: str,
        config_id: str,
        actor: Dict[str, Any],
        old_value: Optional[Dict[str, Any]] = None,
        new_value: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Log a configuration change event for a specific configuration entity.
        
        Parameters:
            action (str): Action performed (e.g., "update", "create", "delete").
            config_type (str): Type/category of the configuration (used as entity_type).
            config_id (str): Identifier of the configuration entity (used as entity_id).
            actor (Dict[str, Any]): Actor information; expected keys: "user_id" (UUID string, optional), "user_type" (optional), "role_code" (optional).
            old_value (Optional[Dict[str, Any]]): Previous configuration state, included when available.
            new_value (Optional[Dict[str, Any]]): New configuration state, included when available.
        
        Returns:
            bool: `true` if the audit service acknowledged the event (HTTP 200), `false` otherwise.
        """
        return await self.log_event(
            event_type="CONFIG",
            action=action,
            entity_type=config_type,
            entity_id=config_id,
            actor_user_id=UUID(actor.get("user_id")) if actor.get("user_id") else None,
            actor_user_type=actor.get("user_type"),
            actor_role=actor.get("role_code"),
            old_value=old_value,
            new_value=new_value,
        )
    
    async def log_verification_event(
        self,
        action: str,
        phone: str,
        verification_type: str,
        result: Optional[Dict[str, Any]] = None,
        status: str = "SUCCESS",
        error_message: Optional[str] = None,
    ) -> bool:
        """
        Log a verification event for the given phone number, including verification type, result, status, and optional error message.
        
        Parameters:
            action (str): The action name describing the verification operation.
            phone (str): The phone number associated with the verification event (used as the entity identifier).
            verification_type (str): A short identifier for the verification method or purpose.
            result (Optional[Dict[str, Any]]): Optional details about the verification outcome.
            status (str): Event status, typically "SUCCESS" or "FAILURE". Defaults to "SUCCESS".
            error_message (Optional[str]): Optional error message describing failure details.
        
        Returns:
            bool: `true` if the audit service accepted the event (HTTP 200), `false` otherwise.
        """
        return await self.log_event(
            event_type="VERIFICATION",
            action=action,
            entity_type="verification",
            entity_id=phone,
            new_value={
                "verification_type": verification_type,
                "result": result,
            },
            status=status,
            error_message=error_message,
        )
