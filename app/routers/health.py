"""Health check endpoints."""

from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from shared.responses import success_response

router = APIRouter()


@router.get("/")
async def root():
    """
    Return metadata about the LMS FinAI service.
    
    Provides a standardized success response containing the service name and version.
    
    Returns:
        A success response object with data containing "service": "lms-finai" and "version": "2.0.0" and a message "LMS FinAI Service".
    """
    return success_response(
        message="LMS FinAI Service",
        data={
            "service": "lms-finai",
            "version": "2.0.0",
        }
    )


@router.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)):
    """
    Perform a service health check including a database connectivity probe.
    
    Returns:
        A standardized success response with a `data` object containing:
        - `status`: "healthy" or "unhealthy".
        - `service`: service name ("lms-finai").
        - `version`: service version ("2.0.0").
        - `timestamp`: current UTC time in ISO 8601 format.
        - `checks`: mapping of subsystem checks (includes `"database"` with either `"healthy"` or an `"unhealthy: <error_message>"` string).
        The response `message` is "Health check passed" when `status` is "healthy", otherwise "Health check failed".
    """
    db_status = "healthy"
    try:
        await db.execute(text("SELECT 1"))
    except Exception as e:
        db_status = f"unhealthy: {str(e)}"
    
    return success_response(
        message="Health check passed" if db_status == "healthy" else "Health check failed",
        data={
            "status": "healthy" if db_status == "healthy" else "unhealthy",
            "service": "lms-finai",
            "version": "2.0.0",
            "timestamp": datetime.utcnow().isoformat(),
            "checks": {
                "database": db_status,
            }
        }
    )


@router.get("/healthz")
async def healthz(db: AsyncSession = Depends(get_db)):
    """Kubernetes-style liveness probe."""
    return await health_check(db)


@router.get("/readyz")
async def readyz(db: AsyncSession = Depends(get_db)):
    """
    Kubernetes readiness probe endpoint that returns the service's health and dependency checks.
    
    Returns:
        A response containing service status, version, UTC timestamp, and a `checks` mapping with database health details.
    """
    return await health_check(db)
