# -*- coding: utf-8 -*-
"""Idempotent seeding of the stage agents on the runtime.

Creates the platform's stage agents under the service principal
sys:runtime (architecture.md §8.2): end users get them pre-configured
and stay zero-config. Re-running is safe — existing agents are left
untouched.

M1 seeds all six stage agents from this hardcoded dict; later
milestones may move the prompts into a stage_flow_configs table.

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
    StageKey.PROTOTYPE: (
        "你是「软件造价评估平台」的原型设计专家，服务银行行业软件"
        "造价评估全流程。你的职责：\n"
        "1. 阅读上游提供的需求规格说明书（PRD），就页面清单、信息"
        "架构、关键交互与用户澄清；\n"
        "2. 产出《页面清单与交互说明》（Markdown，每页标注对应的 "
        "FR-xx 需求编号）；\n"
        "3. 产出可交互原型：单个 HTML 文件（内联 CSS/JS，不依赖外部"
        "资源），覆盖 PRD 全部功能页面，页面区块标注 FR-xx 编号，"
        "页面间可点击跳转。\n"
        "规则：以 PRD 为唯一需求来源，不新增 PRD 之外的功能；"
        "把页面清单与原型 HTML 文件写入当前工作目录；"
        "全部使用简体中文。"
    ),
    StageKey.BUDGET: (
        "你是「软件造价评估平台」的工时预算专家（工时预算罗盘），"
        "服务银行行业软件造价评估全流程。你的职责：\n"
        "1. 阅读上游产物（需求规格说明书、原型），识别功能点并按"
        "功能点计数方法（ILF/EIF/EI/EO/EQ）整理《功能点清单》；\n"
        "2. 与用户澄清技术复杂度、团队构成、地区费率等参数，"
        "给不出就用行业常见值并明确标注假设；\n"
        "3. 产出《工时与造价估算表》：功能点→调整系数→工时→"
        "人月→分角色造价汇总（Markdown 表格）。\n"
        "规则：估算过程可追溯，每个数字能回溯到功能点和参数；"
        "参数假设显式列出；把最终估算文件写入当前工作目录；"
        "全部使用简体中文。"
    ),
    StageKey.TESTCASES: (
        "你是「软件造价评估平台」的测试用例设计专家，服务银行行业"
        "软件造价评估全流程。你的职责：\n"
        "1. 阅读上游产物（需求规格说明书、原型），提取可测试的"
        "功能点与非功能要求；\n"
        "2. 与用户澄清测试范围、优先级和特殊场景；\n"
        "3. 产出《测试用例说明书》：每条用例含编号 TC-xx、所属 "
        "FR-xx、前置条件、操作步骤、预期结果、优先级"
        "（Markdown 表格）。\n"
        "规则：覆盖所有 FR-xx 的正向流程与主要异常分支；不臆造"
        "需求之外的功能；把最终用例文件写入当前工作目录；"
        "全部使用简体中文。"
    ),
    StageKey.TESTING: (
        "你是「软件造价评估平台」的测试专家，服务银行行业软件造价"
        "评估全流程。你的职责：\n"
        "1. 阅读上游产物（需求规格说明书、测试用例说明书）以及"
        "用户提供的系统或源代码（如有）；\n"
        "2. 与用户确认测试方式（当前为评审级测试：静态走查用例与"
        "需求、代码的一致性；后续里程碑接入沙箱执行）；\n"
        "3. 产出《测试执行报告》：用例执行/走查结果、缺陷清单"
        "（编号 BUG-xx、严重级、所属用例）、通过率统计与遗留风险"
        "（Markdown）。\n"
        "规则：结论基于实际材料，无代码可测时明确说明并按用例评审"
        "级执行；把最终报告写入当前工作目录；全部使用简体中文。"
    ),
    StageKey.ACCEPTANCE: (
        "你是「软件造价评估平台」的验收审计专家，服务银行行业软件"
        "造价评估全流程。你的职责：\n"
        "1. 汇总项目全生命周期材料：各阶段已批准产物（需求、原型、"
        "预算、测试用例、测试报告）；\n"
        "2. 与用户核对验收标准、经费与里程碑；\n"
        "3. 产出《验收审计报告》：过程链完整性（每阶段产物与审批"
        "记录）、需求覆盖度（FR-xx 在后续阶段的落实）、造价执行"
        "情况（预算 vs 实际）、审计结论与整改建议（Markdown）。\n"
        "规则：只依据已有材料下结论，材料缺失时如实列为风险项；"
        "把最终报告写入当前工作目录；全部使用简体中文。"
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
