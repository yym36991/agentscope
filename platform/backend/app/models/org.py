# -*- coding: utf-8 -*-
"""Organisation model: users, groups (departments), memberships.

Maps to architecture.md §4.2. Users self-register and land in the
"default" group until an admin moves them (decision record D5).
"""
import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class PlatformRole(str, enum.Enum):
    ADMIN = "admin"
    MEMBER = "member"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(128))
    role: Mapped[PlatformRole] = mapped_column(
        Enum(PlatformRole, name="platform_role"),
        default=PlatformRole.MEMBER,
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    groups: Mapped[list["Group"]] = relationship(
        secondary="group_members", back_populates="members"
    )


class Group(Base):
    """A department / tenant. Knowledge bases are granted per group."""

    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    # Optional hierarchy: a sub-department points at its parent.
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("groups.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    members: Mapped[list[User]] = relationship(
        secondary="group_members", back_populates="groups"
    )


class GroupMember(Base):
    __tablename__ = "group_members"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), primary_key=True
    )
    group_id: Mapped[int] = mapped_column(
        ForeignKey("groups.id"), primary_key=True
    )
