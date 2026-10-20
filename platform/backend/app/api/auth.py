# -*- coding: utf-8 -*-
"""Self-service registration (decision record D5).

A new user registers with just a username and lands in the "default"
group. Login/JWT lands in the next iteration; the schema is prepared
for it (config.jwt_secret).
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import Group, User

router = APIRouter(prefix="/auth", tags=["auth"])

DEFAULT_GROUP = "default"


class RegisterIn(BaseModel):
    username: str = Field(min_length=2, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    display_name: str | None = Field(default=None, max_length=128)


class UserOut(BaseModel):
    id: int
    username: str
    display_name: str
    groups: list[str]

    model_config = {"from_attributes": True}


@router.post("/register", response_model=UserOut, status_code=201)
async def register(
    payload: RegisterIn, db: AsyncSession = Depends(get_db)
) -> UserOut:
    existing = await db.scalar(
        select(User).where(User.username == payload.username)
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="username already taken")

    # Every user starts in the "default" group until an admin moves them.
    group = await db.scalar(select(Group).where(Group.name == DEFAULT_GROUP))
    if group is None:
        group = Group(name=DEFAULT_GROUP)
        db.add(group)

    user = User(
        username=payload.username,
        display_name=payload.display_name or payload.username,
    )
    user.groups.append(group)
    db.add(user)
    await db.commit()
    # expire_on_commit=False: id was set during flush and groups is still
    # the in-memory list — no refresh (it would expire the relationship
    # and trigger sync lazy loading, which async sessions forbid).
    return UserOut(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        groups=[g.name for g in user.groups],
    )
