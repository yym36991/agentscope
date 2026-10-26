# -*- coding: utf-8 -*-
"""Memory & consolidation models (architecture.md §6, milestone M4).

Two artifacts of "the project remembers":

- :class:`ProjectArchive` — the project-level memory digest (§6.2 ②a):
  the authoritative handoff summary rendered into every later stage's
  kickoff, regenerated deterministically from approved artifacts.
- :class:`ConsolidationDraft` — knowledge distillation of a finished
  project (§6.4), awaiting human review before entering the owner
  group's distill KB.
"""
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ProjectArchive(Base):
    """One row per project: the running summary of what has been
    decided so far (requirement key points, budget basis, ...).

    Deliberately NOT LLM-generated: a deterministic digest of the
    approved artifacts keeps the archive chain unbreakable — a missing
    or slow model can never cost the next stage its context (§6.3).
    """

    __tablename__ = "project_archives"
    __table_args__ = (
        UniqueConstraint("project_id", name="uq_project_archives_project"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id"), index=True
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class ConsolidationDraft(Base):
    """A distilled-lessons document drafted at project acceptance.

    The draft is produced best-effort by the 知识沉淀 agent over the
    runtime (fallback: the project archive); a human then approves it
    into the owner group's distill KB through its approval task, or
    returns it with comments.
    """

    __tablename__ = "consolidation_drafts"

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id"), index=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # NULL until the review task is created (drafts may also exist
    # without a task if consolidation is disabled later).
    approval_task_id: Mapped[int | None] = mapped_column(
        ForeignKey("approval_tasks.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
