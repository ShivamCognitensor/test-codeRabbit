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
    """Root endpoint."""
    return success_response(
        message="LMS FinAI Service",
        data={
            "service": "lms-finai",
            "version": "2.0.0",
        }
    )


@router.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)):
    """Health check endpoint."""
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
    """Kubernetes-style readiness probe."""
    return await health_check(db)
