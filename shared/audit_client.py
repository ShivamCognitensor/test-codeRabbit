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
        self.base_url = audit_service_url
        self.service_name = service_name
        self.timeout = timeout
    
    def _get_headers(self) -> Dict[str, str]:
        """Get headers for service-to-service communication."""
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
        Log an audit event to the Audit Service.
        
        Args:
            event_type: Event type (CREATE, UPDATE, DELETE, LOGIN, LOGOUT, etc.)
            action: Specific action (e.g., "user.login", "lead.status_change")
            entity_type: Type of entity (user, lead, borrower, etc.)
            entity_id: ID of the entity
            actor_user_id: User who performed the action
            actor_user_type: User type (INTERNAL, CSP, END_USER)
            actor_role: User role
            actor_csp_code: CSP code if applicable
            old_value: Previous state (for updates)
            new_value: New state
            metadata: Additional context
            status: SUCCESS, FAILED, ERROR
            error_message: Error details if failed
            correlation_id: Request correlation ID
        
        Returns:
            True if logged successfully, False otherwise
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
        """Convenience method for logging user events."""
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
        """Convenience method for logging authentication events."""
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
        """Convenience method for logging config events."""
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
        """Convenience method for logging verification events."""
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
