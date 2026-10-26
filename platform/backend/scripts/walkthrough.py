# -*- coding: utf-8 -*-
"""M2 acceptance walkthrough: drive one fake project through all six
stages over the L1 API, exactly as the frontend would.

Flow per stage: start -> kickoff chat -> poll the relayed conversation
(auto-confirming HITL tool prompts like a user clicking 允许) ->
submit the reply -> approve. The prototype stage does one full
return/rework round first, so the acceptance also covers 退回修改:
new run (round 2), fresh session, and the kickoff injecting the
approver's return comment.

Usage (from platform/backend, with L1 on :8100 and the runtime on
:8000 already running):
    .venv/Scripts/python -m scripts.walkthrough
"""
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Windows consoles default to GBK, which cannot encode the ▶/✘/… log
# markers — reconfigure so the run never dies on a print().
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

import httpx  # noqa: E402

BASE = "http://127.0.0.1:8100"
STAGES = [
    "requirement",
    "prototype",
    "budget",
    "testcases",
    "testing",
    "acceptance",
]
STAGE_TITLES = {
    "requirement": "需求规格说明书",
    "prototype": "功能点明细",
    "budget": "工时与软件造价估算表",
    "testcases": "测试用例说明书",
    "testing": "测试执行报告",
    "acceptance": "验收审计报告",
}
POLL_INTERVAL = 4.0
STAGE_TIMEOUT = 15 * 60  # one LLM reply, generous ceiling
RETURN_STAGE = "prototype"  # where the rework round is exercised
RETURN_COMMENT = "演练退回：功能点明细请补充复杂度评定依据列。"

_T0 = time.time()


def log(msg: str) -> None:
    print(f"[{time.time() - _T0:7.1f}s] {msg}", flush=True)


def _asking_blocks(messages: list[dict]) -> list[dict]:
    """Tool-call blocks still awaiting a human verdict."""
    asking = []
    for msg in messages:
        for block in msg.get("content") or []:
            if (
                isinstance(block, dict)
                and block.get("type") == "tool_call"
                and block.get("state") == "asking"
            ):
                asking.append(block)
    return asking


def _last_assistant_text(messages: list[dict]) -> str | None:
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


async def wait_reply(
    client: httpx.AsyncClient, run_id: int
) -> str:
    """Poll until the run's reply settles; auto-confirm HITL prompts.

    Returns the final assistant text ("" on timeout — caller aborts).
    Every request carries its own short timeout and a failed tick is
    skipped, so a slow or hung relay can never stall the deadline —
    the first M2 run lost 50 minutes to exactly that.
    """
    deadline = time.time() + STAGE_TIMEOUT
    confirms = 0
    while time.time() < deadline:
        try:
            r = await client.get(
                f"/stage-runs/{run_id}/messages", timeout=15
            )
            r.raise_for_status()
            data = r.json()
            asking = _asking_blocks(data["messages"])
            if asking:
                names = ", ".join(
                    sorted({b.get("name", "?") for b in asking})
                )
                log(f"    HITL 确认: {names}")
                cr = await client.post(
                    f"/stage-runs/{run_id}/confirm",
                    json={"confirmed": True, "allow_all": True},
                    timeout=15,
                )
                if cr.status_code == 200:
                    confirms += 1
                await asyncio.sleep(POLL_INTERVAL)
                continue
            if not data["is_running"]:
                text = _last_assistant_text(data["messages"])
                if text:
                    log(
                        f"    回复完成（{len(text)} 字符，"
                        f"HITL 确认 {confirms} 次）"
                    )
                    return text
        except httpx.HTTPError as exc:
            log(f"    轮询暂时失败（{type(exc).__name__}），跳过本拍")
        await asyncio.sleep(POLL_INTERVAL)
    return ""


async def chat_and_wait(
    client: httpx.AsyncClient, run_id: int, note: str
) -> str:
    """Send *note* and wait for the reply, nudging once on a timeout.

    A nudge covers the real failure mode seen in the first M2 run: the
    LLM stream broke mid-reply (RemoteProtocolError) and the session
    went idle with the run still in_progress — a fresh message simply
    resumes the conversation instead of failing the walkthrough.
    """
    r = await client.post(
        f"/stage-runs/{run_id}/chat", json={"content": note}
    )
    r.raise_for_status()
    text = await wait_reply(client, run_id)
    if not text:
        log("    无产出/超时，催办一次")
        r = await client.post(
            f"/stage-runs/{run_id}/chat",
            json={"content": "请继续，一次性输出完整交付物正文。"},
        )
        r.raise_for_status()
        text = await wait_reply(client, run_id)
    return text


