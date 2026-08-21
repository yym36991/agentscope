# -*- coding: utf-8 -*-
"""SDK-built briefing backend — no create_app.

Same product as the Web UI demo (公开信息简报助手), assembled from
Agent / Model / Toolkit / MCP / Skill, then wrapped in a thin FastAPI.

    cd examples/local_eval
    set -a && source .env && set +a
    python sdk_briefing.py

    curl -sS http://127.0.0.1:8100/chat \\
      -H 'Content-Type: application/json' \\
      -d '{"session_id":"demo","message":"帮我看看贝壳找房最近在租房这块有什么动静。"}'
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from agentscope.agent import Agent, ReActConfig
from agentscope.credential import OpenAICredential
from agentscope.event import TextBlockDeltaEvent, ToolCallStartEvent
from agentscope.mcp import HttpMCPConfig, MCPClient
from agentscope.message import UserMsg
from agentscope.model import OpenAIChatModel
from agentscope.permission import PermissionContext, PermissionMode
from agentscope.state import AgentState
from agentscope.tool import FunctionTool, Toolkit

_HERE = Path(__file__).resolve().parent
_SKILL_DIR = _HERE / "demo_skills" / "intel-report"
_HOST = os.getenv("SDK_BRIEFING_HOST", "127.0.0.1")
_PORT = int(os.getenv("SDK_BRIEFING_PORT", "8100"))


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(
            f"Missing {name}. Copy .env.example to .env and fill it in.",
        )
    return value


def _bypass_state() -> AgentState:
    return AgentState(
        permission_context=PermissionContext(mode=PermissionMode.BYPASS),
    )


def _make_model() -> OpenAIChatModel:
    return OpenAIChatModel(
        credential=OpenAICredential(
            api_key=_require_env("CHATLING_API_KEY"),
            base_url=_require_env("CHATLING_BASE_URL"),
        ),
        model=os.getenv("CHATLING_MODEL", "chatling-plus").strip()
        or "chatling-plus",
        stream=True,
        client_kwargs={"timeout": 120.0},
    )


def _tavily_client() -> MCPClient | None:
    key = os.getenv("TAVILY_API_KEY", "").strip()
    if not key:
        return None
    return MCPClient(
        name="tavily",
        is_stateful=False,
        mcp_config=HttpMCPConfig(
            url=f"https://mcp.tavily.com/mcp/?tavilyApiKey={key}",
        ),
    )


_SEARCHER_PROMPT = """你是信息检索专家。根据任务用搜索工具查找公开信息，整理成带链接的事实条目。

工作方式：拆 3-6 个关键词逐个搜；每条只保留标题、时间、链接、不超过 40 字的要点；最多 8 条；按时间倒序。检索不到就写「未检索到公开信息」，不要编链接。

只用 tavily_search。禁止 tavily_crawl / tavily_extract / tavily_map / tavily_research。只做检索和摘录，不做分析。

输出：
## 检索目标
## 检索结果
1. [标题](链接) — 时间 — 要点
## 未覆盖
（可选，最多 3 条）
"""

_EXTRACTOR_PROMPT = """你是情报提炼专家。只基于收到的检索条目分析，禁止调用任何搜索工具。没有材料就回复「缺少检索材料」。

先归类再提炼变化点，再评估影响。每条结论用（来源 N）追溯。材料少也要写已有事实能支撑的变化点；不够判断就写「现有公开信息不足以判断」。推测必须写「推测」二字。

输出：
## 关键变化点（1-5 条）
## 分维度分析
## 影响评估
| 事项 | 性质（机会/威胁/中性） | 理由 | 建议关注度 |
## 材料不足
（可选，放最后，最多 3 条）
"""

_LEADER_PROMPT = """你是公开信息简报助手。自己不检索、不分析。价值是问清需求、调用专家、按 intel-report 技能汇总成简报。

【输出模式】每次回复只选一种：
- 模式 A 提问：只输出问题，一个工具都不调。一次最多 3 问。
- 模式 B 干活：不提问，直接调 ask_searcher / ask_extractor。
禁止同一轮既提问又调工具。禁止「现在开始组建团队」「如无异议我就开始」。

【澄清】先问清：目标对象、关注维度、时间范围、交付用途。四项齐了或用户说「直接开始」才进入干活。用户只补了一项就只追问还缺的，不要自己填默认值。问过两轮仍不齐，第三轮列出假设后开工。

【干活】先 ask_searcher（任务写具体）。拿到条目后 ask_extractor，只转发最多 8 条编号短条目，不要原文和 HTML。然后按 intel-report 技能写简报给用户。不要把专家的「未覆盖 / 材料不足」整节当作对用户的回复。

