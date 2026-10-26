# -*- coding: utf-8 -*-
"""Smoke-check the per-project workspace dir (ProjectWorkspaceManager).

Creates a project, runs one requirement chat turn through L1, then
asserts the runtime materialized ``workspaces/proj-{id}/`` — the
deterministic shared dir — instead of the stock ``basedir/{agent_id}``
layout a shared workspace id used to fall into after a restart or TTL
eviction (see examples/platform_agent_service/main.py).

Usage (from platform/backend, with L1 on :8100 and the runtime on
:8000 already running):
    .venv/Scripts/python -m scripts.verify_workspace
"""
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

import httpx  # noqa: E402

BASE = "http://127.0.0.1:8100"
WORKSPACES = (
    Path(__file__).resolve().parents[3]
    / "examples"
    / "platform_agent_service"
    / "workspaces"
)


async def main() -> None:
    async with httpx.AsyncClient(base_url=BASE, timeout=60) as client:
        username = f"ws{int(time.time())}"
        r = await client.post(
            "/auth/register",
            json={
                "username": username,
                "password": "Walk12345",
                "display_name": "工作区验证员",
            },
        )
        r.raise_for_status()
        r = await client.post(
            "/auth/login",
            json={"username": username, "password": "Walk12345"},
        )
        r.raise_for_status()
        client.headers["Authorization"] = f"Bearer {r.json()['access_token']}"

        r = await client.post("/projects", json={"name": "工作区目录验证"})
        r.raise_for_status()
        pid = r.json()["id"]
        print(f"project #{pid}")

        r = await client.post(f"/projects/{pid}/stages/requirement/start")
        r.raise_for_status()
        run_id = r.json()["id"]

        r = await client.post(
            f"/stage-runs/{run_id}/chat",
            json={
                "content": (
                    "项目：内部审批小工具升级，两个功能即可。"
                    "请直接一次性产出精简 PRD（500 字以内）。"
                )
            },
        )
        r.raise_for_status()

        proj_dir = WORKSPACES / f"proj-{pid}"
        deadline = time.time() + 150
        while time.time() < deadline:
            if (proj_dir / "Memory").is_dir():
                print(f"OK: {proj_dir} 已按项目 id 落盘（含 Memory/）")
                break
            await asyncio.sleep(4)
        else:
            raise SystemExit(f"FAIL: {proj_dir} 未出现，工作区仍按智能体目录解析")

        # The turn keeps running after the dir appears; report and leave
        # it to finish on its own (a stray in-flight turn is harmless).
        r = await client.get(f"/stage-runs/{run_id}/messages", timeout=15)
        print(f"run #{run_id} is_running={r.json()['is_running']}")


if __name__ == "__main__":
    asyncio.run(main())
