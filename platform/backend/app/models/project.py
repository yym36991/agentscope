# -*- coding: utf-8 -*-
"""Project model: projects + memberships + lifecycle enums (§4.2 / §5).

The stage-level state machine (stage_runs / approval_tasks) lands in the
next migration, together with the flow logic that drives it.
"""
import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class ProjectStatus(str, enum.Enum):
    """Project-level state machine (§5.2)."""

    DRAFT = "draft"
    ACTIVE = "active"
    ACCEPTED = "accepted"
    ARCHIVED = "archived"
    SUSPENDED = "suspended"
    CANCELLED = "cancelled"


class StageKey(str, enum.Enum):
    """The six serial stages; NONE = project not started yet."""

    NONE = "none"
    REQUIREMENT = "requirement"
    PROTOTYPE = "prototype"
    BUDGET = "budget"
    TESTCASES = "testcases"
    TESTING = "testing"
    ACCEPTANCE = "acceptance"


class ProjectRole(str, enum.Enum):
    INITIATOR = "initiator"
    MANAGER = "manager"
    MEMBER = "member"
    APPROVER = "approver"
    OBSERVER = "observer"


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    name: Mapped[str] = mapped_column(String(200), index=True)
    status: Mapped[ProjectStatus] = mapped_column(
        Enum(ProjectStatus, name="project_status"),
        default=ProjectStatus.DRAFT,
        nullable=False,
    )
    current_stage: Mapped[StageKey] = mapped_column(
        Enum(StageKey, name="stage_key"),
        default=StageKey.NONE,
        nullable=False,
    )
    owner_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    owner_group_id: Mapped[int | None] = mapped_column(
        ForeignKey("groups.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    members: Mapped[list["ProjectMember"]] = relationship(
        back_populates="project"
    )


class ProjectMember(Base):
    __tablename__ = "project_members"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "user_id", name="uq_project_members_project_user"
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id"), index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[ProjectRole] = mapped_column(
        Enum(ProjectRole, name="project_role"),
        default=ProjectRole.MEMBER,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    project: Mapped[Project] = relationship(back_populates="members")
