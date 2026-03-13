import asyncio
from app.db.session import engine
from app.db.base import Base
from app.db import models  # IMPORTANT: imports all models

async def init_db():
    """
    Initialize the database schema by creating all tables defined on Base.metadata.
    
    This function creates any missing tables in the database associated with the async engine. Ensure all ORM models are imported before calling so their tables are present in Base.metadata.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

if __name__ == "__main__":
    asyncio.run(init_db())