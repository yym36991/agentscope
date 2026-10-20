# -*- coding: utf-8 -*-
"""Meta routes (health etc.)."""
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db

router = APIRouter(tags=["meta"])


@router.get("/health")
async def health(db: AsyncSession = Depends(get_db)) -> dict:
    await db.execute(text("SELECT 1"))
    return {
        "status": "ok",
        "service": "cost-platform-backend",
        "version": "0.1.0",
    }
