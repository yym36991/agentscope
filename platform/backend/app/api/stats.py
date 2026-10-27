# -*- coding: utf-8 -*-
"""Management view: statistics dashboard + feedback ledger.

``/stats`` — platform aggregates over the caller's visible projects
(admin sees everything, members see own + joined): status distribution,
per-stage duration/rounds/return-rate, approval pass rate, and
price-baseline coverage.

``/feedback`` — every DECIDED approval comment (both 通过 and 退回
opinions) across projects: the audit ledger 造价交付场景吃的就是这个.
"""
from datetime import datetime
from statistics import fmean

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db import get_db
from app.services.flow import STAGE_ORDER
from app.models import (
    ApprovalStatus,
    ApprovalTask,
    PlatformRole,
    PriceItem,
    Project,
    ProjectMember,
    StageRun,
    StageRunStatus,
    User,
)

router = APIRouter(tags=["stats"])


def _visible_project_ids(user: User):
    """Subquery: projects the user may see (owner or member)."""
    return select(Project.id).where(
        or_(
            Project.owner_user_id == user.id,
            Project.id.in_(
                select(ProjectMember.project_id).where(
                    ProjectMember.user_id == user.id
                )
            ),
        )
    )


class StageStatOut(BaseModel):
    stage: str
    runs: int
    approved: int
    returned: int
    # hours between run creation and the approval decision, approved runs
    avg_hours: float | None
    # highest round reached per project for this stage
    avg_rounds: float | None
    # returned runs / all runs
    return_rate: float


class StatsOut(BaseModel):
    projects_total: int
    projects_by_status: dict[str, int]
    stages: list[StageStatOut]
    approvals: dict[str, int]
    price: dict[str, object]


