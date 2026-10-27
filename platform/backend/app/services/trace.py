# -*- coding: utf-8 -*-
"""Trace-matrix service (architecture.md §7.3).

Two jobs:

- ``ingest_trace_tables`` — called from the approval path in
  ``flow.decide``: when a run is approved, harvest the stage's
  structured side-table (req/fp/tc/budget ``*-table.json``) from the
  run workspace into the DB, keyed to that run. Best effort by design:
  a missing or malformed file is a warning, never a failed approval.
- ``trace_overview`` — the matrix read: rows of the LATEST approved run
  per stage (history rounds stay in the tables, keyed by run id).
"""
import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    FpCategory,
    FunctionPoint,
    StageKey,
    StageRun,
    StageRunStatus,
    TraceBudgetRow,
    TraceRequirement,
    TraceTestCase,
)
from app.runtime_client import RuntimeCallError, get_runtime_client

logger = logging.getLogger(__name__)

# NESMA 估算功能点法（管理员确认口径，2026-10-27）：类别 → UFP 权重。
# L1 定价而不是智能体报价，提示词只负责分类。
NESMA_ESTIMATED_WEIGHTS: dict[str, int] = {
    "ILF": 7,
    "EIF": 5,
    "EI": 4,
    "EO": 5,
    "EQ": 4,
}

# Which stage drops which side-table in its workspace.
_TRACE_FILES: dict[StageKey, str] = {
    StageKey.REQUIREMENT: "req-table.json",
    StageKey.PROTOTYPE: "fp-table.json",
    StageKey.TESTCASES: "tc-table.json",
    StageKey.BUDGET: "budget-table.json",
}

_ROW_CAP = 500
_REF_CAP = 20


def _text(row: dict, key: str, *, maxlen: int = 200) -> str | None:
    v = row.get(key)
    if not isinstance(v, str) or not v.strip():
        return None
    return v.strip()[:maxlen]


def _refs(row: dict, key: str) -> list[str]:
    v = row.get(key)
    if not isinstance(v, list):
        return []
    out: list[str] = []
    for item in v[:_REF_CAP]:
        if isinstance(item, str) and item.strip():
            out.append(item.strip()[:32])
    return out


