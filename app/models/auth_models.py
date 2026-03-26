from pydantic import BaseModel
from typing import List, Optional
from uuid import UUID


class UserClaims(BaseModel):
    user_id: UUID
    role_code: str
    partner_id: Optional[UUID] = None
    sub_partner_id: Optional[UUID] = None
    region_ids: List[UUID] = []
    product_permissions: List[str] = []
    permissions_version: Optional[str] = None
    pii_mask_level: str = "PARTIAL"
    risk_level: str = "LOW"