@router.get("/stats", response_model=StatsOut)
async def platform_stats(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StatsOut:
    # ---- project scope ----
    stmt = select(Project)
    if user.role != PlatformRole.ADMIN:
        stmt = stmt.where(Project.id.in_(_visible_project_ids(user)))
    projects = (await db.scalars(stmt.order_by(Project.id))).all()
    project_ids = [p.id for p in projects]
    by_status: dict[str, int] = {}
    for p in projects:
        by_status[p.status.value] = by_status.get(p.status.value, 0) + 1

    # ---- stage runs + decision times ----
    runs: list[StageRun] = []
    if project_ids:
        runs = (
            await db.scalars(
                select(StageRun)
                .where(StageRun.project_id.in_(project_ids))
                .order_by(StageRun.id)
            )
        ).all()
    decided: dict[int, datetime] = {}
    if runs:
        rows = await db.execute(
            select(
                ApprovalTask.stage_run_id,
                func.max(ApprovalTask.decided_at),
            )
            .where(
                ApprovalTask.stage_run_id.in_([r.id for r in runs]),
                ApprovalTask.decided_at.is_not(None),
            )
            .group_by(ApprovalTask.stage_run_id)
        )
        decided = dict(rows.all())

    stage_stats: list[StageStatOut] = []
    for stage in STAGE_ORDER:  # real stages only — NONE is "not started"
        s_runs = [r for r in runs if r.stage is stage]
        approved = [
            r for r in s_runs if r.status is StageRunStatus.APPROVED
        ]
        returned = [
            r for r in s_runs if r.status is StageRunStatus.RETURNED
        ]
        durations = [
            (decided[r.id] - r.created_at).total_seconds() / 3600.0
            for r in approved
            if r.id in decided
        ]
        rounds_by_project: dict[int, int] = {}
        for r in s_runs:
            rounds_by_project[r.project_id] = max(
                rounds_by_project.get(r.project_id, 0), r.round
            )
        stage_stats.append(
            StageStatOut(
                stage=stage.value,
                runs=len(s_runs),
                approved=len(approved),
                returned=len(returned),
                avg_hours=round(fmean(durations), 1) if durations else None,
                avg_rounds=(
                    round(fmean(rounds_by_project.values()), 2)
                    if rounds_by_project
                    else None
                ),
                return_rate=(
                    round(len(returned) / len(s_runs), 3) if s_runs else 0.0
                ),
            )
        )

    # ---- approval outcomes (stage tasks join via run, consolidation
    # tasks carry project_id directly) ----
    approval_counts = {"approved": 0, "returned": 0, "pending": 0}
    if project_ids:
        rows = await db.execute(
            select(ApprovalTask.status, func.count())
            .join(StageRun, ApprovalTask.stage_run_id == StageRun.id, isouter=True)
            .where(
                or_(
                    ApprovalTask.project_id.in_(project_ids),
                    StageRun.project_id.in_(project_ids),
                )
            )
            .group_by(ApprovalTask.status)
        )
        for status_, n in rows.all():
            approval_counts[status_.value] = n

    # ---- price baseline coverage (platform-wide) ----
    price_total = await db.scalar(
        select(func.count()).select_from(PriceItem)
    )
    price_regions = await db.scalar(
        select(func.count()).select_from(
            select(PriceItem.region).distinct().subquery()
        )
    )
    by_type_rows = await db.execute(
        select(PriceItem.item_type, func.count()).group_by(
            PriceItem.item_type
        )
    )
    by_type = {t: n for t, n in by_type_rows.all()}

    return StatsOut(
        projects_total=len(projects),
        projects_by_status=by_status,
        stages=stage_stats,
        approvals=approval_counts,
        price={
            "items": price_total or 0,
            "regions": price_regions or 0,
            "by_type": by_type,
        },
    )


class FeedbackOut(BaseModel):
    id: int
    project_id: int
    project_name: str | None
    kind: str  # stage | consolidation
    stage: str | None
    run_round: int | None
    action: str  # approved | returned
    comment: str
    approver: str
    decided_at: str


@router.get("/feedback", response_model=list[FeedbackOut])
async def list_feedback(
    project_id: int | None = None,
    action: str | None = None,
    q: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[FeedbackOut]:
    """Decided opinions across projects — approve notes and return
    comments together, newest first. Filters: project, action, keyword."""
    if action is not None and action not in ("approved", "returned"):
        raise HTTPException(
            status_code=400, detail="action must be approved or returned"
        )
    stmt = (
        select(
            ApprovalTask,
            StageRun.stage,
            StageRun.round,
            Project.id,
            Project.name,
            User.username,
        )
        .join(StageRun, ApprovalTask.stage_run_id == StageRun.id, isouter=True)
        .join(
            Project,
            or_(
                StageRun.project_id == Project.id,
                ApprovalTask.project_id == Project.id,
            ),
            isouter=True,
        )
        .join(User, ApprovalTask.approver_user_id == User.id)
        .where(
            ApprovalTask.comment.is_not(None),
            ApprovalTask.decided_at.is_not(None),
        )
    )
    if user.role != PlatformRole.ADMIN:
        stmt = stmt.where(Project.id.in_(_visible_project_ids(user)))
    if project_id is not None:
        stmt = stmt.where(
            or_(
                StageRun.project_id == project_id,
                ApprovalTask.project_id == project_id,
            )
        )
    if action is not None:
        stmt = stmt.where(ApprovalTask.status == ApprovalStatus(action))
    if q:
        stmt = stmt.where(ApprovalTask.comment.ilike(f"%{q}%"))
    stmt = stmt.order_by(ApprovalTask.decided_at.desc()).limit(200)

    rows = await db.execute(stmt)
    out: list[FeedbackOut] = []
    for task, stage, round_, pid, pname, approver in rows.all():
        out.append(
            FeedbackOut(
                id=task.id,
                project_id=task.project_id or pid or 0,
                project_name=pname,
                kind=task.kind.value,
                stage=stage.value if stage is not None else None,
                run_round=round_,
                action=task.status.value,
                comment=task.comment or "",
                approver=approver,
                decided_at=task.decided_at.isoformat(),  # type: ignore[union-attr]
            )
        )
    return out
