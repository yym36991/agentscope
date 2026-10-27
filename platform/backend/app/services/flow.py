# -*- coding: utf-8 -*-
"""Stage flow state machine (architecture.md §5).

All stage/project transitions live here so the API layer stays thin and
the rules have exactly one implementation. Illegal transitions raise
:class:`FlowError`, which the API layer maps to HTTP 409/400.
"""
from pathlib import Path
import asyncio
import logging

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.db import SessionLocal
from app.models import (
    ApprovalKind,
    ApprovalStatus,
    ApprovalTask,
    ArtifactFormat,
    ArtifactVersion,
    ConsolidationDraft,
    Kb,
    KbGrant,
    KbType,
    PlatformRole,
    Project,
    ProjectArchive,
    ProjectKbLink,
    ProjectMember,
    ProjectRole,
    ProjectStatus,
    StageKey,
    StageRun,
    StageRunStatus,
    User,
)
from app.runtime_client import RuntimeCallError, RuntimeClient, get_runtime_client
from app.services.trace import ingest_trace_tables

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
# one skill dir per method). Installed into the run's workspace when its
# session opens — with §8.5 per-project workspaces that means once per
# project per stage, and the runtime hash-dedups SKILL.md so repeated
# installs stay a no-op. Stages absent here are bare.
STAGE_SKILL_DIRS: dict[StageKey, str] = {
    StageKey.TESTCASES: "testcases",
}

# M4 (§6.4): the consolidation agent that distills a finished project
# into reviewable knowledge. Not a stage — it runs once, at acceptance.
CONSOLIDATION_AGENT_NAME = "知识沉淀"

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


def stage_workspace_id(run: StageRun, project: Project) -> str:
    """Explicit runtime workspace binding for a run (§8.5).

    Doc-writing stages share the PROJECT workspace so rework rounds
    re-read earlier drafts and stage hand-offs see the same files; the
    testing stage gets a per-run scratch workspace — its boundary is
    the disposable state (installed deps, venv, test scripts), so a
    fresh run starts from a clean baseline while sessions inside the
    run keep a continuous environment.
    """
    if run.stage is StageKey.TESTING:
        return f"test-run-{run.id}"
    return f"proj-{project.id}"


async def stage_model_config(stage: StageKey) -> dict | None:
    """Resolve the §8.6 chain for *stage*: blueprint override, else
    the platform default. None = no credential configured yet (the
    chat relay self-heals via PATCH once one shows up)."""
    overrides = get_settings().runtime_stage_models
    model = overrides.get(stage.value) or get_settings().runtime_model
    return await get_runtime_client().build_chat_model_config(model)


async def stage_kb_ids(
    db: AsyncSession, project: Project, stage: StageKey, user: User
) -> list[str]:
    """Runtime KB ids mounted for *stage* seen by *user* (§7.2).

    阶段可用 KB = project_kb_links(本阶段 ∪ 全阶段绑定) ∩ 用户可见集合
    — filter first, retrieve second: a KB the sender cannot see never
    enters the RAG candidate set. Admins see every linked KB.
    """
    links = (
        await db.execute(
            select(ProjectKbLink, Kb)
            .join(Kb, ProjectKbLink.kb_id == Kb.id)
            .where(
                ProjectKbLink.project_id == project.id,
                or_(
                    ProjectKbLink.stage == stage,
                    ProjectKbLink.stage.is_(None),
                ),
            )
        )
    ).all()
    if not links:
        return []
    if user.role == PlatformRole.ADMIN:
        return [kb.agentscope_kb_id for _, kb in links if kb.agentscope_kb_id]
    group_ids = {g.id for g in user.groups}
    if not group_ids:
        return []
    granted = set(
        await db.scalars(
            select(KbGrant.kb_id).where(
                KbGrant.kb_id.in_({kb.id for _, kb in links}),
                KbGrant.group_id.in_(group_ids),
            )
        )
    )
    return [
        kb.agentscope_kb_id
        for _, kb in links
        if kb.id in granted and kb.agentscope_kb_id
    ]


