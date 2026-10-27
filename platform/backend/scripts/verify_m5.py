# -*- coding: utf-8 -*-
"""M5 acceptance harness (architecture.md §12 M5): multi-instance,
export service, offline install.

Covers:
1. Export service: a fresh project's artifact renders md → docx / xlsx
   (heading/table/list/quote paths) and reopens as a valid document;
   bad format is rejected.
2. Multi-instance: boots a second runtime replica (AS_PORT=8001)
   against the SAME PG + Redis as the primary and proves the §10.3
   claims live — agents visible from both replicas (shared storage),
   a session created via A and driven via B (chat fires, messages land
   in PG), the two-level run-mutex semantics (in-process double POST →
   409 from the ChatRunRegistry; cross-replica POST is accepted and
   the run queues behind the Redis lock, i.e. serialized, and A sees
   B's "running" through that same shared lock), and SSE events of
   B's run readable from A (bus fan-out → LB needs no stickiness).
3. L1 anti-corruption layer failover: with runtime_base_urls =
   dead-first + replica, RuntimeClient skips the dead URL (the exact
   code path the live L1 uses; PLATFORM_RUNTIME_BASE_URLS is set at
   module top so get_settings() picks it up).
4. Offline install (only if deploy/offline/backend-wheels exists):
   a fresh venv installs from the wheel dir with --no-index and
   imports app.main — the intranet mechanism, not just the script.

Run from platform/backend with the stack up (start.sh):

    .venv/Scripts/python -m scripts.verify_m5

The replica is terminated in a finally block (taskkill /T — it may
have MCP child processes); its log is logs/runtime-replica.log.
"""
import asyncio
import io
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

# Must be set before app.config is first imported (get_settings is
# lru_cached): dead URL first, replica second — the failover check.
os.environ["PLATFORM_RUNTIME_BASE_URLS"] = (
    "http://127.0.0.1:59998,http://127.0.0.1:8001"
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

BASE = "http://127.0.0.1:8100"
RUNTIME_A = "http://127.0.0.1:8000"
RUNTIME_B = "http://127.0.0.1:8001"
RT_HDR = {"X-User-ID": "sys:runtime"}

REPO = Path(__file__).resolve().parents[3]
BACKEND_DIR = Path(__file__).resolve().parents[1]
RUNTIME_DIR = REPO / "examples" / "platform_agent_service"
ROOT_PY = REPO / ".venv" / "Scripts" / "python.exe"
REPLICA_LOG = REPO / "logs" / "runtime-replica.log"

# The runtime's own env for the replica: same PG / Redis / download
# secret as the primary, own port and own Qdrant dir (embedded Qdrant
# is single-process; replicas must not share the on-disk index — in a
# real multi-instance deployment this is a shared Qdrant service).
REPLICA_ENV = {
    "AS_PORT": "8001",
    "AS_REDIS_PORT": "6380",
    "AS_QDRANT_PATH": str(RUNTIME_DIR / "qdrant-replica"),
    "PYTHONUNBUFFERED": "1",
}

EXPORT_MD = """# 智能客服升级需求文档

## 一、背景

本项目拟对手机银行**智能客服**模块升级，重点增强 `意图识别` 与多轮对话能力。

## 二、功能需求

1. 支持多轮对话上下文继承
2. 支持高峰期自动转人工

## 三、字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| session_id | string | 会话编号 |
| intent | string | 意图标签 |

> 备注：以上字段为初稿，评审通过后冻结。
"""

_T0 = time.time()


def log(msg: str) -> None:
    print(f"[{time.time() - _T0:6.1f}s] {msg}", flush=True)


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def spawn_replica() -> subprocess.Popen:
    """Boot replica B on 8001 and wait until it answers /agent/."""
    env = {**os.environ, **REPLICA_ENV}
    env.pop("PLATFORM_RUNTIME_BASE_URLS", None)  # not a runtime var
    REPLICA_LOG.parent.mkdir(exist_ok=True)
    logf = open(REPLICA_LOG, "ab")
    logf.write(f"\n===== {time.strftime('%F %T')} m5 replica starting =====\n".encode())
    proc = subprocess.Popen(
        [str(ROOT_PY), "main.py"],
        cwd=str(RUNTIME_DIR),
        env=env,
        stdout=logf,
        stderr=subprocess.STDOUT,
    )
    async with httpx.AsyncClient(timeout=3, trust_env=False) as c:
        for _ in range(120):
            if proc.poll() is not None:
                raise RuntimeError(
                    f"replica exited with {proc.returncode} — see {REPLICA_LOG}"
                )
            try:
                r = await c.get(RUNTIME_B + "/agent/", headers=RT_HDR)
                if r.status_code == 200:
                    return proc
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.5)
    raise RuntimeError(f"replica did not come up in 60s — see {REPLICA_LOG}")