async def run_stage(
    client: httpx.AsyncClient,
    project_id: int,
    stage: str,
    note: str,
) -> None:
    log(f"▶ {stage}: 开启")
    r = await client.post(f"/projects/{project_id}/stages/{stage}/start")
    r.raise_for_status()
    run = r.json()
    log(
        f"    run #{run['id']} round {run['round']} "
        f"workspace={run.get('workspace_id')}"
    )

    text = await chat_and_wait(client, run["id"], note)
    if not text:
        raise RuntimeError(f"stage {stage} reply timed out")
    head = text[:80].replace("\n", " ")
    log(f"    产出预览: {head}…")

    r = await client.post(
        f"/stage-runs/{run['id']}/submit-latest",
        json={"title": STAGE_TITLES[stage]},
    )
    r.raise_for_status()
    artifact = r.json()
    log(f"    提交产物 v{artifact['version_no']} #{artifact['id']}")

    r = await client.get("/approvals/pending")
    r.raise_for_status()
    task = next(
        t for t in r.json() if t["stage_run_id"] == run["id"]
    )
    r = await client.post(
        f"/approvals/{task['id']}/decide", json={"action": "approve"}
    )
    r.raise_for_status()
    state = r.json()
    log(
        f"    审批通过 -> 项目阶段 {state['project_stage']} "
        f"状态 {state['project_status']}"
    )


