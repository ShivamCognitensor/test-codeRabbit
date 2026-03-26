"""
Standard response format for all LMS services.

Usage:
    from shared.responses import success_response, error_response, paginated_response

    @app.get("/api/v1/users")
    async def list_users():
        users = await user_service.list()
        return success_response("Users retrieved", users)

    @app.get("/api/v1/users/{id}")
    async def get_user(id: str):
        user = await user_service.get(id)
        if not user:
            return error_response("User not found", ErrorCode.RES_NOT_FOUND, status_code=404)
        return success_response("User retrieved", user)
"""

from datetime import datetime
from typing import Any, Dict, List, Optional, Union
from contextvars import ContextVar

# Context variable for correlation ID (set by middleware)
correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="")


def get_correlation_id() -> str:
    """Get current correlation ID from context."""
    return correlation_id_var.get() or "unknown"


def set_correlation_id(correlation_id: str) -> None:
    """Set correlation ID in context."""
    correlation_id_var.set(correlation_id)


def get_meta() -> Dict[str, str]:
    """Generate response metadata."""
    return {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "request_id": get_correlation_id(),
        "version": "2.0",
    }


def success_response(
    message:  Union[str, Any],
    data: Any = None,
) -> Dict[str, Any]:
    """
    Create a success response.

    Args:
        message: Human-readable success message
        data: Response data (can be dict, list, or any serializable object)

    Returns:
        Standardized response dict
    """

    if data is None and not isinstance(message, str):
        data = message
        message = "OK"

    return {
        "success": True,
        "message": message,
        "data": data,
        "errors": None,
        "meta": get_meta(),
    }


def error_response(
    message: str,
    error_code: str,
    details: Optional[Union[str, Dict, List]] = None,
    status_code: int = 400,
) -> Dict[str, Any]:
    """
    Create an error response.

    Args:
        message: Human-readable error message
        error_code: Machine-readable error code (e.g., "VAL_001")
        details: Additional error details
        status_code: HTTP status code (not included in response, for reference)

    Returns:
        Standardized error response dict
    """
    errors = [
        {
            "code": error_code,
            "message": message,
        }
    ]
    if details:
        errors[0]["details"] = details

    return {
        "success": False,
        "message": message,
        "data": None,
        "errors": errors,
        "meta": get_meta(),
    }


def validation_error_response(
    errors: List[Dict[str, Any]],
    message: str = "Validation failed",
) -> Dict[str, Any]:
    """
    Create a validation error response.

    Args:
        errors: List of validation errors, each with 'field', 'code', 'message'
        message: Overall error message

    Returns:
        Standardized validation error response dict

    Example:
        errors = [
            {"field": "email", "code": "VAL_007", "message": "Invalid email format"},
            {"field": "phone", "code": "VAL_008", "message": "Phone must be 10 digits"}
        ]
        return validation_error_response(errors)
    """
    return {
        "success": False,
        "message": message,
        "data": None,
        "errors": errors,
        "meta": get_meta(),
    }


def paginated_response(
    message: str,
    items: List[Any],
    page: int,
    page_size: int,
    total_items: int,
) -> Dict[str, Any]:
    """
    Create a paginated response.

    Args:
        message: Human-readable success message
        items: List of items for current page
        page: Current page number (1-indexed)
        page_size: Number of items per page
        total_items: Total number of items across all pages

    Returns:
        Standardized paginated response dict
    """
    total_pages = (total_items + page_size - 1) // page_size if page_size > 0 else 0

    return {
        "success": True,
        "message": message,
        "data": {
            "items": items,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total_items": total_items,
                "total_pages": total_pages,
            },
        },
        "errors": None,
        "meta": get_meta(),
    }