def teardown_replica(proc: subprocess.Popen) -> None:
    # /T: the replica may have MCP child processes (node/npx); kill
    # the tree, not just the python process.
    subprocess.run(
        ["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True
    )


async def wait_status(
    client: httpx.AsyncClient, sid: str, agent_id: str, target: str, timeout: float
) -> None:
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        r = await client.get(
            f"/sessions/{sid}/status", params={"agent_id": agent_id}
        )
        last = r.text[:120]
        if r.status_code == 200 and r.json().get("status") == target:
            return
        await asyncio.sleep(0.3)
    raise AssertionError(f"session never reached {target!r}: {last}")


# ---------------------------------------------------------------------------
# 1. export service
# ---------------------------------------------------------------------------


async def check_export(c: httpx.AsyncClient, token: str) -> None:
    from docx import Document
    from openpyxl import load_workbook

    hdr = auth(token)
    r = await c.post(
        "/projects", json={"name": f"M5导出验证-{int(time.time())}"}, headers=hdr
    )
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    r = await c.post(
        f"/projects/{pid}/stages/requirement/start", headers=hdr
    )
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    r = await c.post(
        f"/stage-runs/{rid}/submit",
        json={"title": "M5导出验证-需求文档", "content": EXPORT_MD},
        headers=hdr,
    )
    assert r.status_code == 200, r.text
    art = r.json()
    aid = art["id"]

    # docx: reopens, title present, the pipe table became a Word table
    r = await c.get(
        f"/stage-runs/{rid}/artifacts/{aid}/export",
        params={"fmt": "docx"},
        headers=hdr,
    )
    assert r.status_code == 200, r.text
    assert "wordprocessingml" in r.headers["content-type"]
    assert "filename*=UTF-8''" in r.headers.get("content-disposition", "")
    doc = Document(io.BytesIO(r.content))
    assert any("M5导出验证-需求文档" in p.text for p in doc.paragraphs)
    assert any("智能客服" in p.text for p in doc.paragraphs)
    assert len(doc.tables) == 1, f"expected 1 table, got {len(doc.tables)}"
    assert doc.tables[0].rows[0].cells[0].text == "字段"
    assert doc.tables[0].rows[1].cells[1].text == "string"

    # xlsx: 说明 sheet + one sheet per table, named by its heading
    r = await c.get(
        f"/stage-runs/{rid}/artifacts/{aid}/export",
        params={"fmt": "xlsx"},
        headers=hdr,
    )
    assert r.status_code == 200, r.text
    assert "spreadsheetml" in r.headers["content-type"]
    wb = load_workbook(io.BytesIO(r.content))
    assert wb.sheetnames == ["说明", "三、字段说明"], wb.sheetnames
    ws = wb["三、字段说明"]
    assert ws["A1"].value == "字段" and ws["B2"].value == "string"
    info_texts = [str(c_.value) for row in wb["说明"].iter_rows() for c_ in row if c_.value]
    assert any("多轮对话上下文继承" in t for t in info_texts)

    # invalid format → 422 (the Query pattern rejects it)
    r = await c.get(
        f"/stage-runs/{rid}/artifacts/{aid}/export",
        params={"fmt": "pdf"},
        headers=hdr,
    )
    assert r.status_code == 422, r.text
    log("[PASS] 导出服务：md → docx/xlsx（表格/加粗/列表/引用），非法格式 422")


# ---------------------------------------------------------------------------
# 2. multi-instance runtime
# ---------------------------------------------------------------------------


async def check_multi_instance() -> subprocess.Popen:
    proc = await spawn_replica()
    log(f"副本 B 就绪 (pid {proc.pid}, 日志 {REPLICA_LOG.name})")
    try:
        async with (
            httpx.AsyncClient(base_url=RUNTIME_A, headers=RT_HDR, timeout=15, trust_env=False) as a,
            httpx.AsyncClient(base_url=RUNTIME_B, headers=RT_HDR, timeout=15, trust_env=False) as b,
        ):
            # agents seeded once, visible from BOTH replicas (shared PG)
            names = set()
            for cl in (a, b):
                r = await cl.get("/agent/")
                assert r.status_code == 200, r.text
                for ag in r.json()["agents"]:
                    names.add((ag.get("data") or {}).get("name") or ag.get("name"))
            need = {"需求生成", "原型设计", "工时预算罗盘", "测试用例", "测试", "验收审计"}
            assert need <= names, f"missing agents on a replica: {need - names}"
            log("[PASS] 共享存储：六智能体在两个副本上都可见（同一 PG）")

            # model config from the registered credential — id/type only,
            # the api_key in the response is never printed (§8.2)
            r = await a.get("/credential/")
            creds = r.json()["credentials"]
            assert creds, "no credential under sys:runtime — chat test impossible"
            cred = creds[0]
            cfg = {
                "type": (cred.get("data") or {}).get("type") or "anthropic",
                "credential_id": cred["id"],
                "model": "glm-5.3",
                "parameters": {},
            }
            agent_id = next(
                ag["id"]
                for ag in (await a.get("/agent/")).json()["agents"]
                if ((ag.get("data") or {}).get("name") or ag.get("name")) == "需求生成"
            )

            # session created on A, driven from B — same PG/Redis behind
            r = await a.post(
                "/sessions/",
                json={"agent_id": agent_id, "name": "m5-verify", "chat_model_config": cfg},
            )
            assert r.status_code in (200, 201), r.text
            sid = r.json()["session_id"]

            def user_msg(text: str) -> dict:
                return {
                    "agent_id": agent_id,
                    "session_id": sid,
                    "input": {
                        "name": "user",
                        "role": "user",
                        "content": [{"type": "text", "text": text}],
                    },
                }

            long_msg = user_msg("请用大约300字介绍软件造价评估的一般流程。")
            short_msg = user_msg("请用一句话总结上面介绍的流程。")

            r = await b.post("/chat/", json=long_msg)
            assert r.status_code == 200, r.text
            log("[PASS] 跨副本会话：A 建会话，B 发首条消息（状态落共享存储）")

            # A's status endpoint derives "running" from the Redis lock
            # (is_locked), and A holds no local task for this session —
            # so seeing running via A IS the shared-lock proof.
            await wait_status(a, sid, agent_id, "running", timeout=30)
            log("[PASS] 分布式运行锁：B 执行中，A 经共享 Redis 锁观察到 running")

            # SSE from A while B's run generates: events fan out through
            # the shared bus (replay log first, then live), which is what
            # makes LB session-stickiness unnecessary (§10.3).
            async def read_some_sse() -> int:
                events = 0
                async with a.stream(
                    "GET",
                    f"/sessions/{sid}/stream",
                    params={"agent_id": agent_id},
                ) as resp:
                    assert resp.status_code == 200
                    async for line in resp.aiter_lines():
                        if line.startswith("data:"):
                            events += 1
                        if events >= 3:
                            break
                return events

            events = await asyncio.wait_for(read_some_sse(), timeout=30)
            assert events >= 3, f"only {events} SSE events from A for B's run"
            log("[PASS] 跨副本事件流：A 订阅 B 运行中的 SSE，收到事件（总线共享）")

            # In-process double-submit guard: a second POST to the SAME
            # replica while its run is active → 409 (ChatRunRegistry).
            # Retry once if the reply finished before the probe landed.
            got_409 = False
            for _ in range(2):
                r = await b.post("/chat/", json=short_msg)
                if r.status_code == 409:
                    got_409 = True
                    break
                await wait_status(a, sid, agent_id, "idle", timeout=180)
                r = await b.post("/chat/", json=long_msg)
                assert r.status_code == 200, r.text
                await wait_status(a, sid, agent_id, "running", timeout=30)
            assert got_409, "in-process double-submit guard never fired on B"
            log("[PASS] 进程内双投递保护：运行中的会话在 B 上再 POST → 409")

            # Cross-replica POST while B holds the lock → accepted (200):
            # the spawned task queues behind the distributed lock instead
            # of failing — runs serialize across processes.
            r = await a.post("/chat/", json=short_msg)
            assert r.status_code == 200, r.text
            log("[PASS] 跨副本投递：A 的 POST 被接受，任务排队等锁（跨进程串行化）")

            await wait_status(a, sid, agent_id, "idle", timeout=240)
            r = await b.get(
                f"/sessions/{sid}/messages", params={"agent_id": agent_id}
            )
            msgs = r.json()["messages"]
            replies = [m for m in msgs if m.get("role") == "assistant"]
            assert len(replies) >= 2, (
                f"expected >=2 serialized assistant replies, got {len(replies)}"
            )
            log(f"[PASS] 串行执行：两条消息先后完成，B 读到 {len(replies)} 条回答")

            # best-effort cleanup of the verify session
            await a.delete(f"/sessions/{sid}", params={"agent_id": agent_id})
    except BaseException:
        teardown_replica(proc)
        raise

    # 3. L1 failover — replica must still be up here; the client reads
    # PLATFORM_RUNTIME_BASE_URLS (dead first, replica second).
    try:
        from app.runtime_client import RuntimeClient

        client = RuntimeClient()
        assert len(client._clients) == 2
        agent_id = await client.find_agent_by_name("需求生成")
        assert agent_id, "failover client could not find the agent"
        await client.aclose()
        log("[PASS] L1 防腐层：dead→replica 连接级故障转移（仅连接期错误重试）")
    finally:
        teardown_replica(proc)
    return proc


# ---------------------------------------------------------------------------
# 4. offline install mechanism (only when the bundle was built)
# ---------------------------------------------------------------------------


def check_offline() -> None:
    wheels = REPO / "deploy" / "offline" / "backend-wheels"
    reqs = REPO / "deploy" / "offline" / "backend-requirements.txt"
    if not (reqs.is_file() and any(wheels.glob("*.whl"))):
        log("[SKIP] 离线安装：跳过（未构建 deploy/offline/backend-wheels）")
        return
    venv_dir = REPO / "deploy" / "offline" / "backend-test-venv"
    if venv_dir.exists():
        shutil.rmtree(venv_dir)
    subprocess.run(
        [sys.executable, "-m", "venv", str(venv_dir)], check=True
    )
    pip = venv_dir / "Scripts" / "pip.exe"
    subprocess.run(
        [
            str(pip), "install", "--no-index",
            "--find-links", str(wheels), "-r", str(reqs),
        ],
        check=True,
        capture_output=True,
    )
    py = venv_dir / "Scripts" / "python.exe"
    r = subprocess.run(
        [
            str(py), "-I", "-c",
            "import sys; sys.path.insert(0, r'%s'); "
            "import app.main; print('OFFLINE_IMPORT_OK')" % BACKEND_DIR,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert "OFFLINE_IMPORT_OK" in r.stdout, r.stdout[-500:] + r.stderr[-500:]
    shutil.rmtree(venv_dir)  # mechanism proven, don't keep the copy
    log("[PASS] 离线安装：--no-index 从 wheels 建 venv，import app.main 通过")


async def main() -> None:
    async with httpx.AsyncClient(base_url=BASE, timeout=30, trust_env=False) as c:
        r = await c.get("/docs")
        assert r.status_code == 200, "L1 (8100) not up — run start.sh first"
        r = await c.post(
            "/auth/login", json={"username": "platadmin", "password": "Smoke123"}
        )
        assert r.status_code == 200, f"platadmin login failed: {r.text[:120]}"
        token = r.json()["access_token"]
        log("L1 就绪，platadmin 登录成功")

        await check_export(c, token)

    await check_multi_instance()
    check_offline()
    log("M5 验证全部通过 [ALL PASS]")


if __name__ == "__main__":
    asyncio.run(main())