async def ensure_stage_session(
    db: AsyncSession, run: StageRun, project: Project, user: User
) -> tuple[str, str]:
    """(session_id, agent_id), creating the runtime session if needed.

    Lazy creation keeps runs opened while the runtime was down (or
    before the model credential existed) usable later — the chat relay
    calls this too, not just start_stage. The session binds the run's
    explicit workspace (§8.5), the stage's resolved model (§8.6) and
    the sender-visible stage KBs (§7.2); the runtime creates a NEW
    session per call (verified against the PG backend), so rework
    rounds never land in a previous session.
    """
    agent_id = await resolve_stage_agent(run.stage)
    if run.session_id is not None:
        return run.session_id, agent_id

    client = get_runtime_client()
    workspace_id = stage_workspace_id(run, project)
    session_id = await client.create_session(
        agent_id,
        name=f"project{project.id}-{run.stage.value}-run{run.id}",
        chat_model_config=await stage_model_config(run.stage),
        workspace_id=workspace_id,
        kb_ids=await stage_kb_ids(db, project, run.stage, user),
    )
    await _install_stage_skills(client, agent_id, session_id, run.stage)
    run.session_id = session_id
    run.workspace_id = workspace_id
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

    # §6.3 kickoff layer 1: the compact archive digest (M4). Only when
    # at least one stage has been approved ("\n- " marks a stage line).
    archive = await db.scalar(
        select(ProjectArchive).where(ProjectArchive.project_id == project.id)
    )
    if archive is not None and "\n- " in archive.summary:
        kickoff += f"\n\n【项目档案摘要】\n{archive.summary}"

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


# ---------- project archive (§6.2 ②a, M4) ----------


def _digest_line(content: str, cap: int = 200) -> str:
    """One-line deterministic digest of an artifact — no LLM.

    The archive is the unbreakable fallback layer of the kickoff: a
    missing or slow model may cost the pretty summary, never the
    context itself. First 200 chars of whitespace-collapsed text is
    crude but honest about being a digest, not a distillation.
    """
    text = " ".join(content.split())
    return text[:cap] + ("…" if len(text) > cap else "")


async def update_project_archive(db: AsyncSession, project: Project) -> None:
    """Regenerate the project archive from the approved artifacts.

    Called at every stage approval; the summary covers each approved
    stage in flow order, so later kickoffs always see the full chain
    of decisions so far. Caller owns the commit.
    """
    approved = await _approved_artifacts_by_stage(db, project)
    lines = [f"项目《{project.name}》各阶段已批准产物的关键结论："]
    for stage in STAGE_ORDER:
        artifact = approved.get(stage)
        if artifact is None:
            continue
        try:
            content = (
                Path(get_settings().artifact_dir) / artifact.storage_path
            ).read_text(encoding="utf-8")
        except OSError:
            content = ""
        lines.append(
            f"- {STAGE_AGENT_NAMES[stage]}（{artifact.title}）：{_digest_line(content)}"
        )
    summary = "\n".join(lines)
    archive = await db.scalar(
        select(ProjectArchive).where(ProjectArchive.project_id == project.id)
    )
    if archive is None:
        db.add(ProjectArchive(project_id=project.id, summary=summary))
    else:
        archive.summary = summary


# ---------- consolidation flow (§6.4, M4) ----------

_CONSOLIDATION_PROMPT = (
    "【项目沉淀任务】该项目已完成验收审计。以下是各阶段已批准产物，"
    "请提炼一份《知识沉淀文档》，供本部门后续同类项目参考：\n"
    "1. 项目案例概要：业务目标、功能规模、造价区间与口径；\n"
    "2. 功能点与造价系数观察：估算口径、费率与调整因子的取值经验；\n"
    "3. 常见问题与经验教训：各阶段协作或返工的典型原因；\n"
    "4. 对同类项目的建议。\n"
    "要求：脱敏（不得出现真实客户名称与联系方式）；全文控制在 "
    "1500 字以内；Markdown；一次性交付，不等待用户确认。"
)

_CONSOLIDATION_TIMEOUT = 10 * 60  # one LLM reply, generous
_BG_TASKS: set["asyncio.Task[None]"] = set()


def _spawn_consolidation(project_id: int) -> None:
    """Fire-and-forget the consolidation drafting; refs held so the
    task cannot be garbage-collected mid-flight."""
    task = asyncio.create_task(_run_consolidation(project_id))
    _BG_TASKS.add(task)
    task.add_done_callback(_BG_TASKS.discard)


def _last_assistant_text(messages: list[dict]) -> str | None:
    """Newest non-empty assistant text across the message list."""
    for msg in reversed(messages):
        if msg.get("role") != "assistant":
            continue
        raw = msg.get("content")
        if isinstance(raw, str):
            text = raw.strip()
        else:
            text = "\n".join(
                b.get("text", "")
                for b in raw or []
                if isinstance(b, dict) and b.get("type") == "text"
            ).strip()
        if text:
            return text
    return None


