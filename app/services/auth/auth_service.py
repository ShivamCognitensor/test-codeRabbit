import base64
import time
from typing import Optional, List
from uuid import UUID, uuid5, NAMESPACE_DNS

import httpx
from jose import jwt, JWTError
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Depends, HTTPException, Request, status

from app.core.config import get_settings
from app.clients.config_client import config_client

settings = get_settings()

_jwks_cache: Optional[dict] = None
_jwks_cache_time: Optional[float] = None
_jwks_cache_ttl = 3600


class AuthService:
    async def get_jwks() -> dict:
        """Fetch and cache JWKS from Identity Service."""
        global _jwks_cache, _jwks_cache_time

        current_time = time.time()
        if _jwks_cache and _jwks_cache_time and (current_time - _jwks_cache_time) < _jwks_cache_ttl:
            return _jwks_cache

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(settings.jwks_url)
                response.raise_for_status()
                _jwks_cache = response.json()
                _jwks_cache_time = current_time
                return _jwks_cache
        except Exception as e:
            if _jwks_cache:
                # Return stale cache if fetch fails
                return _jwks_cache
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Failed to fetch JWKS: {str(e)}",
            )


    def get_rsa_key(jwks: dict, kid: str) -> Optional[dict]:
        """Get RSA key from JWKS by kid."""
        for key in jwks.get("keys", []):
            if key.get("kid") == kid:
                return key
        return None


    def _base64url_decode(value: str) -> bytes:
        padding = 4 - len(value) % 4
        if padding != 4:
            value += "=" * padding
        return base64.urlsafe_b64decode(value)


    async def verify_token(token: str) -> dict:
        """Verify JWT token and return claims."""
        try:
            # Decode header to get kid
            header = jwt.get_unverified_header(token)
            kid = header.get("kid")
            if not kid:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Missing kid in token header",
                )

            # Get JWKS and RSA key
            jwks = await AuthService.get_jwks()
            rsa_key = AuthService.get_rsa_key(jwks, kid)
            if not rsa_key:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Unable to find appropriate key",
                )

            # Construct RSA public key
            from cryptography.hazmat.backends import default_backend
            from cryptography.hazmat.primitives.asymmetric import rsa

            n_bytes = AuthService._base64url_decode(rsa_key["n"])
            e_bytes = AuthService._base64url_decode(rsa_key["e"])

            n = int.from_bytes(n_bytes, "big")
            e = int.from_bytes(e_bytes, "big")

            public_key = rsa.RSAPublicNumbers(e, n).public_key(default_backend())
            # Verify token
            payload = jwt.decode(
                token,
                public_key,
                algorithms=["RS256"],
                audience=settings.jwt_audience,
                options={"verify_exp": True, "verify_aud": True},
            )

            return payload

        except jwt.ExpiredSignatureError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has expired",
            )
        except jwt.JWTClaimsError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token claims",
            )
        except JWTError as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid token: {str(e)}",
            )