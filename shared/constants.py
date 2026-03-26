"""
Common constants for all LMS services.

Usage:
    from shared.constants import SERVICE_URLS, DEFAULT_PAGE_SIZE
"""

# =============================================================================
# Service URLs (Docker network names)
# =============================================================================
SERVICE_URLS = {
    "gateway": "http://gateway:8000",
    "identity": "http://identity:8001",
    "config": "http://config:8002",
    "lead_ops": "http://lead-ops:8003",
    "audit": "http://audit:8004",
    "notification": "http://notification:8005",
    "reports": "http://reports:8006",
    "finai": "http://finai:8007",
    "verification": "http://verification:8008",
}

# =============================================================================
# Service Ports
# =============================================================================
SERVICE_PORTS = {
    "gateway": 8000,
    "identity": 8001,
    "config": 8002,
    "lead_ops": 8003,
    "audit": 8004,
    "notification": 8005,
    "reports": 8006,
    "finai": 8007,
    "verification": 8008,
}

# =============================================================================
# Pagination
# =============================================================================
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
MIN_PAGE_SIZE = 1

# =============================================================================
# Token Expiry (seconds)
# =============================================================================
ACCESS_TOKEN_EXPIRY = 3600  # 1 hour
REFRESH_TOKEN_EXPIRY = 604800  # 7 days
SERVICE_TOKEN_EXPIRY = 86400  # 24 hours
OTP_EXPIRY = 300  # 5 minutes

# =============================================================================
# Security
# =============================================================================
MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_DURATION_MINUTES = 30
PASSWORD_MIN_LENGTH = 8

# =============================================================================
# Headers
# =============================================================================
CORRELATION_ID_HEADER = "X-Correlation-ID"
SERVICE_TOKEN_HEADER = "X-Service-Token"

# =============================================================================
# User Types
# =============================================================================
USER_TYPE_INTERNAL = 0
USER_TYPE_CSP = 1
USER_TYPE_DSA = 2
USER_TYPE_END_USER = 3

USER_TYPE_CODES = {
    0: "INTERNAL",
    1: "CSP",
    2: "DSA",
    3: "END_USER",
}

# =============================================================================
# Lead Stages
# =============================================================================
LEAD_STAGE_CAPTURE = "CAPTURE"
LEAD_STAGE_PROCESSING = "PROCESSING"
LEAD_STAGE_UNDERWRITING = "UNDERWRITING"

LEAD_STAGES = [
    LEAD_STAGE_CAPTURE,
    LEAD_STAGE_PROCESSING,
    LEAD_STAGE_UNDERWRITING,
]

# =============================================================================
# Lead Number Prefix
# =============================================================================
LEAD_NUMBER_PREFIX = "RFL"

# =============================================================================
# BRE Configuration
# =============================================================================
BRE_TOP_N_FOR_END_USER = 3
BRE_TOP_N_FOR_CSP = 5

# =============================================================================
# Staleness and Expiry (days)
# =============================================================================
LEAD_STALE_DAYS = 7
LEAD_EXPIRY_DAYS = 30

# =============================================================================
# Audit Retention
# =============================================================================
AUDIT_RETENTION_YEARS = 7

# =============================================================================
# File Upload
# =============================================================================
MAX_BULK_UPLOAD_ROWS = 10000
ALLOWED_UPLOAD_EXTENSIONS = [".csv", ".xlsx"]

# =============================================================================
# Date/Time Formats
# =============================================================================
DATE_FORMAT = "%Y-%m-%d"
DATETIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

# =============================================================================
# Income Ranges (for employment)
# =============================================================================
INCOME_RANGES = [
    "0_15K",
    "15K_25K",
    "25K_50K",
    "50K_75K",
    "75K_1L",
    "1L_2L",
    "2L_PLUS",
]

# =============================================================================
# Annual Turnover Ranges (for self-employed)
# =============================================================================
TURNOVER_RANGES = [
    "0_10L",
    "10L_25L",
    "25L_50L",
    "50L_1CR",
    "1CR_5CR",
    "5CR_PLUS",
]