async def _run_consolidation(project_id: int) -> None:
    """Draft the consolidation document and open its review task.

    Best-effort by design: a missing agent, an unreachable runtime or
    a failed LLM reply all fall back to the deterministic project
    archive as the draft, so the review task (and the audit trail)
    always materializes. Runs detached from the approval request.
    """
    try:
        async with SessionLocal() as db:
            project = await db.get(Project, project_id)
            if project is None:
                return
            client = get_runtime_client()
            draft_content: str | None = None
            agent_id = await client.find_agent_by_name(
                CONSOLIDATION_AGENT_NAME
            )
            if agent_id is not None:
                session_id = await client.create_session(
                    agent_id,
                    name=f"project{project_id}-consolidation",
                    chat_model_config=await stage_model_config(
                        StageKey.ACCEPTANCE
                    ),
                    workspace_id=f"proj-{project_id}",
                )
                sections = []
                approved = await _approved_artifacts_by_stage(db, project)
                for stage in STAGE_ORDER:
                    artifact = approved.get(stage)
                    if artifact is None:
                        continue
                    try:
                        content = (
                            Path(get_settings().artifact_dir)
                            / artifact.storage_path
                        ).read_text(encoding="utf-8")
                    except OSError:
                        continue
                    if len(content) > _KICKOFF_ARTIFACT_CAP:
                        content = (
                            content[:_KICKOFF_ARTIFACT_CAP] + "\n…（已截断）"
                        )
                    sections.append(
                        f"=== {STAGE_AGENT_NAMES[stage]} · 《{artifact.title}》 ===\n{content}"
                    )
                await client.send_message(
                    agent_id,
                    session_id,
                    _CONSOLIDATION_PROMPT
                    + "\n\n" + "\n\n".join(sections),
                )
                interrupted = False
                deadline = asyncio.get_event_loop().time() + (
                    _CONSOLIDATION_TIMEOUT
                )
                while asyncio.get_event_loop().time() < deadline:
                    await asyncio.sleep(4)
                    status = await client.get_session_status(
                        agent_id, session_id
                    )
                    if status == "awaiting_permission" and not interrupted:
                        # Distillation needs no tools; un-park and let
                        # the reply close instead of waiting out the
                        # timeout on a permission nobody will answer.
                        await client.interrupt_session(agent_id, session_id)
                        interrupted = True
                        continue
                    if status == "idle":
                        data = await client.get_messages(
                            agent_id, session_id
                        )
                        draft_content = _last_assistant_text(
                            data["messages"]
                        )
                        break
            if not draft_content:
                archive = await db.scalar(
                    select(ProjectArchive).where(
                        ProjectArchive.project_id == project_id
                    )
                )
                draft_content = (
                    archive.summary
                    if archive
                    else f"项目《{project.name}》已完成验收（无可用产物摘要）。"
                )
                logger.info(
                    "consolidation for project %s falls back to archive",
                    project_id,
                )
            draft = ConsolidationDraft(
                project_id=project_id, content=draft_content
            )
            db.add(draft)
            await db.flush()
            task = ApprovalTask(
                kind=ApprovalKind.CONSOLIDATION,
                project_id=project_id,
                approver_user_id=await resolve_approver(db, project),
                status=ApprovalStatus.PENDING,
            )
            db.add(task)
            await db.flush()
            draft.approval_task_id = task.id
            await db.commit()
            logger.info(
                "consolidation draft #%s ready for project %s",
                draft.id,
                project_id,
            )
    except Exception:
        logger.exception(
            "consolidation drafting failed for project %s", project_id
        )


async def decide_consolidation(
    db: AsyncSession,
    task: ApprovalTask,
    draft: ConsolidationDraft,
    project: Project,
    action: str,
    comment: str | None,
) -> dict:
    """Record the reviewer's verdict on a consolidation draft.

    Approve publishes into the owner group's distill KB (§6.4); return
    keeps the draft for a rework the current milestone does not
    automate — the comment carries the reason.
    """
    if task.status != ApprovalStatus.PENDING:
        raise FlowError(409, f"task #{task.id} is already {task.status.value}")
    # decided_at 用数据库时钟：server_default now() 走 PG 会话时区
    # (Asia/Shanghai)，Python 侧 utcnow 会与之相差 8 小时。
    now = func.now()
    if action == "approve":
        task.status = ApprovalStatus.APPROVED
        task.decided_at = now
        result = await _publish_distill(db, project, draft)
    elif action == "return":
        if not comment:
            raise FlowError(400, "returning a draft requires a comment")
        task.status = ApprovalStatus.RETURNED
        task.comment = comment
        task.decided_at = now
        result = {"kb_uploaded": False, "detail": "已退回，未入库"}
    else:
        raise FlowError(400, f"unknown action '{action}'")
    await db.commit()
    return result


