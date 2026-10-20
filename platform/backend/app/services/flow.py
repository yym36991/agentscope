# -*- coding: utf-8 -*-
"""Stage flow state machine (architecture.md §5).

All stage/project transitions live here so the API layer stays thin and
the rules have exactly one implementation. Illegal transitions raise
:class:`FlowError`, which the API layer maps to HTTP 409/400.
"""
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import (
    ApprovalStatus,
    ApprovalTask,
    ArtifactFormat,
    ArtifactVersion,
    Project,
    ProjectMember,
    ProjectRole,
    ProjectStatus,
    StageKey,
    StageRun,
    StageRunStatus,
    User,
)

STAGE_ORDER: list[StageKey] = [
    StageKey.REQUIREMENT,
    StageKey.PROTOTYPE,
    StageKey.BUDGET,
    StageKey.TESTCASES,
    StageKey.TESTING,
    StageKey.ACCEPTANCE,
]

ACTIVE_RUN_STATUSES = (StageRunStatus.IN_PROGRESS, StageRunStatus.UNDER_REVIEW)


class FlowError(Exception):
    """Illegal state transition; ``status`` maps to the HTTP code."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


def next_stage(stage: StageKey) -> StageKey | None:
    """The stage that follows *stage*, or None after the last one."""
    idx = STAGE_ORDER.index(stage)
    return STAGE_ORDER[idx + 1] if idx + 1 < len(STAGE_ORDER) else None


async def require_member(db: AsyncSession, project: Project, user: User) -> None:
    """403 unless *user* is the owner or a member of *project*."""
    if project.owner_user_id == user.id:
        return
    member = await db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project.id,
            ProjectMember.user_id == user.id,
        )
    )
    if member is None:
        raise FlowError(403, "not a member of this project")


async def resolve_approver(db: AsyncSession, project: Project) -> int:
    """Approval addressee: first APPROVER-role member, else the owner.

    Decision D8: approvers resolve from project roles by default;
    explicit reassignment lands with the approval-center iteration.
    """
    approver = await db.scalar(
        select(ProjectMember)
        .where(
            ProjectMember.project_id == project.id,
            ProjectMember.role == ProjectRole.APPROVER,
        )
        .order_by(ProjectMember.id)
        .limit(1)
    )
    return approver.user_id if approver else project.owner_user_id


async def start_stage(
    db: AsyncSession, project: Project, stage: StageKey, user: User
) -> StageRun:
    """Open a new run of *stage* (round + 1 per previous rework)."""
    if project.status in (
        ProjectStatus.ACCEPTED,
        ProjectStatus.ARCHIVED,
        ProjectStatus.CANCELLED,
    ):
        raise FlowError(409, f"project is {project.status.value}, no new runs")

    # Stages run strictly in order; NONE means nothing started yet.
    if stage is StageKey.REQUIREMENT:
        if project.current_stage not in (StageKey.NONE, StageKey.REQUIREMENT):
            raise FlowError(
                409,
                f"requirement stage already passed "
                f"(current: {project.current_stage.value})",
            )
    elif project.current_stage != stage:
        raise FlowError(
            409,
            f"stage out of order: project is at "
            f"'{project.current_stage.value}', requested '{stage.value}'",
        )

    active = await db.scalar(
        select(StageRun).where(
            StageRun.project_id == project.id,
            StageRun.stage == stage,
            StageRun.status.in_(ACTIVE_RUN_STATUSES),
        )
    )
    if active is not None:
        raise FlowError(
            409,
            f"stage '{stage.value}' already has an active run "
            f"(#{active.id}, {active.status.value})",
        )

    approved = await db.scalar(
        select(StageRun.id).where(
            StageRun.project_id == project.id,
            StageRun.stage == stage,
            StageRun.status == StageRunStatus.APPROVED,
        )
    )
    if approved is not None:
        raise FlowError(409, f"stage '{stage.value}' is already approved")

    previous_rounds = await db.scalar(
        select(func.count())
        .select_from(StageRun)
        .where(
            StageRun.project_id == project.id, StageRun.stage == stage
        )
    )

    if project.current_stage is StageKey.NONE:
        project.current_stage = stage
        project.status = ProjectStatus.ACTIVE

    run = StageRun(
        project_id=project.id,
        stage=stage,
        status=StageRunStatus.IN_PROGRESS,
        round=(previous_rounds or 0) + 1,
        started_by_user_id=user.id,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    return run


async def submit_run(
    db: AsyncSession,
    run: StageRun,
    project: Project,
    title: str,
    content: str,
) -> ArtifactVersion:
    """Attach artifact v{n} to *run* and hand it to the approver."""
    if run.status != StageRunStatus.IN_PROGRESS:
        raise FlowError(
            409, f"run #{run.id} is {run.status.value}, cannot submit"
        )

    version_no = (
        await db.scalar(
            select(func.count())
            .select_from(ArtifactVersion)
            .where(ArtifactVersion.stage_run_id == run.id)
        )
        or 0
    ) + 1

    rel_path = (
        f"{project.id}/{run.stage.value}/run{run.id}-v{version_no}.md"
    )
    abs_path = Path(get_settings().artifact_dir) / rel_path
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_text(content, encoding="utf-8")

    artifact = ArtifactVersion(
        stage_run_id=run.id,
        version_no=version_no,
        title=title,
        format=ArtifactFormat.MD,
        storage_path=rel_path,
    )
    run.status = StageRunStatus.UNDER_REVIEW
    db.add(artifact)
    db.add(
        ApprovalTask(
            stage_run_id=run.id,
            approver_user_id=await resolve_approver(db, project),
            status=ApprovalStatus.PENDING,
        )
    )
    await db.commit()
    await db.refresh(artifact)
    return artifact


async def decide(
    db: AsyncSession,
    task: ApprovalTask,
    run: StageRun,
    project: Project,
    action: str,
    comment: str | None,
) -> None:
    """Record the approver's decision and advance the state machine."""
    if task.status != ApprovalStatus.PENDING:
        raise FlowError(409, f"task #{task.id} is already {task.status.value}")
    if run.status != StageRunStatus.UNDER_REVIEW:
        raise FlowError(
            409,
            f"run #{run.id} is {run.status.value}, expected under_review",
        )

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if action == "approve":
        task.status = ApprovalStatus.APPROVED
        task.decided_at = now
        run.status = StageRunStatus.APPROVED
        if run.stage is StageKey.ACCEPTANCE:
            project.status = ProjectStatus.ACCEPTED
        else:
            project.current_stage = next_stage(run.stage)  # type: ignore[assignment]
    elif action == "return":
        if not comment:
            raise FlowError(400, "returning a run requires a comment")
        task.status = ApprovalStatus.RETURNED
        task.comment = comment
        task.decided_at = now
        run.status = StageRunStatus.RETURNED
    else:
        raise FlowError(400, f"unknown action '{action}'")

    await db.commit()
