# LMS Shared Code Library

This package contains shared utilities used across all LMS microservices.

## Contents

| File | Purpose |
|------|---------|
| `responses.py` | Standard API response format |
| `error_codes.py` | Centralized error codes |
| `constants.py` | Shared constants (URLs, pagination, etc.) |
| `audit_mixin.py` | Database audit columns mixin |

## Usage

### 1. Copy to Service

Copy this entire `lms-shared` folder to your service's `shared/` directory:

```bash
cp -r lms-shared/* /path/to/lms-config/shared/
```

### 2. Import in Code

```python
# Responses
from shared.responses import success_response, error_response, paginated_response

# Error codes
from shared.error_codes import ErrorCode

# Constants
from shared.constants import SERVICE_URLS, DEFAULT_PAGE_SIZE

# Audit mixin (for database models)
from shared.audit_mixin import AuditMixin, set_created_audit, set_updated_audit
```

## Examples

### API Response

```python
from fastapi import APIRouter
from shared.responses import success_response, error_response
from shared.error_codes import ErrorCode

router = APIRouter()

@router.get("/users/{user_id}")
async def get_user(user_id: str):
    user = await user_service.get(user_id)
    if not user:
        return error_response(
            "User not found",
            ErrorCode.USER_NOT_FOUND,
            status_code=404
        )
    return success_response("User retrieved", user)
```

### Database Model with Audit

```python
from sqlalchemy import Column, String
from sqlalchemy.dialects.postgresql import UUID
from uuid import uuid4

from app.core.db import Base
from shared.audit_mixin import AuditMixin

class User(Base, AuditMixin):
    __tablename__ = "users"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    email = Column(String(255), unique=True, nullable=False)
    full_name = Column(String(200), nullable=False)
    # ... other fields
    
    # AuditMixin automatically adds:
    # - created_at, created_by
    # - updated_at, updated_by  
    # - deleted_at, deleted_by
```

### Service Layer with Audit

```python
from shared.audit_mixin import set_created_audit, set_updated_audit

async def create_user(data: dict, current_user_id: UUID) -> User:
    user = User(**data)
    set_created_audit(user, current_user_id)
    db.add(user)
    await db.commit()
    return user

async def update_user(user_id: UUID, data: dict, current_user_id: UUID) -> User:
    user = await db.get(User, user_id)
    for key, value in data.items():
        setattr(user, key, value)
    set_updated_audit(user, current_user_id)
    await db.commit()
    return user

async def delete_user(user_id: UUID, current_user_id: UUID) -> User:
    user = await db.get(User, user_id)
    user.soft_delete(current_user_id)
    await db.commit()
    return user
```

## Response Format

All API responses follow this standard format:

```json
{
  "success": true,
  "message": "Operation completed",
  "data": { ... },
  "errors": null,
  "meta": {
    "timestamp": "2026-01-30T10:00:00Z",
    "request_id": "correlation-uuid",
    "version": "2.0"
  }
}
```

### Error Response

```json
{
  "success": false,
  "message": "User not found",
  "data": null,
  "errors": [
    {
      "code": "USER_001",
      "message": "User not found"
    }
  ],
  "meta": { ... }
}
```

### Paginated Response

```json
{
  "success": true,
  "message": "Users retrieved",
  "data": {
    "items": [...],
    "pagination": {
      "page": 1,
      "page_size": 20,
      "total_items": 150,
      "total_pages": 8
    }
  },
  "errors": null,
  "meta": { ... }
}
```

## Version

- **Version:** 2.0
- **Last Updated:** January 30, 2026