async def _publish_distill(
    db: AsyncSession, project: Project, draft: ConsolidationDraft
) -> dict:
    """Write the approved draft into the owner group's distill KB.

    The group KB is auto-created on first use; both creation and
    upload need the runtime embedding credential. Without it the draft
    degrades to an archived file on disk — the knowledge is kept, the
    searchable-KB part waits for the operator (same gap as M3 RAG).
    """
    client = get_runtime_client()
    owner = (
        await db.scalars(
            select(User)
            .options(selectinload(User.groups))
            .where(User.id == project.owner_user_id)
        )
    ).first()
    group = owner.groups[0] if owner and owner.groups else None
    try:
        if group is None:
            raise RuntimeCallError(
                409, "项目负责人不属于任何组，无法定位沉淀库"
            )
        kb = await db.scalar(
            select(Kb).where(
                Kb.kb_type == KbType.DISTILL,
                Kb.owner_group_id == group.id,
            )
        )
        if kb is None or kb.agentscope_kb_id is None:
            runtime_id = await client.create_kb(
                f"{group.name}·沉淀库",
                "项目验收后沉淀的知识（审批通过后自动写入）",
            )
            if kb is None:
                kb = Kb(
                    name=f"{group.name}·沉淀库",
                    kb_type=KbType.DISTILL,
                    description="项目验收后沉淀的知识（审批通过后自动写入）",
                    agentscope_kb_id=runtime_id,
                    owner_group_id=group.id,
                )
                db.add(kb)
                await db.flush()
            else:
                kb.agentscope_kb_id = runtime_id
            db.add(KbGrant(kb_id=kb.id, group_id=group.id))
        filename = f"project{project.id}-consolidation-draft{draft.id}.md"
        await client.upload_kb_document(
            kb.agentscope_kb_id,
            filename,
            draft.content.encode("utf-8"),
            "text/markdown",
        )
        return {
            "kb_uploaded": True,
            "kb_name": kb.name,
            "detail": f"已写入沉淀库《{kb.name}》({filename})",
        }
    except RuntimeCallError as exc:
        rel = (
            f"{project.id}/consolidation/draft-{draft.id}-pending-kb.md"
        )
        abs_path = Path(get_settings().artifact_dir) / rel
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_text(draft.content, encoding="utf-8")
        return {
            "kb_uploaded": False,
            "kb_name": None,
            "detail": (
                f"入库暂缓：{exc.detail}。草稿已存档 artifacts/{rel}，"
                "凭证就绪后可重新入库"
            ),
        }


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
    # Deterministic from (project, run), but the testing stage needs
    # the assigned run id — flush first, then record the mapping so it
    # is visible before the first chat creates the runtime session.
    await db.flush()
    run.workspace_id = stage_workspace_id(run, project)
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

    # decided_at 用数据库时钟：server_default now() 走 PG 会话时区
    # (Asia/Shanghai)，Python 侧 utcnow 会与之相差 8 小时。
    now = func.now()
    accepted = False
    if action == "approve":
        task.status = ApprovalStatus.APPROVED
        task.decided_at = now
        run.status = StageRunStatus.APPROVED
        if run.stage is StageKey.ACCEPTANCE:
            project.status = ProjectStatus.ACCEPTED
            accepted = True
        else:
            project.current_stage = next_stage(run.stage)  # type: ignore[assignment]
        # M4: every approval refreshes the archive; acceptance approval
        # additionally spawns the consolidation flow (§6.4).
        try:
            await update_project_archive(db, project)
        except OSError:
            logger.warning(
                "project archive refresh failed (artifacts on disk?)",
                exc_info=True,
            )
        # §7.3: harvest the run's structured side-table into the trace
        # matrix. Best effort — never fails the approval itself.
        try:
            await ingest_trace_tables(
                db, run, agent_id=await resolve_stage_agent(run.stage)
            )
        except Exception:
            logger.warning(
                "trace ingestion failed for run #%s", run.id, exc_info=True
            )
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
    if accepted:
        _spawn_consolidation(project.id)
