from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.crm_models import LeadCRM, MasterProduct


class LeadRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_required_docs(self, user_id):
        """
        Example logic:
        - Find user's lead
        - Find associated product
        - Return required documents
        """

        # 1. Find lead
        result = await self.db.execute(
            select(LeadCRM).where(LeadCRM.lead_id == user_id)
        )
        lead = result.scalar_one_or_none()
        if not lead:
            return []

        # 2. Find product (example assumes product_name is stored)
        result = await self.db.execute(
            select(MasterProduct).where(
                MasterProduct.product_name == "PERSONAL_LOAN"
            )
        )
        product = result.scalar_one_or_none()

        return product.required_docs if product else []