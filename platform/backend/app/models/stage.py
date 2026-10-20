# -*- coding: utf-8 -*-
"""Stage flow model: stage runs, approval tasks, artifact versions.

The two-level state machine (architecture.md §5):

- project level: draft -> active -> accepted -> archived
- stage level:   each stage_run goes in_progress -> under_review ->
  approved | returned. A "returned" run is kept as history; rework
  starts a NEW run of the same stage with round + 1 (audit trail).
"""
import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.project import StageKey


class StageRunStatus(str, enum.Enum):
    IN_PROGRESS = "in_progress"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    RETURNED = "returned"


class ApprovalStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    RETURNED = "returned"


class ArtifactFormat(str, enum.Enum):
    MD = "md"
    DOCX = "docx"
    HTML = "html"


class StageRun(Base):
    """One attempt of one stage of one project.

    ``session_id`` binds the run to its AgentScope runtime session
    (created via runtime_client once that lands); NULL until then.
    """

    __tablename__ = "stage_runs"

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id"), index=True
    )
    stage: Mapped[StageKey] = mapped_column(
        Enum(StageKey, name="stage_key"), nullable=False
    )
    status: Mapped[StageRunStatus] = mapped_column(
        Enum(StageRunStatus, name="stage_run_status"),
        default=StageRunStatus.IN_PROGRESS,
        nullable=False,
    )
    # 1 for the first attempt, +1 per rework round after a return.
    round: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False
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

    artifacts: Mapped[list["ArtifactVersion"]] = relationship(
        back_populates="stage_run"
    )
    approvals: Mapped[list["ApprovalTask"]] = relationship(
        back_populates="stage_run"
    )


class ApprovalTask(Base):
    """A pending human decision on a submitted stage run."""

    __tablename__ = "approval_tasks"

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    stage_run_id: Mapped[int] = mapped_column(
        ForeignKey("stage_runs.id"), index=True
    )
    approver_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), index=True
    )
    status: Mapped[ApprovalStatus] = mapped_column(
        Enum(ApprovalStatus, name="approval_status"),
        default=ApprovalStatus.PENDING,
        nullable=False,
    )
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )

    stage_run: Mapped[StageRun] = relationship(back_populates="approvals")


class ArtifactVersion(Base):
    """An immutable version of a stage's deliverable (PRD, prototype...).

    Content lives on disk under ``settings.artifact_dir``; the DB row
    pins the version chain (v1 returned, v2 approved, ...).
    """

    __tablename__ = "artifact_versions"
    __table_args__ = (
        UniqueConstraint(
            "stage_run_id", "version_no", name="uq_artifact_versions_run_no"
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    stage_run_id: Mapped[int] = mapped_column(
        ForeignKey("stage_runs.id"), index=True
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(200))
    format: Mapped[ArtifactFormat] = mapped_column(
        Enum(ArtifactFormat, name="artifact_format"),
        default=ArtifactFormat.MD,
        nullable=False,
    )
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    stage_run: Mapped[StageRun] = relationship(back_populates="artifacts")
