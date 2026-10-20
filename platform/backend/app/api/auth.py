# -*- coding: utf-8 -*-
"""Self-service registration and login (decision records D5, §13).

Registering lands the user in the "default" group. Login issues a JWT;
accounts without a password (the dev bootstrap) log in by username only
until bank SSO/LDAP replaces this flow.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user
from app.core.security import (
    create_access_token,
    hash_password,
    verify_password,
)
from app.db import get_db
from app.models import Group, User

router = APIRouter(tags=["auth"])

DEFAULT_GROUP = "default"


class RegisterIn(BaseModel):
    username: str = Field(
        min_length=2, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$"
    )
    display_name: str | None = Field(default=None, max_length=128)
    password: str | None = Field(default=None, min_length=8, max_length=128)


class LoginIn(BaseModel):
    username: str
    password: str | None = None


class UserOut(BaseModel):
    id: int
    username: str
    display_name: str
    groups: list[str]

    model_config = {"from_attributes": True}


class LoginOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


@router.post("/auth/register", response_model=UserOut, status_code=201)
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
        password_hash=(
            hash_password(payload.password) if payload.password else None
        ),
    )
    user.groups.append(group)
    db.add(user)
    await db.commit()
    return UserOut(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        groups=[g.name for g in user.groups],
    )


@router.post("/auth/login", response_model=LoginOut)
async def login(payload: LoginIn, db: AsyncSession = Depends(get_db)) -> LoginOut:
    user = await db.scalar(
        select(User)
        .where(User.username == payload.username)
        .options(selectinload(User.groups))
    )
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="unknown username")

    if user.password_hash is None:
        # Dev bootstrap account: no password set yet.
        if payload.password is not None:
            raise HTTPException(
                status_code=401, detail="no password set for this account"
            )
    elif payload.password is None or not verify_password(
        payload.password, user.password_hash
    ):
        raise HTTPException(status_code=401, detail="wrong password")

    return LoginOut(
        access_token=create_access_token(user.id, user.username),
        user=UserOut(
            id=user.id,
            username=user.username,
            display_name=user.display_name,
            groups=[g.name for g in user.groups],
        ),
    )


@router.get("/users/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        groups=[g.name for g in user.groups],
    )
