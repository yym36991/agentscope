# -*- coding: utf-8 -*-
"""Organisation admin (architecture.md §13 D5): groups CRUD and moving
users between departments — the UI closure for what until now was
hand-edited DB rows. Admin only throughout."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from typing import Literal

from app.api.deps import get_current_user
from app.api.kbs import GroupOut, _require_admin
from app.db import get_db
from app.models import Group, GroupMember, KbGrant, PlatformRole, User

router = APIRouter(tags=["org"])


class AdminUserOut(BaseModel):
    id: int
    username: str
    display_name: str
    role: str
    is_active: bool
    groups: list[GroupOut]


class UserPatchIn(BaseModel):
    display_name: str | None = Field(
        default=None, min_length=1, max_length=128
    )
    role: Literal["admin", "member"] | None = None
    is_active: bool | None = None


class UserGroupsIn(BaseModel):
    group_ids: list[int]


class GroupCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)


async def _get_group_or_404(db: AsyncSession, group_id: int) -> Group:
    group = await db.get(Group, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="group not found")
    return group


@router.get("/admin/users", response_model=list[AdminUserOut])
async def list_admin_users(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[AdminUserOut]:
    _require_admin(user)
    users = (
        await db.scalars(
            select(User)
            .options(selectinload(User.groups))
            .order_by(User.id)
        )
    ).all()
    return [
        AdminUserOut(
            id=u.id,
            username=u.username,
            display_name=u.display_name,
            role=u.role.value,
            is_active=u.is_active,
            groups=[
                GroupOut(id=g.id, name=g.name) for g in sorted(u.groups, key=lambda g: g.id)
            ],
        )
        for u in users
    ]


@router.patch("/admin/users/{user_id}", response_model=AdminUserOut)
async def patch_admin_user(
    user_id: int,
    payload: UserPatchIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AdminUserOut:
    _require_admin(user)
    target = await db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="user not found")
    # Self-guard: the last admin locking themselves out helps nobody.
    if target.id == user.id and (
        payload.role == "member" or payload.is_active is False
    ):
        raise HTTPException(
            status_code=400, detail="不能降级或停用自己的账号"
        )
    if payload.display_name is not None:
        target.display_name = payload.display_name
    if payload.role is not None:
        target.role = PlatformRole(payload.role)
    if payload.is_active is not None:
        target.is_active = payload.is_active
    await db.commit()
    await db.refresh(target, attribute_names=["groups"])
    return AdminUserOut(
        id=target.id,
        username=target.username,
        display_name=target.display_name,
        role=target.role.value,
        is_active=target.is_active,
        groups=[
            GroupOut(id=g.id, name=g.name)
            for g in sorted(target.groups, key=lambda g: g.id)
        ],
    )


@router.put("/admin/users/{user_id}/groups", response_model=AdminUserOut)
async def set_user_groups(
    user_id: int,
    payload: UserGroupsIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AdminUserOut:
    """Replace the user's department memberships (kb grants follow the
    group, so moving departments re-scopes their knowledge bases)."""
    _require_admin(user)
    target = await db.get(User, user_id, options=[selectinload(User.groups)])
    if target is None:
        raise HTTPException(status_code=404, detail="user not found")
    groups: list[Group] = []
    if payload.group_ids:
        rows = await db.scalars(
            select(Group).where(Group.id.in_(payload.group_ids))
        )
        groups = list(rows.all())
        if len(groups) != len(set(payload.group_ids)):
            raise HTTPException(
                status_code=404, detail="部分小组不存在，请刷新后重试"
            )
    target.groups = groups
    await db.commit()
    await db.refresh(target, attribute_names=["groups"])
    return AdminUserOut(
        id=target.id,
        username=target.username,
        display_name=target.display_name,
        role=target.role.value,
        is_active=target.is_active,
        groups=[
            GroupOut(id=g.id, name=g.name)
            for g in sorted(target.groups, key=lambda g: g.id)
        ],
    )


@router.post("/groups", response_model=GroupOut, status_code=201)
async def create_group(
    payload: GroupCreateIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GroupOut:
    _require_admin(user)
    name = payload.name.strip()
    exists = await db.scalar(select(Group).where(Group.name == name))
    if exists is not None:
        raise HTTPException(status_code=409, detail=f"小组「{name}」已存在")
    group = Group(name=name)
    db.add(group)
    await db.commit()
    await db.refresh(group)
    return GroupOut(id=group.id, name=group.name)


@router.patch("/groups/{group_id}", response_model=GroupOut)
async def rename_group(
    group_id: int,
    payload: GroupCreateIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GroupOut:
    _require_admin(user)
    group = await _get_group_or_404(db, group_id)
    name = payload.name.strip()
    clash = await db.scalar(
        select(Group).where(Group.name == name, Group.id != group.id)
    )
    if clash is not None:
        raise HTTPException(status_code=409, detail=f"小组「{name}」已存在")
    group.name = name
    await db.commit()
    await db.refresh(group)
    return GroupOut(id=group.id, name=group.name)


@router.delete("/groups/{group_id}", status_code=204)
async def delete_group(
    group_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    _require_admin(user)
    group = await _get_group_or_404(db, group_id)
    member_count = await db.scalar(
        select(func.count())
        .select_from(GroupMember)
        .where(GroupMember.group_id == group.id)
    )
    if member_count:
        raise HTTPException(
            status_code=409,
            detail=f"小组里还有 {member_count} 名成员，先移走再删除",
        )
    grant_count = await db.scalar(
        select(func.count())
        .select_from(KbGrant)
        .where(KbGrant.group_id == group.id)
    )
    if grant_count:
        raise HTTPException(
            status_code=409,
            detail=f"小组还挂着 {grant_count} 条知识库授权，先解除再删除",
        )
    await db.delete(group)
    await db.commit()
