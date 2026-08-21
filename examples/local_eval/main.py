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
from agentscope.app.access import (
    ResourceAccessPolicyBase,
    ResourceKind,
    ResourcePermission,
    ResourceRef,
)
from agentscope.app.hub import GitHubMCPHub
from agentscope.app.message_bus import RedisMessageBus
from agentscope.app.storage import AsyncSQLAlchemyStorage, StorageBase
from agentscope.app.workspace_manager import LocalWorkspaceManager
from agentscope.agent import ReActConfig
from agentscope.mcp import HttpMCPConfig, MCPClient
from agentscope.permission import PermissionContext, PermissionMode

from intel_handoff import IntelHandoffMiddleware
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


class AdminCatalogPolicy(ResourceAccessPolicyBase):
    """Publish the admin account's agents and credentials to every other user.

    Storage is owner-scoped, so a fresh user id starts with an empty agent
    list — fine for a developer console, wrong for a product where the
    intelligence assistant should already be there on first visit.

    Only *configuration* is shared. Sessions, messages and workspaces stay
    keyed by the caller's own user id, so everyone talks to the same experts
    without seeing each other's conversations. Credentials must be shared
    alongside the agents: session creation rejects a credential the caller
    cannot see, and the API masks shared secrets anyway.
    """

    _SHARED_KINDS = (ResourceKind.AGENT, ResourceKind.CREDENTIAL)

    def __init__(self, admin_user_id: str) -> None:
        self._owner = admin_user_id

    async def list_accessible(
        self,
        viewer_id: str,
        kind: ResourceKind,
        storage: StorageBase,
    ) -> list[ResourceRef]:
        """Return the admin account's resources of ``kind``, read-only."""
        # The owner reaches its own records through the ordinary owner path;
        # returning refs here would list every agent twice.
        if viewer_id == self._owner or kind not in self._SHARED_KINDS:
            return []

        if kind is ResourceKind.AGENT:
            records = await storage.list_agents(self._owner)
        else:
            records = await storage.list_credentials(self._owner)

        return [
            ResourceRef(
                kind=kind,
                owner_id=self._owner,
                resource_id=record.id,
                permission=ResourcePermission.READ,
            )
            for record in records
        ]


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

# Team members always run in freshly minted sessions, and MCP declarations
# are keyed by (agent, session) — an MCP attached through /workspace/mcp is
# therefore invisible to a worker after AgentInvite. Seeding it as a
# workspace default is what makes search reach the invited experts.
_tavily_key = os.getenv("TAVILY_API_KEY", "").strip()
_default_mcps: list[MCPClient] = []
if _tavily_key:
    _default_mcps.append(
        MCPClient(
            name="tavily",
            is_stateful=False,
            mcp_config=HttpMCPConfig(
                url=f"https://mcp.tavily.com/mcp/?tavilyApiKey={_tavily_key}",
            ),
        ),
    )

# Unset ⇒ the framework default (deny-all), i.e. every user builds their own
# agents. Set it to the admin / ops account holding the pre-built experts
# to turn the service into a product people can just open.
_admin_user = os.getenv("AGENTSCOPE_ADMIN_USER_ID", "").strip()
_access_policy = (
    AdminCatalogPolicy(_admin_user) if _admin_user else None
)

# Skills live in the workspace, which is per (user, agent) — the report
# template installed by the admin account would be missing for everyone
# else. Seeding it makes each new user's partition come equipped, the same
# reason the search MCP is a workspace default rather than a session one.
_skill_paths = [str(_here / "demo_skills" / "intel-report")]

storage = AsyncSQLAlchemyStorage(
    _pg_url,
    create_tables=True,
)
message_bus = RedisMessageBus(
    host=_redis_host,
    port=_redis_port,
)

def _mount_web_ui(application) -> Path | None:
    """Serve the built Web UI from the same process as the API.

    Vite output lives at ``examples/web_ui/frontend/dist``. API routes
    registered by ``create_app`` stay first; leftover GET paths fall
    through to ``index.html`` so the SPA can handle client routing.
    """
    dist = (_here.parent / "web_ui" / "frontend" / "dist").resolve()
    index = dist / "index.html"
    if not index.is_file():
        return None

    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    assets = dist / "assets"
    if assets.is_dir():
        application.mount(
            "/assets",
            StaticFiles(directory=str(assets)),
            name="ui-assets",
        )

    @application.get("/{full_path:path}", include_in_schema=False)
    async def _spa(full_path: str):
        candidate = (dist / full_path).resolve()
        try:
            candidate.relative_to(dist)
        except ValueError:
            return FileResponse(index)
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(index)

    return dist


async def _intel_agent_middlewares(
    user_id: str,
    agent_id: str,
    session_id: str,
) -> list[IntelHandoffMiddleware]:
    """Per-turn middleware: search tools only on 信息检索; cap TeamSay size."""
    del user_id, agent_id, session_id
    return [IntelHandoffMiddleware()]


app = create_app(
    storage=storage,
    message_bus=message_bus,
    workspace_manager=LocalWorkspaceManager(
        basedir=str(_here / "workspaces"),
        default_mcps=_default_mcps,
        skill_paths=_skill_paths,
    ),
    resource_access_policy=_access_policy,
    # External MCP market (GitHub Registry) + offline Skill Hub.
    # Flow: Hub → user library (PG) → POST /workspace/*/from-library.
    mcp_hubs=[GitHubMCPHub()],
    skill_hubs=[LocalEvalSkillHub()],
    extra_agent_middlewares=_intel_agent_middlewares,
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

_web_ui_dist = _mount_web_ui(app)


if __name__ == "__main__":
    print(
        f"Starting AgentScope local_eval on http://{_host}:{_port}\n"
        f"  storage = PostgreSQL\n"
        f"  message_bus = Redis ({_redis_host}:{_redis_port})\n"
        f"  mcp_hubs = github (GitHub MCP Registry)\n"
        f"  default_mcps = "
        f"{'tavily (web search)' if _tavily_key else 'none (set TAVILY_API_KEY)'}\n"
        f"  skill_hubs = local-eval\n"
        f"  shared catalog = "
        f"{f'agents + credentials of {_admin_user}' if _admin_user else 'off (per-user agents)'}\n"
        f"  web UI = "
        f"{_web_ui_dist if _web_ui_dist else 'not built (cd examples/web_ui/frontend && pnpm build)'}\n"
        f"  chat models = register via POST /credential + session config\n",
    )
    # reload=False: single process so RedisMessageBus + In-process runs stay simple
    uvicorn.run(
        "main:app",
        host=_host,
        port=_port,
        reload=False,
    )
