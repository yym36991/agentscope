# -*- coding: utf-8 -*-
"""Stage flow state machine (architecture.md §5).

All stage/project transitions live here so the API layer stays thin and
the rules have exactly one implementation. Illegal transitions raise
:class:`FlowError`, which the API layer maps to HTTP 409/400.
"""
from datetime import datetime, timezone
from pathlib import Path
import logging

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
from app.runtime_client import RuntimeCallError, RuntimeClient, get_runtime_client

logger = logging.getLogger(__name__)

STAGE_ORDER: list[StageKey] = [
    StageKey.REQUIREMENT,
    StageKey.PROTOTYPE,
    StageKey.BUDGET,
    StageKey.TESTCASES,
    StageKey.TESTING,
    StageKey.ACCEPTANCE,
]

# Runtime agent name per stage. The seed script (scripts/seed.py)
# creates these under sys:runtime; M1 seeds only the first.
STAGE_AGENT_NAMES: dict[StageKey, str] = {
    StageKey.REQUIREMENT: "需求生成",
    StageKey.PROTOTYPE: "原型设计",
    StageKey.BUDGET: "工时预算罗盘",
    StageKey.TESTCASES: "测试用例",
    StageKey.TESTING: "测试",
    StageKey.ACCEPTANCE: "验收审计",
}

# Stage skill bundles (subdir of settings.runtime_skill_dir, each holding
# one skill dir per method). Installed into the agent's workspace
# partition when the stage's first session opens — the partition is
# shared by all of the agent's sessions and hash-deduped by the runtime,
# so re-opening sessions stays a no-op. Stages absent here are bare.
STAGE_SKILL_DIRS: dict[StageKey, str] = {
    StageKey.TESTCASES: "testcases",
}

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


async def resolve_stage_agent(stage: StageKey) -> str:
    """Agent id for *stage*; FlowError if the seed script hasn't run."""
    agent_id = await get_runtime_client().find_agent_by_name(
        STAGE_AGENT_NAMES[stage]
    )
    if agent_id is None:
        raise FlowError(
            503,
            f"stage agent '{STAGE_AGENT_NAMES[stage]}' is not seeded on "
            f"the runtime — run scripts/seed.py",
        )
    return agent_id


async def ensure_stage_session(
    db: AsyncSession, run: StageRun, project: Project
) -> tuple[str, str]:
    """(session_id, agent_id), creating the runtime session if needed.

    Lazy creation keeps runs opened while the runtime was down (or
    before the model credential existed) usable later — the chat relay
    calls this too, not just start_stage.
    """
    agent_id = await resolve_stage_agent(run.stage)
    if run.session_id is not None:
        return run.session_id, agent_id

    client = get_runtime_client()
    session_id = await client.create_session(
        agent_id,
        name=f"project{project.id}-{run.stage.value}-run{run.id}",
        chat_model_config=await client.default_chat_model_config(),
    )
    await _install_stage_skills(client, agent_id, session_id, run.stage)
    run.session_id = session_id
    await db.commit()
    return session_id, agent_id


async def _install_stage_skills(
    client: RuntimeClient, agent_id: str, session_id: str, stage: StageKey
) -> None:
    """Install the stage's skill bundle into the agent's workspace.

    Best-effort by design: a missing dir or a failed install must never
    block the conversation — the stage works bare, just less guided.
    The runtime hash-dedups SKILL.md, so a re-created session of the
    same agent is a cheap no-op.
    """
    bundle = STAGE_SKILL_DIRS.get(stage)
    if bundle is None:
        return
    root = Path(get_settings().runtime_skill_dir) / bundle
    if not root.is_dir():
        logger.warning("stage skill bundle missing: %s", root)
        return
    for skill_dir in sorted(p for p in root.iterdir() if (p / "SKILL.md").is_file()):
        try:
            await client.add_workspace_skill(agent_id, session_id, str(skill_dir))
        except RuntimeCallError as exc:
            logger.warning(
                "skill %s not installed (%s) — continuing without it",
                skill_dir.name,
                exc.detail,
            )


_KICKOFF_ARTIFACT_CAP = 30_000  # chars per injected upstream artifact


