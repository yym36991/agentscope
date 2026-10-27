# -*- coding: utf-8 -*-
"""Trace-matrix API: the 需求 → 功能点 → 测试用例 → 报价 matrix of one
project, assembled from the latest approved runs' side-tables (§7.3)."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db import get_db
from app.models import Project, User
from app.services import flow, trace
from app.services.flow import FlowError

router = APIRouter(tags=["trace"])


class ReqRowOut(BaseModel):
    req_id: str
    title: str
    summary: str


class FpRowOut(BaseModel):
    fp_id: str
    name: str
    category: str
    complexity: str | None
    fr_refs: list[str]
    weight: int
    hours: float | None


class TcRowOut(BaseModel):
    tc_id: str
    title: str
    fp_refs: list[str]


class TraceOut(BaseModel):
    requirements: list[ReqRowOut]
    function_points: list[FpRowOut]
    test_cases: list[TcRowOut]
    # NESMA 估算功能点法：Σ 类别权重
    ufp: int
    hours_total: float | None
    # stage → run id that produced each slice (transparency for the UI)
    produced_at: dict[str, int]


@router.get("/projects/{project_id}/trace", response_model=TraceOut)
async def get_project_trace(
    project_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TraceOut:
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    try:
        await flow.require_member(db, project, user)
    except FlowError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail) from exc

    data = await trace.trace_overview(db, project_id)
    budget_hours: dict[str, float] = data["budget_hours"]
    fps = [
        FpRowOut(
            fp_id=fp.fp_id,
            name=fp.name,
            category=fp.category.value,
            complexity=fp.complexity,
            fr_refs=list(fp.fr_refs or []),
            weight=fp.weight,
            hours=budget_hours.get(fp.fp_id),
        )
        for fp in data["function_points"]
    ]
    return TraceOut(
        requirements=[
            ReqRowOut(req_id=r.req_id, title=r.title, summary=r.summary)
            for r in data["requirements"]
        ],
        function_points=fps,
        test_cases=[
            TcRowOut(
                tc_id=t.tc_id,
                title=t.title,
                fp_refs=list(t.fp_refs or []),
            )
            for t in data["test_cases"]
        ],
        ufp=sum(fp.weight for fp in data["function_points"]),
        hours_total=(
            sum(fp.hours for fp in fps if fp.hours is not None) or None
        ),
        produced_at=data["produced_at"],
    )
