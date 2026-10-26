# -*- coding: utf-8 -*-
"""Knowledge-base model: kbs, group grants, project links (§7).

The L1 ``kbs`` row is the platform-side authority (typing, group
grants, project bindings); ``agentscope_kb_id`` points at the runtime
knowledge base that physically holds documents and vectors. All
visibility decisions happen on these tables — the runtime is never
asked who may see what (§7.2: filter first, retrieve second).
"""
import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.project import StageKey


class KbType(str, enum.Enum):
    """§7.1 classification; the price baseline also feeds the
    structured query tool (M3), not just RAG."""

    SPEC = "spec"  # 行业规范库
    PRICE = "price"  # 价格基准库
    CASE = "case"  # 案例库
    TEMPLATE = "template"  # 模板库
    DISTILL = "distill"  # 沉淀库 (M4 target)


class GrantLevel(str, enum.Enum):
    READ = "read"  # search / browse documents
    WRITE = "write"  # + upload / delete documents


class Kb(Base):
    __tablename__ = "kbs"

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    name: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    kb_type: Mapped[KbType] = mapped_column(
        Enum(KbType, name="kb_type"), nullable=False
    )
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # Runtime knowledge base id (documents + vectors live there).
    agentscope_kb_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    # Group that owns the KB (creator's group; admins may move it).
    owner_group_id: Mapped[int | None] = mapped_column(
        ForeignKey("groups.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )


class KbGrant(Base):
    """Group-level authorization (§4.3: visibility comes from the
    department, operations from the project role)."""

    __tablename__ = "kb_grants"
    __table_args__ = (
        UniqueConstraint("kb_id", "group_id", name="uq_kb_grants_kb_group"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    kb_id: Mapped[int] = mapped_column(ForeignKey("kbs.id"), index=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), index=True)
    level: Mapped[GrantLevel] = mapped_column(
        Enum(GrantLevel, name="grant_level"),
        default=GrantLevel.READ,
        nullable=False,
    )


class ProjectKbLink(Base):
    """Which KBs a project uses, optionally pinned to one stage
    (§4.2: requirement stage -> spec library, budget stage -> price
    library). ``stage`` NULL = bound to every stage."""

    __tablename__ = "project_kb_links"

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id"), index=True
    )
    kb_id: Mapped[int] = mapped_column(ForeignKey("kbs.id"), index=True)
    stage: Mapped[StageKey | None] = mapped_column(
        Enum(StageKey, name="stage_key"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
