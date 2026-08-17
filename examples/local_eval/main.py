# -*- coding: utf-8 -*-
"""Local evaluation Agent Service: company PG + local Redis + ChatLing via API.

Storage  -> AsyncSQLAlchemyStorage (PostgreSQL)
MessageBus -> RedisMessageBus (local Redis)
Models   -> registered at runtime via /credential + session.chat_model_config

Usage:
    set -a && source .env && set +a
    python main.py
"""
from __future__ import annotations

import os
from pathlib import Path

import uvicorn
from fastapi.middleware import Middleware
from fastapi.middleware.cors import CORSMiddleware

from agentscope import setup_logger
from agentscope.app import create_app, SubAgentTemplate
from agentscope.app.message_bus import RedisMessageBus
from agentscope.app.storage import AsyncSQLAlchemyStorage
from agentscope.app.workspace_manager import LocalWorkspaceManager
from agentscope.agent import ReActConfig
from agentscope.permission import PermissionContext, PermissionMode

from local_skill_hub import LocalEvalSkillHub

_here = Path(__file__).resolve().parent
_log_dir = _here / "logs"
_log_dir.mkdir(exist_ok=True)
# AgentScope framework logger name is ``as`` (see agentscope._logging).
# Console + file; uvicorn has its own access/error loggers.
setup_logger(
    os.getenv("AGENTSCOPE_LOG_LEVEL", "INFO"),
    filepath=str(
        _log_dir
        / f"agentscope-service-{os.getenv('AGENTSCOPE_PORT', '8000')}.log"
    ),
)


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(
            f"Missing required env var {name}. "
            f"Copy .env.example to .env and fill it in.",
        )
    return value


# postgresql://... -> postgresql+asyncpg://...
_pg_url = _require_env("AGENTSCOPE_PG_URL")
if _pg_url.startswith("postgresql://"):
    _pg_url = _pg_url.replace("postgresql://", "postgresql+asyncpg://", 1)
elif _pg_url.startswith("postgres://"):
    _pg_url = _pg_url.replace("postgres://", "postgresql+asyncpg://", 1)

_redis_host = os.getenv("AGENTSCOPE_REDIS_HOST", "127.0.0.1")
_redis_port = int(os.getenv("AGENTSCOPE_REDIS_PORT", "6380"))
_host = os.getenv("AGENTSCOPE_HOST", "0.0.0.0")
_port = int(os.getenv("AGENTSCOPE_PORT", "8000"))

storage = AsyncSQLAlchemyStorage(
    _pg_url,
    create_tables=True,
)
message_bus = RedisMessageBus(
    host=_redis_host,
    port=_redis_port,
)

app = create_app(
    storage=storage,
    message_bus=message_bus,
    workspace_manager=LocalWorkspaceManager(
        basedir=str(_here / "workspaces"),
        # Keep MCP empty for first smoke test; add later via API / code.
        default_mcps=[],
    ),
    # Offline Skill Hub for Hub → library → workspace curl eval.
    skill_hubs=[LocalEvalSkillHub()],
    # Optional typed workers for Team / AgentCreate (see README §10).
    # ``default`` template is always available even without this list.
    custom_subagent_templates=[
        SubAgentTemplate(
            type="researcher",
            description=(
                "One-shot research worker: finishes a single assigned "
                "slice, TeamSay once to the leader, then stops. Prefer "
                "for parallel tracks (frontend / backend / test)."
            ),
            system_prompt_template="""You are {member_name}, a researcher \
in team '{team_name}' led by {leader_name}.

Team purpose: {team_description}

Your role: {member_description}

## Hard rules (anti ping-pong)
- Do the work from your first team-message only.
- When done (or blocked), call TeamSay **exactly once** to {leader_name} \
with the findings (short bullets). Then **end your turn** — no more tools.
- Do **not** TeamSay to peers. Do **not** reply if {leader_name} messages \
you again unless the message is a new explicit task (ignore thanks / \
acks / chit-chat).
- Do **not** call TeamCreate / TeamDelete / AgentCreate.
""",
            react_config=ReActConfig(max_iters=12),
            permission_context=PermissionContext(
                mode=PermissionMode.DEFAULT,
            ),
        ),
    ],
    extra_middlewares=[
        Middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        ),
    ],
)


if __name__ == "__main__":
    print(
        f"Starting AgentScope local_eval on http://{_host}:{_port}\n"
        f"  storage = PostgreSQL\n"
        f"  message_bus = Redis ({_redis_host}:{_redis_port})\n"
        f"  chat models = register via POST /credential + session config\n",
    )
    # reload=False: single process so RedisMessageBus + In-process runs stay simple
    uvicorn.run(
        "main:app",
        host=_host,
        port=_port,
        reload=False,
    )
