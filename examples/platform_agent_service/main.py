# -*- coding: utf-8 -*-
"""软件全生命周期管控平台的 AgentScope 运行时入口。

派生自 ``examples/agent_service/main.py``（上游原版保持零改动），
差异只有运行时组装三件套，全部可用环境变量覆盖：

- 落盘：``AsyncSQLAlchemyStorage`` → PG 库 ``agentscope``
  （``AS_STORAGE_URL``，库由仓库根 start.sh 创建，表启动时自动建）
- 总线：``RedisMessageBus``（``AS_REDIS_HOST`` / ``AS_REDIS_PORT``），
  状态外置到 Redis，因此可以多进程/多实例起多个副本
- 下载签名密钥：``AS_DOWNLOAD_SECRET``（重启后签名 URL 仍有效）
- 知识库向量索引：Qdrant 本地落盘（``AS_QDRANT_PATH``，默认本目录
  ``qdrant/``）——进程内嵌、不引入独立向量库服务，索引随重启保留；
  文档字节在 blobs/、KB/文档记录在 PG，这里只存分块向量

由仓库根 start.sh 第 [3/6] 项拉起，端口 8000；会话工作区落在
本目录 ``workspaces/`` 下。其余能力（渠道/知识库/子智能体模板/
长期记忆）与上游示例保持一致。
"""
import os
import re
import sys

import uvicorn
from fastapi.middleware import Middleware
from fastapi.middleware.cors import CORSMiddleware

from agentscope.app import create_app, SubAgentTemplate
from agentscope.app.channel import (
    DingTalkChannel,
    DiscordChannel,
    FeishuChannel,
)
from agentscope.app.hub import ClawSkillHub, GitHubMCPHub
from agentscope.app.message_bus import RedisMessageBus
from agentscope.app.rag.knowledge_base_manager import CollectionPerKbManager
from agentscope.app.storage import AsyncSQLAlchemyStorage
from agentscope.app.workspace_manager import LocalWorkspaceManager
from agentscope.mcp import MCPClient, StdioMCPConfig, HttpMCPConfig
from agentscope.middleware import AgenticMemoryMiddleware, MiddlewareBase
from agentscope.permission import PermissionContext, PermissionMode
from agentscope.rag import ApproxTokenChunker, QdrantStore
from agentscope.workspace import WorkspaceBase

default_mcps = [
    MCPClient(
        name="playwright",
        mcp_config=StdioMCPConfig(
            command="npx",
            args=["@playwright/mcp@latest"],
        ),
        is_stateful=True,
    ),
]

if os.getenv("AMAP_API_KEY"):
    default_mcps.append(
        MCPClient(
            name="amap",
            mcp_config=HttpMCPConfig(
                url=f"https://mcp.amap.com/mcp?key="
                f"{os.environ['AMAP_API_KEY']}",
            ),
            is_stateful=False,
        ),
    )

# Price baseline served by the platform's L1 backend (architecture.md
# §7.1 dual track): the budget agent queries exact rates/coefficients
# from the structured price_items table instead of "recalling" numbers.
# Read-only localhost endpoint; every stage agent gets the tool, only
# the budget blueprint tells its agent to use it.
default_mcps.append(
    MCPClient(
        name="price-baseline",
        mcp_config=HttpMCPConfig(
            url=os.getenv(
                "AS_PRICE_MCP_URL",
                "http://127.0.0.1:8100/mcp/price/",
            ),
        ),
        is_stateful=False,
    ),
)

# Durable storage in PostgreSQL — the database itself ("agentscope") is
# created by start.sh; tables are provisioned automatically on startup.
storage = AsyncSQLAlchemyStorage(
    url=os.getenv(
        "AS_STORAGE_URL",
        "postgresql+asyncpg://postgres@localhost:5432/agentscope",
    ),
)

# 进程内嵌 Qdrant 的本地落盘模式：不是独立服务，只是 pip 依赖；索引
# 持久化到磁盘，运行时重启后 KB 检索不再丢（元数据本就在 PG）。
# 多实例部署（M5）时改为 url= 指向共享 Qdrant，或换 PG 向量后端。
vector_store = QdrantStore(
    path=os.getenv(
        "AS_QDRANT_PATH",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "qdrant"),
    ),
)


# L1 编排层为每个阶段会话显式传入的共享工作区 id（architecture.md
# §8.5：文档类阶段 proj-{id} 共享，测试阶段 test-run-{run_id} 沙箱）。
_SHARED_WORKSPACE_RE = re.compile(r"^(proj-\d+|test-run-\d+)$")


