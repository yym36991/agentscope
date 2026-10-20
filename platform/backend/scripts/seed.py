# -*- coding: utf-8 -*-
"""Idempotent seeding of the stage agents on the runtime.

Creates the platform's stage agents under the service principal
sys:runtime (architecture.md §8.2): end users get them pre-configured
and stay zero-config. Re-running is safe — existing agents are left
untouched.

M1 seeds only the requirement agent; later milestones add the rest via
the stage_flow_configs table instead of this hardcoded dict.

Usage (from platform/backend):
    .venv/Scripts/python -m scripts.seed
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models import StageKey  # noqa: E402
from app.runtime_client import (  # noqa: E402
    RuntimeCallError,
    get_runtime_client,
)
from app.services.flow import STAGE_AGENT_NAMES  # noqa: E402

# Prompt per stage; only stages present here are seeded.
SYSTEM_PROMPTS: dict[StageKey, str] = {
    StageKey.REQUIREMENT: (
        "你是「软件造价评估平台」的需求分析专家，服务银行行业软件"
        "造价评估全流程。你的职责：\n"
        "1. 通过提问澄清业务目标、干系人与角色、核心业务流程、"
        "合规/安全/性能等约束条件；\n"
        "2. 把用户口述的需求整理为结构化的《需求规格说明书（PRD）》"
        "草稿，包含：项目概述、干系人与角色、业务流程、功能需求清单"
        "（编号 FR-xx 并标优先级）、非功能需求、假设与开放问题；\n"
        "3. 用户确认后产出完整的 Markdown 版 PRD，作为本阶段交付物。\n"
        "规则：不臆造需求，不确定就问；保留用户原话的关键表述；"
        "全部使用简体中文。"
    ),
}


async def main() -> None:
    client = get_runtime_client()
    try:
        for stage, name in STAGE_AGENT_NAMES.items():
            prompt = SYSTEM_PROMPTS.get(stage)
            if prompt is None:
                continue  # not seeded in this milestone
            existing = await client.find_agent_by_name(name)
            if existing:
                print(f"= {name}: already seeded ({existing})")
            else:
                agent_id = await client.create_agent(name, prompt)
                print(f"+ {name}: created ({agent_id})")

        creds = await client.list_credentials()
        if creds:
            print(f"* 模型凭证: {creds[0]['name']} ({creds[0]['id']})")
        else:
            print(
                "! sys:runtime 名下还没有模型凭证——阶段可以开启，"
                "但对话前需要先配置（见 README）"
            )
    except RuntimeCallError as exc:
        print(f"runtime call failed: {exc.detail}")
        raise SystemExit(1) from exc
    finally:
        await client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
