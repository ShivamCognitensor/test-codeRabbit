"""
LMS Shared Code Library

This package contains shared utilities used across all LMS microservices.
Copy this folder to each service's `shared/` directory.

Contents:
- responses.py: Standard API response format
- error_codes.py: Centralized error codes
- constants.py: Shared constants
- audit_mixin.py: Database audit columns mixin
"""

from .responses import (
    success_response,
    error_response,
    paginated_response,
    validation_error_response,
)
from .error_codes import ErrorCode
from .constants import (
    SERVICE_URLS,
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    CORRELATION_ID_HEADER,
)
from .audit_mixin import AuditMixin, set_created_audit, set_updated_audit
from .audit_client import AuditClient

__all__ = [
    # Responses
    "success_response",
    "error_response",
    "paginated_response",
    "validation_error_response",
    # Error codes
    "ErrorCode",
    # Constants
    "SERVICE_URLS",
    "DEFAULT_PAGE_SIZE",
    "MAX_PAGE_SIZE",
    "CORRELATION_ID_HEADER",
    # Audit
    "AuditMixin",
    "set_created_audit",
    "set_updated_audit",
    # Audit Client
    "AuditClient",
]
