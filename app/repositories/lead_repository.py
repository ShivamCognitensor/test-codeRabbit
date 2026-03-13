from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.crm_models import LeadCRM, MasterProduct


class LeadRepository:
    def __init__(self, db: AsyncSession):
        """
        Initialize the repository with an asynchronous database session.
        
        Stores the provided AsyncSession on the instance for use by repository methods.
        """
        self.db = db

    async def get_required_docs(self, user_id):
        """
        Retrieve the list of required documents for the PERSONAL_LOAN product associated with the given lead.
        
        Parameters:
            user_id: Identifier of the lead to look up.
        
        Returns:
            list: The product's required documents if both the lead and product exist, otherwise an empty list.
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