class ProjectWorkspaceManager(LocalWorkspaceManager):
    """共享工作区 id 的目录按 id 本身确定，而非按智能体。

    上游 LocalWorkspaceManager 的 workdir 恒为 ``basedir/agent_id``，
    缓存才按 workspace_id 键——同一 ``proj-19`` 只有恰好命中缓存时才
    真正共享目录；重启或 TTL 逐出后，下一个解析该 id 的阶段智能体会
    拿到自己名下的另一个目录，跨阶段文件与项目记忆会静默断裂。
    平台显式传入的 id 必须目录确定：把 id 当 agent_id 委托给父类，
    workdir 即 ``basedir/{workspace_id}``；未命中正则的（默认铸造的
    UUID/哈希 id）保持上游行为 ``basedir/agent_id`` 不变。
    """

    async def get_workspace(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
        workspace_id: str | None = None,
    ):
        if workspace_id and _SHARED_WORKSPACE_RE.match(workspace_id):
            return await super().get_workspace(
                user_id, workspace_id, session_id, workspace_id
            )
        return await super().get_workspace(
            user_id, agent_id, session_id, workspace_id
        )


async def longterm_memory_factory(
    user_id: str,
    agent_id: str,
    session_id: str,
    workspace: WorkspaceBase,
) -> list[MiddlewareBase]:
    """Attach Markdown-file long-term memory, stored under the session's
    workspace so it is reachable through whichever backend is bound."""
    del user_id, agent_id, session_id
    return [
        AgenticMemoryMiddleware(
            workdir=workspace.workdir,
            backend=workspace.get_backend(),
        ),
    ]


app = create_app(
    storage=storage,
    # Redis Streams message bus — state lives in Redis, so the runtime
    # can be started as more than one process / instance.
    message_bus=RedisMessageBus(
        host=os.getenv("AS_REDIS_HOST", "localhost"),
        port=int(os.getenv("AS_REDIS_PORT", "6379")),
    ),
    # Stable download-URL signing secret: survives restarts and would be
    # shared by every instance behind a load balancer.
    download_secret=os.getenv("AS_DOWNLOAD_SECRET", "dev-only-download-secret"),
    workspace_manager=ProjectWorkspaceManager(
        basedir=os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "workspaces",
        ),
        # The default MCP servers that will be added into the workspace
        default_mcps=default_mcps,
    ),
    # Knowledge base feature — backed by the on-disk Qdrant store above.
    # The CollectionPerKbManager allocates one collection per knowledge
    # base, so any embedding dimension is allowed.
    knowledge_base_manager=CollectionPerKbManager(
        storage=storage,
        vector_store=vector_store,
    ),
    # Chunker classes users can pick from when creating a knowledge base;
    # the chosen type and parameters are pinned on the knowledge base.
    knowledge_chunkers=[ApproxTokenChunker],
    # Resource hubs the UI browses under /hub. Neither needs credentials
    # of its own — an individual MCP card declares whatever key it wants
    # from the user in its ``inputs_schema``. Passing a ClawHub token
    # only raises the rate limit.
    mcp_hubs=[GitHubMCPHub()],
    skill_hubs=[ClawSkillHub(api_token=os.getenv("CLAWHUB_API_TOKEN"))],
    # Customize your own subagent templates
    custom_subagent_templates=[
        SubAgentTemplate(
            type="explorer",
            description=(
                "Read-only agents specialized in exploration tasks. It can "
                "read files but cannot modify, create, or delete them. Use "
                "this agent type when you need to investigate the codebase, "
                "understand its structure, or gather information from files "
                "to support planning—without making any changes."
            ),
            system_prompt_template="""You are {member_name}, an explorer \
agent in team '{team_name}' led by {leader_name}.

Team purpose: {team_description}

Your role: {member_description}

## Responsibilities
- Complete the exploration tasks assigned by the team leader.
- You are read-only: you may inspect files and the codebase, but you must \
never modify, create, or delete anything.

## Reporting
- Always report the task result back to {leader_name} using the TeamSay \
tool, whether the task succeeds or fails.
- Keep your private reasoning private; only share conclusions and findings \
that the leader needs.

Note: `TeamSay` is your ONLY channel to communicate with {leader_name} and \
the other team members. Any output you produce is invisible to them, \
so anything you want them to see MUST be sent through `TeamSay`.""",
            permission_context=PermissionContext(
                # Read-only
                mode=PermissionMode.EXPLORE,
            ),
        ),
    ],
    # Long-term memory. The default PER_AGENT workspace isolation makes
    # the memory survive across sessions of the same agent.
    extra_agent_middlewares=longterm_memory_factory,
    extra_middlewares=[
        Middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        ),
    ],
    channels=[
        DingTalkChannel,
        DiscordChannel,
        FeishuChannel,
    ],
)


if __name__ == "__main__":
    # Start the service. Port is configurable (AS_PORT) so a second
    # replica can run on the same host against the same PG + Redis —
    # the multi-instance form architecture.md §10.3 describes.
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.getenv("AS_PORT", "8000")),
        # Hot reload forces a SelectorEventLoop on Windows, which cannot
        # spawn the subprocesses that the builtin tools rely on
        reload=sys.platform != "win32",
    )
