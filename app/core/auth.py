"""Authentication module for FinAI Service."""

import logging
from typing import Any, Dict, Optional

import httpx
from fastapi import Depends, Header, HTTPException, Request, status
from jose import JWTError, jwt

from .config import settings

logger = logging.getLogger(__name__)

_jwks_cache: Optional[Dict] = None
_jwks_cache_time: float = 0


async def get_jwks() -> Dict:
    """Fetch JWKS from Identity Service with caching."""
    global _jwks_cache, _jwks_cache_time
    import time
    
    if _jwks_cache and (time.time() - _jwks_cache_time) < 300:
        return _jwks_cache
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{settings.IDENTITY_SERVICE_URL}/jwks.json")
            if response.status_code == 200:
                _jwks_cache = response.json()
                _jwks_cache_time = time.time()
                return _jwks_cache
    except Exception as e:
        logger.warning(f"Failed to fetch JWKS: {e}")
    
    if _jwks_cache:
        return _jwks_cache
    
    return {"keys": []}


async def validate_token(token: str) -> Dict[str, Any]:
    """Validate JWT token using JWKS."""
    try:
        jwks = await get_jwks()
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")
        
        rsa_key = None
        for key in jwks.get("keys", []):
            if key.get("kid") == kid or kid is None:
                rsa_key = key
                break
        
        if rsa_key:
            payload = jwt.decode(
                token,
                rsa_key,
                algorithms=["RS256"],
                options={"verify_aud": False},
            )
            return payload
        
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token key",
        )
        
    except JWTError as e:
        logger.warning(f"JWT validation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )


async def get_current_user(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None),
    x_user_type: Optional[str] = Header(None),
    x_user_role: Optional[str] = Header(None),
    x_user_permissions: Optional[str] = Header(None),
) -> Dict[str, Any]:
    """Get current user from request (required)."""
    if x_user_id:
        permissions = []
        if x_user_permissions:
            permissions = [p.strip() for p in x_user_permissions.split(",") if p.strip()]
        
        return {
            "user_id": x_user_id,
            "user_type": x_user_type,
            "role_code": x_user_role,
            "permissions": permissions,
            "token": authorization[7:] if authorization and authorization.startswith("Bearer ") else None,
        }
    
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
        try:
            payload = await validate_token(token)
            return {
                "user_id": payload.get("sub"),
                "user_type": payload.get("user_type_code"),
                "role_code": payload.get("role_code"),
                "permissions": payload.get("permissions", []),
                "token": token,  # Include token for context enrichment
            }
        except HTTPException:
            pass
    
    if settings.DEBUG:
        return {
            "user_id": "00000000-0000-0000-0000-000000000001",
            "user_type": "INTERNAL",
            "role_code": "SUPER_ADMIN",
            "permissions": ["*"],
            "token": None,
        }
    
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
    )


async def get_optional_user(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None),
    x_user_type: Optional[str] = Header(None),
    x_user_role: Optional[str] = Header(None),
    x_user_permissions: Optional[str] = Header(None),
) -> Optional[Dict[str, Any]]:
    """Get current user from request (optional - returns None if not authenticated)."""
    if x_user_id:
        permissions = []
        if x_user_permissions:
            permissions = [p.strip() for p in x_user_permissions.split(",") if p.strip()]
        
        return {
            "user_id": x_user_id,
            "user_type": x_user_type,
            "role_code": x_user_role,
            "permissions": permissions,
            "token": authorization[7:] if authorization and authorization.startswith("Bearer ") else None,
        }
    
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
        try:
            payload = await validate_token(token)
            return {
                "user_id": payload.get("sub"),
                "user_type": payload.get("user_type_code"),
                "role_code": payload.get("role_code"),
                "permissions": payload.get("permissions", []),
                "token": token,
            }
        except HTTPException:
            pass
    
    # Return None if not authenticated (don't raise)
    return None


def require_permission(permission: str):
    """Dependency to require a specific permission."""
    async def check_permission(
        current_user: Dict = Depends(get_current_user),
    ) -> Dict:
        permissions = current_user.get("permissions", [])
        
        if "*" in permissions or current_user.get("role_code") == "SUPER_ADMIN":
            return current_user
        
        if permission not in permissions:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied: {permission} required",
            )
        
        return current_user
    
    return check_permission


async def get_internal_caller(
    x_service_name: Optional[str] = Header(None),
) -> Optional[str]:
    """Get internal service caller."""
    return x_service_name
