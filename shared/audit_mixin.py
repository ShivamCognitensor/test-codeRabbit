"""
Standard audit columns mixin for all LMS database models.

ALL database tables MUST use this mixin for consistent audit tracking.

Usage:
    from shared.audit_mixin import AuditMixin

    class User(Base, AuditMixin):
        __tablename__ = "users"
        
        id = Column(UUID, primary_key=True, default=uuid4)
        email = Column(String(255), unique=True)
        # ... other columns
        # AuditMixin automatically adds:
        # - created_at, created_by
        # - updated_at, updated_by
        # - deleted_at, deleted_by
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import Column, DateTime, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID


class AuditMixin:
    """
    Mixin class providing standard audit columns for all models.

    Columns:
    - created_at: When the record was created (auto-set)
    - created_by: User who created the record (NULL for system)
    - updated_at: When the record was last updated (auto-updated)
    - updated_by: User who last updated the record
    - deleted_at: When the record was soft-deleted (NULL = active)
    - deleted_by: User who deleted the record
    """

    created_at = Column(
        DateTime,
        nullable=False,
        default=func.now(),
        comment="Timestamp when record was created",
    )
    created_by = Column(
        PGUUID,
        nullable=True,
        comment="User ID who created this record (NULL for system)",
    )
    updated_at = Column(
        DateTime,
        nullable=False,
        default=func.now(),
        onupdate=func.now(),
        comment="Timestamp when record was last updated",
    )
    updated_by = Column(
        PGUUID,
        nullable=True,
        comment="User ID who last updated this record",
    )
    deleted_at = Column(
        DateTime,
        nullable=True,
        comment="Soft delete timestamp (NULL = active record)",
    )
    deleted_by = Column(
        PGUUID,
        nullable=True,
        comment="User ID who deleted this record",
    )

    @property
    def is_deleted(self) -> bool:
        """Check if record is soft-deleted."""
        return self.deleted_at is not None

    def soft_delete(self, user_id: Optional[UUID] = None) -> None:
        """Mark record as deleted."""
        self.deleted_at = datetime.utcnow()
        self.deleted_by = user_id

    def restore(self) -> None:
        """Restore a soft-deleted record."""
        self.deleted_at = None
        self.deleted_by = None


def set_created_audit(entity, user_id: Optional[UUID] = None) -> None:
    """
    Set audit fields for a new record.

    Args:
        entity: The SQLAlchemy model instance
        user_id: UUID of the user creating the record (None for system)
    """
    now = datetime.utcnow()
    entity.created_at = now
    entity.created_by = user_id
    entity.updated_at = now
    entity.updated_by = user_id


def set_updated_audit(entity, user_id: Optional[UUID] = None) -> None:
    """
    Set audit fields for an updated record.

    Args:
        entity: The SQLAlchemy model instance
        user_id: UUID of the user updating the record (None for system)
    """
    entity.updated_at = datetime.utcnow()
    entity.updated_by = user_id


def set_deleted_audit(entity, user_id: Optional[UUID] = None) -> None:
    """
    Set audit fields for soft delete.

    Args:
        entity: The SQLAlchemy model instance
        user_id: UUID of the user deleting the record (None for system)
    """
    entity.deleted_at = datetime.utcnow()
    entity.deleted_by = user_id