async def _approved_artifacts_by_stage(
    db: AsyncSession, project: Project
) -> dict[StageKey, ArtifactVersion]:
    """Newest approved artifact per stage, for the kickoff injection."""
    rows = (
        await db.execute(
            select(ArtifactVersion, StageRun.stage)
            .join(StageRun, ArtifactVersion.stage_run_id == StageRun.id)
            .where(
                StageRun.project_id == project.id,
                StageRun.status == StageRunStatus.APPROVED,
            )
            .order_by(ArtifactVersion.id.desc())
        )
    ).all()
    latest: dict[StageKey, ArtifactVersion] = {}
    for artifact, stage in rows:  # newest first — first hit per stage wins
        latest.setdefault(stage, artifact)
    return latest


async def build_kickoff(
    db: AsyncSession, run: StageRun, project: Project
) -> str:
    """The stage-opening context that rides on a run's FIRST message.

    Opening a stage no longer fires the agent — the user gets a window
    to add an opening note and materials first (e.g. the 功能点明细
    xlsx their own external model produced) — so the context the agent
    needs travels with that first message instead: every previously
    approved artifact in stage order, plus the approver's comment on a
    rework round.
    """
    kickoff = (
        f"【阶段启动】项目《{project.name}》的「"
        f"{STAGE_AGENT_NAMES[run.stage]}」阶段已开始（第 {run.round} 轮）。"
        f"请先向用户确认你需要了解的信息，再开始本阶段工作。"
    )

    approved = await _approved_artifacts_by_stage(db, project)
    sections: list[str] = []
    for stage in STAGE_ORDER[: STAGE_ORDER.index(run.stage)]:
        artifact = approved.get(stage)
        if artifact is None:
            continue
        try:
            content = (
                Path(get_settings().artifact_dir) / artifact.storage_path
            ).read_text(encoding="utf-8")
        except OSError:
            # archived file gone — say so instead of failing the chat
            sections.append(
                f"=== {STAGE_AGENT_NAMES[stage]} · 《{artifact.title}》 ===\n"
                f"（产物归档文件读取失败，请向用户索取该阶段产物）"
            )
            continue
        content = content.lstrip("\ufeff")
        if len(content) > _KICKOFF_ARTIFACT_CAP:
            content = content[:_KICKOFF_ARTIFACT_CAP] + "\n…（内容过长，已截断）"
        sections.append(
            f"=== {STAGE_AGENT_NAMES[stage]} · 《{artifact.title}》 ===\n{content}"
        )
    if sections:
        kickoff += (
            "\n\n上游各阶段已批准的产物如下，请以它们为本阶段的输入"
            "（如需补充信息再向用户澄清）：\n\n" + "\n\n".join(sections)
        )

    # A rework round opens a FRESH session — without the approver's
    # comment the agent would not know why the previous round was
    # rejected (its draft still lies in the shared workspace for it
    # to re-read).
    return_comment = await _latest_return_comment(db, project, run.stage)
    if return_comment:
        kickoff += (
            f"\n\n【上一轮退回意见】请针对以下意见重新产出：\n\n{return_comment}"
        )
    return kickoff


async def _latest_return_comment(
    db: AsyncSession, project: Project, stage: StageKey
) -> str | None:
    """Comment of the most recent RETURNED run of *stage*."""
    task = await db.scalar(
        select(ApprovalTask)
        .join(StageRun, ApprovalTask.stage_run_id == StageRun.id)
        .where(
            StageRun.project_id == project.id,
            StageRun.stage == stage,
            StageRun.status == StageRunStatus.RETURNED,
        )
        .order_by(ApprovalTask.id.desc())
        .limit(1)
    )
    return task.comment if task else None


async def start_stage(
    db: AsyncSession, project: Project, stage: StageKey, user: User
) -> StageRun:
    """Open a new run of *stage* (round + 1 per previous rework).

    Deliberately pure DB work: the runtime session and the kickoff
    context are deferred to the run's first chat relay (see
    :func:`build_kickoff`), so between 开启 and 开始 the user has a
    window to add an opening note and materials before the agent
    starts working — and an unreachable runtime can never leave a
    half-started run behind either.
    """
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
    fmt: ArtifactFormat = ArtifactFormat.MD,
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
        f"{project.id}/{run.stage.value}/"
        f"run{run.id}-v{version_no}.{fmt.value}"
    )
    abs_path = Path(get_settings().artifact_dir) / rel_path
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_text(content, encoding="utf-8")

    artifact = ArtifactVersion(
        stage_run_id=run.id,
        version_no=version_no,
        title=title,
        format=fmt,
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
