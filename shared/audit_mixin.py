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
        """
        Indicates whether the record is soft deleted.
        
        Returns:
            True if the record's `deleted_at` timestamp is set, False otherwise.
        """
        return self.deleted_at is not None

    def soft_delete(self, user_id: Optional[UUID] = None) -> None:
        """
        Mark the record as soft-deleted by setting its deletion timestamp and actor.
        
        Parameters:
            user_id (Optional[UUID]): UUID of the user performing the deletion, or None to indicate a system-initiated deletion.
        """
        self.deleted_at = datetime.utcnow()
        self.deleted_by = user_id

    def restore(self) -> None:
        """
        Mark the instance as not soft-deleted.
        
        Clears the instance's deletion timestamp and deletion user identifier so the record is treated as active again.
        """
        self.deleted_at = None
        self.deleted_by = None


def set_created_audit(entity, user_id: Optional[UUID] = None) -> None:
    """
    Populate created and updated audit fields on an entity.
    
    Sets the entity's created_at and updated_at to the current UTC time and sets created_by and updated_by to the provided user_id.
    
    Parameters:
    	entity: The ORM model instance whose audit fields will be set.
    	user_id (UUID | None): UUID of the user responsible for creation; use `None` to represent a system action.
    """
    now = datetime.utcnow()
    entity.created_at = now
    entity.created_by = user_id
    entity.updated_at = now
    entity.updated_by = user_id


def set_updated_audit(entity, user_id: Optional[UUID] = None) -> None:
    """
    Update audit fields on an entity to reflect a modification.
    
    Sets the entity's `updated_at` to the current UTC time and `updated_by` to the provided `user_id`.
    
    Parameters:
        entity: SQLAlchemy model instance whose audit fields will be updated.
        user_id (Optional[UUID]): UUID of the user performing the update; `None` indicates a system action.
    """
    entity.updated_at = datetime.utcnow()
    entity.updated_by = user_id


def set_deleted_audit(entity, user_id: Optional[UUID] = None) -> None:
    """
    Mark an ORM entity as deleted by setting its deletion timestamp and deleter.
    
    Parameters:
        entity: SQLAlchemy model instance whose `deleted_at` and `deleted_by` fields will be set.
        user_id (Optional[UUID]): UUID of the user performing the deletion; `None` indicates a system action.
    """
    entity.deleted_at = datetime.utcnow()
    entity.deleted_by = user_id
