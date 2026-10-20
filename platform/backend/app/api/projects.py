# -*- coding: utf-8 -*-
"""Project, stage-run and approval routes.

Thin transport layer: validation here, state-machine rules in
app/services/flow.py (single implementation, §5).
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user
from app.db import get_db
from app.models import (
    ApprovalStatus,
    ApprovalTask,
    Project,
    ProjectMember,
    ProjectRole,
    ProjectStatus,
    StageKey,
    StageRun,
    StageRunStatus,
    User,
)
from app.services import flow
from app.services.flow import FlowError

router = APIRouter(tags=["projects"])


# ---------- schemas ----------

class ProjectCreateIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)


class ProjectOut(BaseModel):
    id: int
    name: str
    status: ProjectStatus
    current_stage: StageKey
    owner_user_id: int
    created_at: str

    model_config = {"from_attributes": True}

    @classmethod
    def from_project(cls, project: Project) -> "ProjectOut":
        return cls(
            id=project.id,
            name=project.name,
            status=project.status,
            current_stage=project.current_stage,
            owner_user_id=project.owner_user_id,
            created_at=project.created_at.isoformat(),
        )


class StageRunOut(BaseModel):
    id: int
    project_id: int
    stage: StageKey
    status: StageRunStatus
    round: int
    session_id: str | None
    created_at: str

    model_config = {"from_attributes": True}

    @classmethod
    def from_run(cls, run: StageRun) -> "StageRunOut":
        return cls(
            id=run.id,
            project_id=run.project_id,
            stage=run.stage,
            status=run.status,
            round=run.round,
            session_id=run.session_id,
            created_at=run.created_at.isoformat(),
        )


class SubmitIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=200_000)


class ArtifactOut(BaseModel):
    id: int
    version_no: int
    title: str
    format: str
    storage_path: str


class DecideIn(BaseModel):
    action: str = Field(pattern=r"^(approve|return)$")
    comment: str | None = Field(default=None, max_length=4000)


class ApprovalOut(BaseModel):
    id: int
    stage_run_id: int
    project_id: int
    stage: StageKey
    run_status: StageRunStatus
    status: ApprovalStatus
    comment: str | None


# ---------- helpers ----------

def _flow_http(exc: FlowError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=exc.detail)


async def _get_project_or_404(
    db: AsyncSession, project_id: int, user: User
) -> Project:
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    try:
        await flow.require_member(db, project, user)
    except FlowError as exc:
        raise _flow_http(exc) from exc
    return project


# ---------- projects ----------

@router.post("/projects", response_model=ProjectOut, status_code=201)
async def create_project(
    payload: ProjectCreateIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProjectOut:
    project = Project(
        name=payload.name,
        owner_user_id=user.id,
    )
    db.add(project)
    await db.flush()
    db.add(
        ProjectMember(
            project_id=project.id,
            user_id=user.id,
            role=ProjectRole.INITIATOR,
        )
    )
    await db.commit()
    await db.refresh(project)
    return ProjectOut.from_project(project)


@router.get("/projects", response_model=list[ProjectOut])
async def list_projects(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ProjectOut]:
    member_project_ids = select(ProjectMember.project_id).where(
        ProjectMember.user_id == user.id
    )
    projects = (
        await db.scalars(
            select(Project)
            .where(
                or_(
                    Project.owner_user_id == user.id,
                    Project.id.in_(member_project_ids),
                )
            )
            .order_by(Project.id.desc())
        )
    ).all()
    return [ProjectOut.from_project(p) for p in projects]


@router.get("/projects/{project_id}", response_model=ProjectOut)
async def get_project(
    project_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProjectOut:
    project = await _get_project_or_404(db, project_id, user)
    return ProjectOut.from_project(project)


# ---------- stage runs ----------

@router.get(
    "/projects/{project_id}/stage-runs", response_model=list[StageRunOut]
)
async def list_stage_runs(
    project_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[StageRunOut]:
    await _get_project_or_404(db, project_id, user)
    runs = (
        await db.scalars(
            select(StageRun)
            .where(StageRun.project_id == project_id)
            .order_by(StageRun.id)
        )
    ).all()
    return [StageRunOut.from_run(r) for r in runs]


@router.post(
    "/projects/{project_id}/stages/{stage}/start",
    response_model=StageRunOut,
    status_code=201,
)
async def start_stage(
    project_id: int,
    stage: StageKey,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StageRunOut:
    project = await _get_project_or_404(db, project_id, user)
    try:
        run = await flow.start_stage(db, project, stage, user)
    except FlowError as exc:
        raise _flow_http(exc) from exc
    return StageRunOut.from_run(run)


@router.post("/stage-runs/{run_id}/submit", response_model=ArtifactOut)
async def submit_run(
    run_id: int,
    payload: SubmitIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ArtifactOut:
    run = await db.get(StageRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="stage run not found")
    project = await _get_project_or_404(db, run.project_id, user)
    try:
        artifact = await flow.submit_run(
            db, run, project, payload.title, payload.content
        )
    except FlowError as exc:
        raise _flow_http(exc) from exc
    return ArtifactOut(
        id=artifact.id,
        version_no=artifact.version_no,
        title=artifact.title,
        format=artifact.format.value,
        storage_path=artifact.storage_path,
    )


# ---------- approvals ----------

@router.get("/approvals/pending", response_model=list[ApprovalOut])
async def pending_approvals(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ApprovalOut]:
    tasks = (
        await db.scalars(
            select(ApprovalTask)
            .options(selectinload(ApprovalTask.stage_run))
            .where(
                ApprovalTask.approver_user_id == user.id,
                ApprovalTask.status == ApprovalStatus.PENDING,
            )
            .order_by(ApprovalTask.id)
        )
    ).all()
    return [
        ApprovalOut(
            id=t.id,
            stage_run_id=t.stage_run_id,
            project_id=t.stage_run.project_id,
            stage=t.stage_run.stage,
            run_status=t.stage_run.status,
            status=t.status,
            comment=t.comment,
        )
        for t in tasks
    ]


@router.post("/approvals/{task_id}/decide")
async def decide_approval(
    task_id: int,
    payload: DecideIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    task = await db.get(ApprovalTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="approval task not found")
    if task.approver_user_id != user.id:
        raise HTTPException(
            status_code=403, detail="only the assigned approver can decide"
        )
    run = await db.get(StageRun, task.stage_run_id)
    project = await db.get(Project, run.project_id)
    try:
        await flow.decide(db, task, run, project, payload.action, payload.comment)
    except FlowError as exc:
        raise _flow_http(exc) from exc
    return {
        "task_id": task.id,
        "action": payload.action,
        "run_status": run.status.value,
        "project_stage": project.current_stage.value,
        "project_status": project.status.value,
    }