【纪律】事实必须来自 ask_searcher。未检索到就如实写。全文中文。
"""


@dataclass
class BriefingTeam:
    searcher: Agent
    extractor: Agent
    leader: Agent


def build_team(model: OpenAIChatModel, tavily: MCPClient | None) -> BriefingTeam:
    """One isolated trio of agents. Call once per chat session."""
    searcher_toolkit = Toolkit(mcps=[tavily] if tavily else None)
    searcher = Agent(
        name="信息检索",
        system_prompt=_SEARCHER_PROMPT,
        model=model,
        toolkit=searcher_toolkit,
        react_config=ReActConfig(max_iters=12),
        state=_bypass_state(),
    )
    extractor = Agent(
        name="情报提炼",
        system_prompt=_EXTRACTOR_PROMPT,
        model=model,
        toolkit=Toolkit(),
        react_config=ReActConfig(max_iters=8),
        state=_bypass_state(),
    )

    async def ask_searcher(task: str) -> str:
        """派给信息检索专家。task 写清对象、维度、时间范围。"""
        if tavily is None:
            return "搜索未配置：请设置 TAVILY_API_KEY 后重启。"
        msg = await searcher.reply(UserMsg(name="leader", content=task))
        return msg.get_text_content() or ""

    async def ask_extractor(material: str) -> str:
        """把检索短条目交给情报提炼。不要让它自己去搜。最多 8 条。"""
        clipped = material if len(material) <= 4000 else material[:4000] + "\n…(已截断)"
        msg = await extractor.reply(UserMsg(name="leader", content=clipped))
        return msg.get_text_content() or ""

    leader = Agent(
        name="公开信息简报助手",
        system_prompt=_LEADER_PROMPT,
        model=model,
        toolkit=Toolkit(
            tools=[
                FunctionTool(ask_searcher),
                FunctionTool(ask_extractor),
            ],
            skills_or_loaders=[str(_SKILL_DIR)],
        ),
        react_config=ReActConfig(max_iters=40),
        state=_bypass_state(),
    )
    return BriefingTeam(searcher=searcher, extractor=extractor, leader=leader)


class ChatIn(BaseModel):
    message: str
    session_id: str = Field(default="default")


def create_sdk_app() -> FastAPI:
    model = _make_model()
    tavily = _tavily_client()
    sessions: dict[str, BriefingTeam] = {}

    def team_for(session_id: str) -> BriefingTeam:
        if session_id not in sessions:
            sessions[session_id] = build_team(model, tavily)
        return sessions[session_id]

    app = FastAPI(
        title="公开信息简报助手（SDK）",
        description="AgentScope SDK 组装的后端，不经过 create_app。",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/")
    async def index() -> dict[str, Any]:
        return {
            "hint": "POST /chat  or  POST /chat/stream",
            "search": "tavily" if tavily else "off (set TAVILY_API_KEY)",
            "example": {
                "session_id": "demo",
                "message": "帮我看看贝壳找房最近在租房这块有什么动静。",
            },
        }

    @app.post("/chat")
    async def chat(body: ChatIn) -> dict[str, str]:
        team = team_for(body.session_id)
        msg = await team.leader.reply(
            UserMsg(name="user", content=body.message),
        )
        return {"session_id": body.session_id, "reply": msg.get_text_content() or ""}

    @app.post("/chat/stream")
    async def chat_stream(body: ChatIn) -> StreamingResponse:
        team = team_for(body.session_id)

        async def events():
            async for ev in team.leader.reply_stream(
                UserMsg(name="user", content=body.message),
            ):
                if isinstance(ev, TextBlockDeltaEvent):
                    yield f"data: {json.dumps({'type': 'text', 'delta': ev.delta}, ensure_ascii=False)}\n\n"
                elif isinstance(ev, ToolCallStartEvent):
                    yield f"data: {json.dumps({'type': 'tool', 'name': ev.tool_call_name}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(events(), media_type="text/event-stream")

    return app


app = create_sdk_app()


if __name__ == "__main__":
    has_tavily = bool(os.getenv("TAVILY_API_KEY", "").strip())
    print(
        f"SDK briefing service on http://{_HOST}:{_PORT}\n"
        f"  this is AgentScope SDK + FastAPI, not create_app\n"
        f"  search = {'tavily' if has_tavily else 'off'}\n"
        f"  docs = http://{_HOST}:{_PORT}/docs\n",
    )
    uvicorn.run(app, host=_HOST, port=_PORT, reload=False)
