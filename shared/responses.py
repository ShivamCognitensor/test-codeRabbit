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
    """
    Return the current correlation/request ID stored in the context.
    
    Returns:
        str: The correlation ID from the context, or "unknown" if none is set.
    """
    return correlation_id_var.get() or "unknown"


def set_correlation_id(correlation_id: str) -> None:
    """Set correlation ID in context."""
    correlation_id_var.set(correlation_id)


def get_meta() -> Dict[str, str]:
    """
    Builds a standardized metadata dictionary for responses.
    
    Returns:
        meta (Dict[str, str]): Metadata containing:
            - `timestamp`: Current UTC time in ISO 8601 format with a trailing "Z".
            - `request_id`: Correlation/request identifier from the current context or "unknown".
            - `version`: API metadata version string ("2.0").
    """
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
    Builds a standardized success payload for API responses.
    
    If `data` is omitted and `message` is not a string, `message` is treated as the response data and the message is set to "OK".
    
    Parameters:
        message (str | Any): Human-readable message or, when `data` is omitted and `message` is not a string, the response data.
        data (Any, optional): Response data (e.g., dict, list, or other serializable object). Defaults to None.
    
    Returns:
        Dict[str, Any]: A dict with keys:
            - `success`: True
            - `message`: the response message
            - `data`: the response payload or None
            - `errors`: None
            - `meta`: metadata dictionary (timestamp, request_id, version)
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
    Builds a standardized error response payload.
    
    Parameters:
        message (str): Human-readable error message.
        error_code (str): Machine-readable error code (e.g., "VAL_001").
        details (Optional[Union[str, Dict, List]]): Optional additional error details to include on the error entry.
        status_code (int): HTTP status code for reference only; not included in the returned payload.
    
    Returns:
        dict: Response payload with keys:
            - success: False
            - message: the provided message
            - data: None
            - errors: list containing a single error object with `code`, `message`, and optional `details`
            - meta: metadata from get_meta()
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
    Builds a standardized response payload for validation failures.
    
    Parameters:
        errors (List[Dict[str, Any]]): List of validation error objects (e.g., each containing keys like "field", "code", and "message").
        message (str): Overall error message shown at the top-level of the response.
    
    Returns:
        Dict[str, Any]: Response dict with keys:
            - "success": False
            - "message": the provided message
            - "data": None
            - "errors": the provided list of error objects
            - "meta": metadata dictionary from get_meta()
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
    Builds a standardized paginated response payload.
    
    Parameters:
        message: Human-readable success message.
        items: List of items for the current page.
        page: Current page number (1-indexed).
        page_size: Number of items per page; if <= 0, `total_pages` will be 0.
        total_items: Total number of items across all pages.
    
    Returns:
        A dict containing:
            - `success`: True
            - `message`: the provided message
            - `data`: dict with `items` and `pagination` (keys: `page`, `page_size`, `total_items`, `total_pages`)
            - `errors`: None
            - `meta`: metadata produced by `get_meta()`
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
