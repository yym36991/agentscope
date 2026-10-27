# -*- coding: utf-8 -*-
"""Trace matrices (architecture.md §7.3): the structured side of the
stage deliverables.

Stage agents keep writing human deliverables (PRD, 功能点明细 CSV,
估算表…), and additionally drop a machine-readable side-table in the
workspace (req/fp/tc/budget ``*-table.json``). L1 harvests those files
when the run is APPROVED — so only approved data ever lands here, keyed
to the producing run; the matrix reads the latest approved run per
stage, history rounds stay queryable.
"""
import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class FpCategory(str, enum.Enum):
    """NESMA five function-point categories."""

    ILF = "ILF"
    EIF = "EIF"
    EI = "EI"
    EO = "EO"
    EQ = "EQ"


class TraceRequirement(Base):
    """One numbered requirement row (FR-xx) from the requirement stage."""

    __tablename__ = "trace_requirements"
    __table_args__ = (
        UniqueConstraint(
            "stage_run_id", "req_id", name="uq_trace_requirements_run_req"
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id"), index=True
    )
    stage_run_id: Mapped[int] = mapped_column(
        ForeignKey("stage_runs.id"), index=True
    )
    req_id: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )


class FunctionPoint(Base):
    """One function point (FP-xx) from the prototype stage.

    ``weight`` is fixed by L1 at ingestion per the NESMA 估算功能点法
    category weights (ILF=7/EIF=5/EI=4/EO=5/EQ=4) — agents classify,
    the platform prices, so a prompt can't inflate the count.
    """

    __tablename__ = "function_points"
    __table_args__ = (
        UniqueConstraint(
            "stage_run_id", "fp_id", name="uq_function_points_run_fp"
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id"), index=True
    )
    stage_run_id: Mapped[int] = mapped_column(
        ForeignKey("stage_runs.id"), index=True
    )
    fp_id: Mapped[str] = mapped_column(String(32))
    category: Mapped[FpCategory] = mapped_column(
        Enum(FpCategory, name="fp_category"), nullable=False
    )
    # 低/中/高 — recorded by the agent, only used by the detailed method.
    complexity: Mapped[str | None] = mapped_column(String(16), nullable=True)
    name: Mapped[str] = mapped_column(String(200))
    fr_refs: Mapped[list] = mapped_column(JSON, default=list)
    weight: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )


class TraceTestCase(Base):
    """One test case (TC-xx) from the testcases stage."""

    __tablename__ = "trace_test_cases"
    __table_args__ = (
        UniqueConstraint(
            "stage_run_id", "tc_id", name="uq_trace_test_cases_run_tc"
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id"), index=True
    )
    stage_run_id: Mapped[int] = mapped_column(
        ForeignKey("stage_runs.id"), index=True
    )
    tc_id: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(200))
    fp_refs: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )


class TraceBudgetRow(Base):
    """One per-function-point hours row from the budget stage."""

    __tablename__ = "trace_budget_rows"
    __table_args__ = (
        UniqueConstraint(
            "stage_run_id", "fp_id", name="uq_trace_budget_rows_run_fp"
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id"), index=True
    )
    stage_run_id: Mapped[int] = mapped_column(
        ForeignKey("stage_runs.id"), index=True
    )
    fp_id: Mapped[str] = mapped_column(String(32))
    hours: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