async def ingest_trace_tables(
    db: AsyncSession, run: StageRun, *, agent_id: str
) -> None:
    """Harvest this run's structured side-table, if the stage has one."""
    filename = _TRACE_FILES.get(run.stage)  # type: ignore[arg-type]
    if filename is None or run.session_id is None:
        return

    client = get_runtime_client()
    try:
        content = await client.read_workspace_file(
            agent_id, run.session_id, filename
        )
    except RuntimeCallError:
        return  # no side-table this round — the doc may predate §7.3
    try:
        rows = json.loads(content)
    except (json.JSONDecodeError, UnicodeDecodeError):
        logger.warning(
            "run #%s: %s is not valid JSON — trace table skipped",
            run.id,
            filename,
        )
        return
    if not isinstance(rows, list):
        logger.warning(
            "run #%s: %s is not a JSON array — trace table skipped",
            run.id,
            filename,
        )
        return
    rows = rows[:_ROW_CAP]

    objs: list[Any]
    if run.stage is StageKey.REQUIREMENT:
        await db.execute(
            delete(TraceRequirement).where(
                TraceRequirement.stage_run_id == run.id
            )
        )
        objs = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            req_id = _text(row, "id", maxlen=32)
            title = _text(row, "title")
            if not req_id or not title:
                continue
            objs.append(
                TraceRequirement(
                    project_id=run.project_id,
                    stage_run_id=run.id,
                    req_id=req_id,
                    title=title,
                    summary=(_text(row, "summary", maxlen=2000) or ""),
                )
            )
    elif run.stage is StageKey.PROTOTYPE:
        await db.execute(
            delete(FunctionPoint).where(FunctionPoint.stage_run_id == run.id)
        )
        objs = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            fp_id = _text(row, "id", maxlen=32)
            name = _text(row, "name")
            category = _text(row, "category", maxlen=8)
            if not fp_id or not name:
                continue
            if category not in NESMA_ESTIMATED_WEIGHTS:
                continue  # unknown category would break the enum anyway
            objs.append(
                FunctionPoint(
                    project_id=run.project_id,
                    stage_run_id=run.id,
                    fp_id=fp_id,
                    category=FpCategory(category),
                    complexity=_text(row, "complexity", maxlen=16),
                    name=name,
                    fr_refs=_refs(row, "fr_refs"),
                    weight=NESMA_ESTIMATED_WEIGHTS[category],
                )
            )
    elif run.stage is StageKey.TESTCASES:
        await db.execute(
            delete(TraceTestCase).where(TraceTestCase.stage_run_id == run.id)
        )
        objs = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            tc_id = _text(row, "id", maxlen=32)
            title = _text(row, "title")
            if not tc_id or not title:
                continue
            objs.append(
                TraceTestCase(
                    project_id=run.project_id,
                    stage_run_id=run.id,
                    tc_id=tc_id,
                    title=title,
                    fp_refs=_refs(row, "fp_refs"),
                )
            )
    else:  # StageKey.BUDGET
        await db.execute(
            delete(TraceBudgetRow).where(
                TraceBudgetRow.stage_run_id == run.id
            )
        )
        objs = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            fp_id = _text(row, "fp_id", maxlen=32)
            hours = row.get("hours")
            if not fp_id or not isinstance(hours, (int, float)) or hours < 0:
                continue
            objs.append(
                TraceBudgetRow(
                    project_id=run.project_id,
                    stage_run_id=run.id,
                    fp_id=fp_id,
                    hours=float(hours),
                )
            )
    db.add_all(objs)
    logger.info(
        "run #%s: ingested %d/%d rows from %s",
        run.id,
        len(objs),
        len(rows),
        filename,
    )


async def trace_overview(db: AsyncSession, project_id: int) -> dict[str, Any]:
    """Matrix read: the latest approved run's rows for each trace stage."""
    latest: dict[StageKey, int] = {}
    rows = await db.execute(
        select(StageRun.id, StageRun.stage)
        .where(
            StageRun.project_id == project_id,
            StageRun.status == StageRunStatus.APPROVED,
            StageRun.stage.in_(_TRACE_FILES.keys()),
        )
        .order_by(StageRun.id)
    )
    for run_id, stage in rows.all():
        latest[stage] = run_id  # ascending ids → the last write wins

    reqs: list[Any] = []
    fps: list[Any] = []
    tcs: list[Any] = []
    budget_hours: dict[str, float] = {}
    if StageKey.REQUIREMENT in latest:
        reqs = (
            await db.scalars(
                select(TraceRequirement)
                .where(
                    TraceRequirement.stage_run_id == latest[StageKey.REQUIREMENT]
                )
                .order_by(TraceRequirement.id)
            )
        ).all()
    if StageKey.PROTOTYPE in latest:
        fps = (
            await db.scalars(
                select(FunctionPoint)
                .where(
                    FunctionPoint.stage_run_id == latest[StageKey.PROTOTYPE]
                )
                .order_by(FunctionPoint.id)
            )
        ).all()
    if StageKey.TESTCASES in latest:
        tcs = (
            await db.scalars(
                select(TraceTestCase)
                .where(TraceTestCase.stage_run_id == latest[StageKey.TESTCASES])
                .order_by(TraceTestCase.id)
            )
        ).all()
    if StageKey.BUDGET in latest:
        for row in await db.scalars(
            select(TraceBudgetRow).where(
                TraceBudgetRow.stage_run_id == latest[StageKey.BUDGET]
            )
        ):
            budget_hours[row.fp_id] = row.hours

    return {
        "requirements": reqs,
        "function_points": fps,
        "test_cases": tcs,
        "budget_hours": budget_hours,
        "produced_at": {
            stage.value: run_id for stage, run_id in latest.items()
        },
    }