async def main() -> None:
    async with httpx.AsyncClient(base_url=BASE, timeout=60) as client:
        username = f"walk{int(time.time())}"
        r = await client.post(
            "/auth/register",
            json={
                "username": username,
                "password": "Walk12345",
                "display_name": "验收演练员",
            },
        )
        r.raise_for_status()
        r = await client.post(
            "/auth/login", json={"username": username, "password": "Walk12345"}
        )
        r.raise_for_status()
        token = r.json()["access_token"]
        client.headers["Authorization"] = f"Bearer {token}"
        log(f"登录 {username}")

        r = await client.post(
            "/projects", json={"name": "M2验收演练-手机银行智能客服升级"}
        )
        r.raise_for_status()
        project = r.json()
        log(f"创建项目 #{project['id']}《{project['name']}》")

        note = (
            "项目背景：某银行手机银行APP升级，新增智能客服与转账限额"
            "管理两大功能。本演练无需向用户澄清，请直接按你的提示词要求"
            "一次性产出完整交付物。"
        )

        # Stage 1: straight through.
        await run_stage(client, project["id"], STAGES[0], note)

        # Stage 2: full return/rework round before approving.
        stage = RETURN_STAGE
        log(f"▶ {stage}: 开启（第 1 轮，将演练退回）")
        r = await client.post(f"/projects/{project['id']}/stages/{stage}/start")
        r.raise_for_status()
        run1 = r.json()
        if not await chat_and_wait(client, run1["id"], note):
            raise RuntimeError("prototype round 1 timed out")
        r = await client.post(
            f"/stage-runs/{run1['id']}/submit-latest",
            json={"title": STAGE_TITLES[stage]},
        )
        r.raise_for_status()
        r = await client.get("/approvals/pending")
        task = next(
            t for t in r.json() if t["stage_run_id"] == run1["id"]
        )
        r = await client.post(
            f"/approvals/{task['id']}/decide",
            json={"action": "return", "comment": RETURN_COMMENT},
        )
        r.raise_for_status()
        log(f"    审批退回: {RETURN_COMMENT}")

        # Rework round: new run, fresh session, kickoff carries the
        # comment — the assertions M2 actually promises. Sessions are
        # created lazily by the first chat, so re-fetch the run list
        # AFTER run2's chat instead of trusting start-response snapshots.
        r = await client.post(f"/projects/{project['id']}/stages/{stage}/start")
        r.raise_for_status()
        run2 = r.json()
        assert run2["round"] == 2, f"expected round 2, got {run2['round']}"
        if not await chat_and_wait(
            client, run2["id"], "请按退回意见修订。"
        ):
            raise RuntimeError("prototype round 2 timed out")
        r = await client.get(f"/stage-runs/{run2['id']}/messages")
        kickoff = next(
            (
                m
                for m in r.json()["messages"]
                if m.get("role") == "user"
                and "【阶段启动】" in str(m.get("content"))
            ),
            None,
        )
        assert kickoff is not None, "kickoff message not found"
        content = str(kickoff.get("content"))
        assert "【上一轮退回意见】" in content, "return comment not injected"
        assert RETURN_COMMENT[:10] in content, "comment text not injected"
        # M4: the requirement stage was approved before this rework
        # round, so its kickoff must also carry the archive digest.
        assert "【项目档案摘要】" in content, "archive digest not injected"
        log("    断言通过: kickoff 注入了退回意见与项目档案摘要")
        r = await client.get(f"/projects/{project['id']}/stage-runs")
        fresh = {x["id"]: x for x in r.json()}
        run1_now, run2_now = fresh[run1["id"]], fresh[run2["id"]]
        assert (
            run2_now["session_id"] != run1_now["session_id"]
        ), "rework must open a fresh session"
        assert run2_now["workspace_id"] == run1_now["workspace_id"] == (
            f"proj-{project['id']}"
        ), "doc stages share the project workspace"
        log(
            f"    断言通过: 退回重开 run #{run2['id']} round 2, 会话 "
            f"{run2_now['session_id'][:8]}… ≠ 旧 {run1_now['session_id'][:8]}…, "
            f"共享 workspace {run2_now['workspace_id']}"
        )
        r = await client.post(
            f"/stage-runs/{run2['id']}/submit-latest",
            json={"title": STAGE_TITLES[stage]},
        )
        r.raise_for_status()
        r = await client.get("/approvals/pending")
        task = next(
            t for t in r.json() if t["stage_run_id"] == run2["id"]
        )
        r = await client.post(
            f"/approvals/{task['id']}/decide", json={"action": "approve"}
        )
        r.raise_for_status()
        log("    第 2 轮审批通过")

        # Stages 3-6: straight through to acceptance.
        for stage in STAGES[2:]:
            await run_stage(client, project["id"], stage, note)

        # Testing stage workspace is the per-run sandbox, not the
        # project one — assert it from the run list.
        r = await client.get(f"/projects/{project['id']}/stage-runs")
        runs = r.json()
        testing = [
            x for x in runs if x["stage"] == "testing" and x["workspace_id"]
        ]
        assert testing and testing[0]["workspace_id"].startswith(
            "test-run-"
        ), f"testing workspace wrong: {testing}"
        log(f"断言通过: 测试阶段沙箱 workspace={testing[0]['workspace_id']}")

        r = await client.get(f"/projects/{project['id']}")
        final = r.json()
        assert final["status"] == "accepted", f"project status {final['status']}"
        log(
            f"✔ 全部六阶段走通：项目 #{final['id']} 状态 "
            f"{final['status']}，当前阶段 {final['current_stage']}"
        )

        # ---- M4: consolidation flow (§6.4) ----
        # Acceptance approval spawns the 知识沉淀 agent asynchronously;
        # its draft (or the archive fallback) opens a review task.
        log("▶ M4: 等待知识沉淀审批任务（异步起草中）")
        cons_task = None
        deadline = time.time() + 12 * 60
        while time.time() < deadline:
            r = await client.get("/approvals/pending")
            r.raise_for_status()
            cons_task = next(
                (
                    t
                    for t in r.json()
                    if t.get("kind") == "consolidation"
                ),
                None,
            )
            if cons_task:
                break
            await asyncio.sleep(POLL_INTERVAL)
        assert cons_task, "consolidation approval task never appeared"
        log(
            f"    沉淀任务 #{cons_task['id']} 出现，草稿预览: "
            f"{(cons_task.get('draft_head') or '')[:60]}…"
        )
        r = await client.get(f"/projects/{project['id']}/consolidations")
        r.raise_for_status()
        drafts = r.json()
        assert drafts and len(drafts[0]["content"]) > 100, "draft missing/short"
        log(
            f"断言通过: 沉淀草稿 #{drafts[0]['id']}"
            f"（{len(drafts[0]['content'])} 字）"
        )

        r = await client.post(
            f"/approvals/{cons_task['id']}/decide",
            json={"action": "approve"},
        )
        r.raise_for_status()
        result = r.json()
        # kb_uploaded=False is the documented degradation while no
        # embedding credential is registered; True once one exists.
        assert isinstance(result["kb_uploaded"], bool), result
        log(
            f"    沉淀审批通过: kb_uploaded={result['kb_uploaded']}"
            f" — {result['detail']}"
        )

        r = await client.get(f"/projects/{project['id']}/archive")
        r.raise_for_status()
        archive = r.json()
        assert archive["summary"] and "需求生成" in archive["summary"]
        log("断言通过: 项目档案摘要已生成（含各阶段关键结论）")
        log("✔ M4 记忆与沉淀闭环走通")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except AssertionError as exc:
        log(f"✘ 验收断言失败: {exc}")
        raise SystemExit(2)
    except Exception as exc:  # noqa: BLE001 — walkthrough reports and dies
        log(f"✘ 走查失败: {exc!r}")
        raise SystemExit(1)
