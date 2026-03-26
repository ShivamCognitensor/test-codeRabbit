"""
Centralized error codes for all LMS services.

Usage:
    from shared.error_codes import ErrorCode

    if not user:
        return error_response("User not found", ErrorCode.USER_NOT_FOUND)
"""

from enum import Enum


class ErrorCode(str, Enum):
    """Standard error codes used across all LMS services."""

    # =========================================================================
    # Authentication (AUTH_0XX)
    # =========================================================================
    AUTH_INVALID_TOKEN = "AUTH_001"
    AUTH_EXPIRED_TOKEN = "AUTH_002"
    AUTH_INSUFFICIENT_PERMISSIONS = "AUTH_003"
    AUTH_INVALID_CREDENTIALS = "AUTH_004"
    AUTH_USER_BLOCKED = "AUTH_005"
    AUTH_OTP_EXPIRED = "AUTH_006"
    AUTH_OTP_INVALID = "AUTH_007"
    AUTH_TOO_MANY_ATTEMPTS = "AUTH_008"
    AUTH_USER_DELETED = "AUTH_009"
    AUTH_PASSWORD_WEAK = "AUTH_010"
    AUTH_PASSWORD_SAME = "AUTH_011"
    AUTH_REFRESH_TOKEN_INVALID = "AUTH_012"
    AUTH_SERVICE_TOKEN_INVALID = "AUTH_013"

    # =========================================================================
    # Validation (VAL_0XX)
    # =========================================================================
    VAL_REQUIRED_FIELD = "VAL_001"
    VAL_INVALID_FORMAT = "VAL_002"
    VAL_OUT_OF_RANGE = "VAL_003"
    VAL_INVALID_ENUM = "VAL_004"
    VAL_TOO_LONG = "VAL_005"
    VAL_TOO_SHORT = "VAL_006"
    VAL_INVALID_EMAIL = "VAL_007"
    VAL_INVALID_PHONE = "VAL_008"
    VAL_INVALID_PAN = "VAL_009"
    VAL_INVALID_DATE = "VAL_010"
    VAL_INVALID_UUID = "VAL_011"

    # =========================================================================
    # Resource (RES_0XX)
    # =========================================================================
    RES_NOT_FOUND = "RES_001"
    RES_ALREADY_EXISTS = "RES_002"
    RES_CONFLICT = "RES_003"
    RES_DELETED = "RES_004"
    RES_LOCKED = "RES_005"
    RES_VERSION_MISMATCH = "RES_006"

    # =========================================================================
    # Lead (LEAD_0XX)
    # =========================================================================
    LEAD_NOT_FOUND = "LEAD_001"
    LEAD_INVALID_TRANSITION = "LEAD_002"
    LEAD_ALREADY_ASSIGNED = "LEAD_003"
    LEAD_NOT_ASSIGNED = "LEAD_004"
    LEAD_LOCKED = "LEAD_005"
    LEAD_EXPIRED = "LEAD_006"
    LEAD_DUPLICATE = "LEAD_007"
    LEAD_INVALID_STATUS = "LEAD_008"
    LEAD_CANNOT_DELETE = "LEAD_009"

    # =========================================================================
    # BRE (BRE_0XX)
    # =========================================================================
    BRE_EVALUATION_FAILED = "BRE_001"
    BRE_NO_ELIGIBLE_LENDERS = "BRE_002"
    BRE_MISSING_DATA = "BRE_003"
    BRE_INVALID_RULES = "BRE_004"
    BRE_ALREADY_EVALUATED = "BRE_005"

    # =========================================================================
    # User (USER_0XX)
    # =========================================================================
    USER_NOT_FOUND = "USER_001"
    USER_ALREADY_EXISTS = "USER_002"
    USER_BLOCKED = "USER_003"
    USER_DELETED = "USER_004"
    USER_INVALID_ROLE = "USER_005"
    USER_INVALID_TYPE = "USER_006"

    # =========================================================================
    # Borrower (BORR_0XX)
    # =========================================================================
    BORR_NOT_FOUND = "BORR_001"
    BORR_ALREADY_EXISTS = "BORR_002"
    BORR_BLACKLISTED = "BORR_003"
    BORR_CONSENT_NOT_GRANTED = "BORR_004"

    # =========================================================================
    # Consent (CONS_0XX)
    # =========================================================================
    CONS_NOT_GRANTED = "CONS_001"
    CONS_REVOKED = "CONS_002"
    CONS_EXPIRED = "CONS_003"
    CONS_ALREADY_GRANTED = "CONS_004"

    # =========================================================================
    # Config (CONF_0XX)
    # =========================================================================
    CONF_NOT_FOUND = "CONF_001"
    CONF_INVALID_VALUE = "CONF_002"
    CONF_CANNOT_MODIFY = "CONF_003"

    # =========================================================================
    # Lender (LEND_0XX)
    # =========================================================================
    LEND_NOT_FOUND = "LEND_001"
    LEND_PRODUCT_NOT_FOUND = "LEND_002"
    LEND_INACTIVE = "LEND_003"

    # =========================================================================
    # Commission (COMM_0XX)
    # =========================================================================
    COMM_RULE_NOT_FOUND = "COMM_001"
    COMM_ALREADY_CALCULATED = "COMM_002"

    # =========================================================================
    # Bulk Upload (BULK_0XX)
    # =========================================================================
    BULK_INVALID_FILE = "BULK_001"
    BULK_TOO_MANY_ROWS = "BULK_002"
    BULK_PROCESSING_FAILED = "BULK_003"
    BULK_LIMIT_EXCEEDED = "BULK_004"

    # =========================================================================
    # Verification (VERIF_0XX)
    # =========================================================================
    VERIF_FAILED = "VERIF_001"
    VERIF_PROVIDER_ERROR = "VERIF_002"
    VERIF_ALREADY_VERIFIED = "VERIF_003"

    # =========================================================================
    # Notification (NOTIF_0XX)
    # =========================================================================
    NOTIF_NOT_FOUND = "NOTIF_001"
    NOTIF_TEMPLATE_NOT_FOUND = "NOTIF_002"
    NOTIF_DELIVERY_FAILED = "NOTIF_003"

    # =========================================================================
    # System (SYS_0XX)
    # =========================================================================
    SYS_INTERNAL_ERROR = "SYS_001"
    SYS_SERVICE_UNAVAILABLE = "SYS_002"
    SYS_RATE_LIMITED = "SYS_003"
    SYS_TIMEOUT = "SYS_004"
    SYS_DATABASE_ERROR = "SYS_005"
