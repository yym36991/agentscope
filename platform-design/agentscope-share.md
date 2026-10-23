# AgentScope 分享：框架选型 · 框架能力 · 造价平台实践

> **文档结构与范围**
> - **第一部分**：开源智能体框架横向对比——调研目的是为《软件造价评估平台》选型；
> - **第二部分**：AgentScope 框架能力，行文跟随官方文档（2.0.9 中文版）：先 SDK（Software Development Kit，软件开发工具包）核心组件，后 Agent Service 服务层；
> - **第三部分**：依托 AgentScope 做的软件造价评估平台（自研运行时入口在 `examples/platform_agent_service`），改了哪里、为了支持什么。
> - 只讲 SDK / HTTP（HyperText Transfer Protocol，超文本传输协议）API（Application Programming Interface，应用程序编程接口）两种用法；Star 数与版本号均为 2026-10-21 查询值。

## 三个要点

1. **选型结论**：AgentScope 是六个候选中唯一同时满足「SDK 可嵌入 + 多租户服务层 + Apache-2.0 协议 + MCP 内建」的框架——其余候选要么是单人应用、要么是低代码平台、要么未过稳定期。
2. **框架结构**：两层，智能都在下层——SDK 层（无状态 Agent + 工具箱 + 会话状态）负责智能，Agent Service 层包一层多租户 HTTP 服务；两层可独立使用。
3. **平台实践**：运行时保持官方形态不动，只改组装三件套（存储 / 消息总线 / 下载签名密钥）；鉴权、流程审批、产物版本全部外置到自研编排层——**平台能力不靠改框架，靠「独立目录 + 组装参数 + 外置控制面」**。

---

# 第一部分 开源框架横向对比

## 1.1 选型标尺：五项硬需求

平台目标：**6 个智能体覆盖软件造价评估全生命周期**（需求澄清 → PRD（Product Requirements Document，需求规格说明书）→ 原型 → 工时预算 → 测试 → 验收审计），**产物必须人工审批**，**多用户多角色**（项目经理 / 审批人 / 需求提出者），三层架构（自研编排层 + 智能体运行时 + 前端）——运行时必须可嵌入，不能反过来吞掉编排层。

| # | 硬需求 | 含义 |
|---|---|---|
| 1 | 多智能体编排 | 6 个智能体按阶段串行协作，可扩展 |
| 2 | 人工审批（HITL，Human-in-the-Loop，人在回路） | 产物送审 + 工具调用确认，长周期可审计 |
| 3 | 自定义 HTTP 服务 | 接口、鉴权、SSE（Server-Sent Events，服务器单向事件流推送）自己定，前端自己写 |
| 4 | 多用户隔离 | 用户 / 会话 / 并发三层隔离 |
| 5 | MCP（Model Context Protocol，模型上下文协议——开放工具接入标准）生态 | 工具接入走开放标准 |

## 1.2 六个框架速览

### LangGraph（LangChain）——编排库的标杆

- Python + TypeScript 双栈纯库；MIT 协议；1.0 于 2025-10 稳定。三种形态：`pip install` 纯库、`langgraph dev` 开发服务器、LangSmith 商业托管。
- 核心抽象**状态图**：节点 + 条件边 + 显式 State schema，每个 superstep 后状态 reduce 并持久化到 Checkpointer；`interrupt()` + `Command` 恢复，HITL 是一等原语，同类最成熟。
- 生态分层：LangChain（框架）→ LangGraph（编排运行时）→ Deep Agents（上层 harness）→ LangSmith（平台）。
- **匹配度：中高**——只选「编排库」时的最强替代；但多租户、会话管理、SSE、凭证管理全部要自建或购买。

### DeerFlow（字节跳动）——事件驱动的通用智能体应用

- Python 后端 + Next.js 前端的单体应用（命令行 CLI（Command-Line Interface，命令行界面）+ Web UI）；MIT；v2.0（2026-06）彻底重写、摆脱 LangGraph 依赖。
- 核心是**事件驱动运行时**：Agent / Tool / MCP / HITL 都是一等原语，搭智能体 = 组合原语（composition-driven，组合驱动）；出厂自带 plan-and-execute 规划器。
- **对我们的价值：作参考而非底座**——v2 重写的头号动机是「链式流程装不下常态化的 HITL」，与我们「审批放状态机、工具确认放对话内挂起」的取舍同源；但形态仍是单人应用，无多租户 / 鉴权 / 会话隔离概念。

### DeepSeek Harness（DeepSeek AI）——一切皆插件

- TypeScript；桌面 / Web / CLI + SDK；MIT；0.2.x，官方标注 Developer Preview（承诺破坏性变更）；2026-08 开源，25 万+ star。
- 底层 Cordis 插件框架，连 agent loop 本身都是插件；**会话是 append-only 事件流**（事件溯源风格），fork / 恢复 / transcript / 审计全部从事件派生。
- **对我们的价值：理念借鉴**——事件溯源式会话对审计留痕（银行刚需）有直接启发；preview 状态 + TypeScript 栈不适合作底座。

### Dify（LangGenius）——可视化低代码平台

- Python + TypeScript 可视化平台，Docker 自托管或云服务；画布拖拽编排工作流，配 RAG（Retrieval-Augmented Generation，检索增强生成）管道与插件市场。
- **两条硬伤直接出局**：① 开源协议是 Dify Open Source License（Apache 2.0 附加条款：未经书面授权不得用源码运营多租户环境）——多用户平台需法务确认甚至商业授权；② **它自己就是编排层**，与自研编排层定位直接冲突。

### OpenCode（Anomaly）——终端编程智能体

- TypeScript；CLI / TUI（Terminal User Interface，终端界面）+ 桌面 + IDE（Integrated Development Environment，集成开发环境）扩展；MIT；C/S（Client/Server，客户端-服务器）架构，定位「开源版 Claude Code」。
- `opencode serve` 起 headless HTTP 服务器并暴露 **OpenAPI 3.1 规范**，SDK 由规范自动生成；内置 build（全权）/ plan（只读）两个 agent，permissions 与 policies 分层。
- **对我们的价值**：OpenAPI 驱动 SDK 的接口治理、只读 agent 的权限分级（「审查智能体只读化」直接可借鉴）；单用户工具形态不宜作底座。

### AgentScope（阿里通义实验室）——我们的选择

- Python ≥ 3.11；**Apache-2.0**（商用最友好，无附加条款）；**双层形态**：SDK 库（嵌入自己的服务）+ Agent Service（`create_app` 一键起多租户 FastAPI 服务，配官方 Web UI）。
- 设计哲学「为不断增强的模型能力设计」（design for increasingly agentic LLM（Large Language Model，大语言模型））——不预设固定编排去框住模型，依赖模型的推理和工具使用能力；多租户、多会话、分布式部署是一等公民。
- 风险：无官方 JavaScript SDK；迭代快（5 个月 2.0.0 → 2.0.10）；分布式部署标注 WIP（Work in Progress，开发中）。

## 1.3 横向对比总表

| 框架 | 维护方 | 语言 | 形态 | 协议 | Star* | 核心抽象 | 编排方式 |
|---|---|---|---|---|---|---|---|
| LangGraph | LangChain | Python + TS | 库 + 开发服务器 + 商业平台 | MIT | 43.6k | 状态图 | 代码优先 |
| DeerFlow | 字节跳动 | Python + TS | 单体应用（CLI + Web UI） | MIT | 84.2k | 事件驱动运行时 | 组合驱动 |
| DeepSeek Harness | DeepSeek | TypeScript | 桌面/Web/CLI + SDK | MIT | 256k | 插件树 + 事件流 | 配置组合 |
| Dify | LangGenius | Python + TS | 可视化平台（自托管/云） | Dify 许可† | 159k | 可视化工作流画布 | 可视化优先 |
| OpenCode | Anomaly | TypeScript | 终端/桌面编程助手（C/S） | MIT | 219k | 会话 + 工具循环 | 配置 |
| **AgentScope** | 阿里通义 | Python | SDK 库 + Agent Service | Apache-2.0 | 33.6k | ReAct Agent + 服务资源模型 | 代码优先 |

\* 2026-10-21 GitHub API 查询值。† Apache 2.0 附加多租户与品牌条款。

**五项硬需求匹配矩阵**：

| 需求 | LangGraph | DeerFlow | DeepSeek Harness | Dify | OpenCode | AgentScope |
|---|---|---|---|---|---|---|
| 多智能体编排 | ★★★ 图任意拓扑 | ★★ 规划器 + ReAct 循环 | ★★ Agent Teams（实验） | ★★ 画布节点 | ★ 双 agent | ★★★ Pipeline/Team/SOP/SubAgent 多形态 |
| 人工审批 HITL | ★★★ interrupt + checkpoint | ★★★ 一等原语，任意时点暂停（v2 重写动机） | ★★ 权限审批 | ？（未确认） | ★★ permissions | ★★★ 双暂停 + AskUser + 规则持久化 |
| 自定义 HTTP 服务 | ★★★ 纯库自控 | ★ 单体应用 | ★★ SDK 可嵌 | ★★ BaaS，深度受限 | ★★★ serve + OpenAPI | ★★★ SDK 嵌入或 Service 开放边界 |
| 多用户隔离 | ★★ 自建 | ★ 无 | ★ 无（单用户） | ★★ 有 workspace，**许可证禁多租户** | ★ 无 | ★★★ 原生多租户（实测 404/409） |
| MCP 生态 | ★★ 适配器接入 | ★★★ 支持 + 自当 MCP server | ★★ 能力 seam | ★★★ 市场 + MCP | ★★★ MCP servers | ★★★ 框架内建 + Hub + 网关 |

## 1.4 结论：为什么是 AgentScope

六个框架其实是**四个物种**：编排库、应用（DeerFlow / OpenCode）、低代码平台、插件化运行时（DeepSeek Harness）。**选型错位比功能差距更致命**——用应用或平台做底座，最终都会和自研层打架。

- **LangGraph**：只选「编排库」时的最强替代（大概率路线是 LangGraph + 自写服务层），但服务层要全部自己长出来；
- **Dify**：许可证 + 架构冲突，出局；
- **DeerFlow / OpenCode / DeepSeek Harness**：不作底座，各吸收一点——DeerFlow 验证了「HITL 是常态而非异常」、OpenCode 的 OpenAPI 接口治理与只读分级、DeepSeek Harness 的事件溯源审计；
- **AgentScope**：五项需求全绿的唯一候选；代价（Python-only、月度迭代、分布式 WIP）在第三部分用防腐层（Anti-Corruption Layer，见 §3.5）对冲。

---

# 第二部分 AgentScope 框架能力

> 官方文档（2.0.9 中文版，https://docs.agentscope.io/zh/versions/2.0.9）的行文顺序就是本部分的顺序：核心模块（SDK 层）→ 智能体即服务（Service 层）→ API。

## 2.0 两层结构

- **SDK 层**：`Agent` 是无状态的 ReAct（Reasoning + Acting，推理-行动）循环，配模型、工具箱（Python 函数 / MCP / Skill）、消息和事件。`import agentscope` 组装，用的就是这一层。
- **Agent Service 层**（`create_app`）：SDK 外面包一层 HTTP 服务——多租户、工作区、凭证、Hub、调度。官方入口 `examples/agent_service/main.py`。

**已验证能力速览**（两种接法通用）：

| 能力 | 结论 | 备注 |
|---|---|---|
| 流式对话 | ✅ 发消息、收结果是**两个接口** | `POST /chat` 立即返回 `started`；回复从 `GET /sessions/{id}/stream` 订阅 |
| 多轮记忆 | ✅ | `AgentState` 按 session 持久化，续聊自动恢复；超窗口自动压缩 |
| 超时/重试 | 模型类内默认**重试 3 次、间隔 1 秒** | SDK 侧可改，API 无对应参数 |
| 主备模型 | ✅ 每条 session 最多两个模型 | fallback 可指向不同厂商的凭证 |
| 工具调用 | ✅ MCP、Skill | 都支持「直接挂载」和「Hub 安装」两条路（§2.4） |
| 用户隔离 | ✅ 跨用户访问别人的 session / agent → 404 | |
| 会话隔离 | ✅ 同用户多 session 互不知晓 | |
| 并发 | ✅ 多用户同时对话不串数据 | 同一 session 并发触发 → 409 |
| 集群部署 | ✅ 需 Redis 版 MessageBus（§2.6） | |

## 2.1 SDK 核心模块

### 2.1.1 消息与事件

**消息（Msg / ContentBlock）负责上下文与存储**——存数据库的、喂给大模型的就是它。一条 `Msg` 的 `content` 是一组内容块：

| 块类型 | 存什么 |
|---|---|
| `ThinkingBlock` | 模型的中间推理过程 |
| `ToolCallBlock` | 调用的工具名和参数 |
| `ToolResultBlock` | 工具执行后返回的数据 |
| `TextBlock` | 最终输出给用户的正文 |
| `DataBlock` | 图片、文件等多模态数据 |

工程意义：正文、工具调用、工具返回值结构化分开，后端组装 Prompt、前端渲染都按块取，不用从散文里切。

**事件（Event）负责流式输出**——`reply_stream()` 吐出连续事件（`ModelCallStartEvent` 思考中、`TextBlockDeltaEvent` 打字机、`ToolCallStartEvent` 工具标签），前端按事件类型渲染不同 UI 组件。

### 2.1.2 智能体：无状态的 ReAct 循环引擎

Agent 是纯粹的「消息处理节点」：输入消息 → 推理 + 工具调用 → 输出消息，**自己不存记忆**——正因如此，才能在每次请求时把数据库里的 `AgentState` 注入给它，实现多节点并发部署。

- 所有 Agent 用同一个 `Agent` 类，差别只在构造时注入的系统提示词和工具箱；**隔离是构造出来的**（挂空 Toolkit 就调不到任何工具）。
- 核心 API 两个：`reply()` 同步返回完整结果；`reply_stream()` 流式广播事件。`POST /sessions/{id}/interrupt` 可从外部打断运行中的回复。

### 2.1.3 模型：厂商解耦

基类 `ChatModelBase` 统一成「给消息、收 ChatResponse、流式增量」，Agent 只依赖基类；换厂商只换子类（OpenAI / Anthropic / Gemini / DashScope / DeepSeek / Ollama 等），**Agent 一层不用动**。默认重试 3 次、间隔 1 秒；session 级可配主模型 + fallback。

### 2.1.4 上下文管理：记忆工程

大模型绝对无状态，「记忆」都是 Agent 层的工程：静态配置（系统提示词、工具定义）绑定实例；动态记忆（问答、工具结果）托管于 `AgentState` 持久化。每次调模型前组装两路输入——`messages`（系统提示词 → 摘要 → 历史上下文）和 `tools`（Toolkit 生成的 JSON（JavaScript Object Notation，数据交换格式）Schema），不是拼一段大字符串。

**压缩**（默认 `ContextConfig`）：每次发给模型前预估 token——

```
estimated_tokens = 本次输入 + 历史整份 context + summary
threshold        = trigger_ratio（默认 0.8）× 模型最大窗口
保留额度          = reserve_ratio（默认 0.1）× 窗口   ← 超阈值触发压缩
```

从最新消息向老消息回溯保留近期原文，更旧的调模型提炼进 summary；分割线上的消息可**按 Block 精细截断**。**卸载（offload）**：被压缩的原文可整段写入工作区磁盘，摘要末尾留路径，模型可用读文件工具捞回原文。

### 2.1.5 工具：三种挂法

1. **Python 函数（FunctionTool）**：从签名和 docstring 自动生成工具说明；
2. **MCP**：`MCPClient` 登记进 `Toolkit(mcps=[...])`，命名空间 `mcp__{server}__{tool}`；有状态（stdio，标准输入输出）与无状态（HTTP）两种客户端；
3. **Skill**：不执行业务代码，是一份 SKILL.md 说明书，模型读全文后按要求输出。

另有元工具（内置 Bash / Grep / Read / Write / Edit 等）与沙箱工作区内的 MCP 网关。

### 2.1.6 流水线、权限与工作区（速览）

- **流水线**：GoalPipeline（目标导向 leader-worker）/ TeamPipeline（团队协作）；SDK 侧最轻的协同惯用法是把「调另一个 Agent」包成 FunctionTool 挂到 Leader 工具箱（§2.2 决策 3）。
- **权限模式五档**：

| 模式 | 设计意图 | 场景 |
|---|---|---|
| `DEFAULT` | 宁愿多问一次，也不直接放行 | 通用聊天，权限严格 |
| `ACCEPT_EDITS` | 授权目录内修改文件，不打断 | IDE 开发 |
| `EXPLORE` | 只读 | 调研、规划 |
| `BYPASS` | 信任环境全放行 | 隔离容器 / VM（风险最高） |
| `DONT_ASK` | 要确认的一律拒绝 | 定时任务，无人值守 |

  模式内部可配 `allow_rules / deny_rules / ask_rules`（工具名 + 过滤器 + 命中行为），从左向右先命中先生效。
- **工作区**：文件系统三档隔离（per_agent / per_session / per_user），沙箱支持本地 / Docker / E2B（云沙箱服务商）/ K8s（Kubernetes，容器编排平台）。
- **中间件**：七类挂点（reply / reasoning / acting / model / permission / 压缩 / 系统提示词）。
- **长期记忆**：官方 `AgenticMemoryMiddleware`（Markdown 落盘工作区），也接 ReMe / Mem0。

## 2.2 接法一：SDK 自建服务

案例：公开信息简报助手——大白话提问，Leader 调度「信息检索」（挂 MCP 搜索）、「情报提炼」（空工具箱）两个专家，产出带源链接的简报；后端 FastAPI + PostgreSQL（PG），自己的前端调 `/health` `/sessions` `/chat`。

**五个关键工程决策**：

| 决策 | 做法 | 解决什么 |
|---|---|---|
| 1. Agent 无状态 | 每次 HTTP 请求重建 team，注入从 PG 读回的 AgentState；请求结束丢掉 | 记忆在库里——刷新、切实例、重启都能续聊 |
| 2. 模型单例 | FastAPI lifespan 里建一次 `OpenAIChatModel`，全 Agent 共用 | 换模型只改一处 |
| 3. 编排 = FunctionTool 包函数 | Leader 不直接调专家，只点工具名 | SDK 侧最轻的多 Agent 协同 |
| 4. 同会话互斥 | `pg_try_advisory_lock` 按 session_id 加锁，抢不到 409 | 锁放 PG 上，多 worker / 多实例都看得见 |
| 5. SSE 只转两类事件 | 工具名 + 正文增量 | 内部事件（thinking 等）不泄漏给前端 |

组队代码骨架（节选）：

```python
model = OpenAIChatModel(          # 进程启动时建一次，所有 Agent 共用
    credential=OpenAICredential(api_key=..., base_url=...),
    model="chatling-plus",
    stream=True,
    client_kwargs={"timeout": 120.0},   # 超时/重试在这一层调
)
searcher = Agent(
    name="信息检索", system_prompt=_SEARCHER_PROMPT, model=model,
    toolkit=Toolkit(mcps=[tavily]),           # 空列表，不是 None
    react_config=ReActConfig(max_iters=1),
    state=with_bypass(rec.searcher_state),    # 从 PG 读回的 AgentState 注入
)
extractor = Agent(
    name="情报提炼", system_prompt=_EXTRACTOR_PROMPT, model=model,
    toolkit=Toolkit(),                        # 空的，调不到任何外部工具
    ...
)
leader = Agent(
    name="公开信息简报助手", model=model,
    toolkit=Toolkit(
        tools=[FunctionTool(ask_searcher), FunctionTool(ask_extractor)],
        skills_or_loaders=[str(_SKILL_DIR)],  # Skill 目录挂进工具箱
    ),
    react_config=ReActConfig(max_iters=12), ...
)
```

同一会话的请求生命周期（HTTP 层全部骨架）：

```
lock = await store.try_acquire_lock(session_id)   # pg_try_advisory_lock，抢不到 → 409
rec  = await load_or_create(session_id, user_id)  # 三份 AgentState 从 PG 读回
team = build_team(model, tavily, rec)             # 注入状态、组队
async for ev in team.leader.reply_stream(UserMsg(...)):
    ...   # ToolCallStartEvent → SSE {"type":"tool","name":"信息检索"}
    ...   # TextBlockDeltaEvent → SSE {"type":"text","delta":...}
rec.leader_state = team.leader.state              # 整份 AgentState 写回
await store.upsert(rec); await lock.release()     # 成功/失败/断开都要放
```

**现象 → SDK 组件对照**：

| 用户看到的现象 | SDK 对应物 |
|---|---|
| 界面弹出「信息检索」「情报提炼」标签 | `ToolCallStartEvent`，只推工具名 |
| 文字一条条蹦出来 | `TextBlockDeltaEvent` 转 SSE |
| 简报按固定章节排版 | Skill（SKILL.md），只给 Leader 挂载 |
| 第二句还记得历史 | `AgentState` 落 PG，续聊时读回注入 |
| 生成中再发一条 → 409 | `pg_try_advisory_lock` |
| 换模型只改一处 | 模型单例，Agent 与厂商解耦 |

**什么时候选 SDK**：已有网关/前端，只想挂三五个口，SSE 字段、鉴权流、落库结构自己定；代价是外壳（鉴权、会话、锁、流式转发、多实例总线）全自己写。

## 2.3 接法二：Agent Service（create_app + HTTP API）

启动：`create_app(storage=..., message_bus=..., workspace_manager=..., ...)` 三参必填（可选还有知识库、Hub、SubAgent 模板、消息渠道等）；`uv pip install agentscope[full]` 后跑 `examples/agent_service/main.py`，默认 8000 端口。**注意**：十几组 router 一次挂齐，只能整棵 mount，摘不下来——想只暴露几个接口或自定义 SSE 字段，走 §2.2 的 SDK 接法。

### 资源模型与身份

身份不是 cookie，是请求头 **`X-User-ID`**（缺头 401），所有资源按 user 隔离；**服务不自带鉴权**——`X-User-ID` 只是占位，生产上要换自己的 JWT / OAuth 中间件。

| 表 | 一行是什么 | 关键字段 |
|---|---|---|
| `credential` | 用户注册的模型凭证 | `credential_id`、payload（api_key、base_url） |
| `agents` | 用户建的一个 Agent | `agent_id`、payload（name、system_prompt、config） |
| `sessions` | 一条会话（一个 AgentState） | `agent_id`、payload（**config + state** 两部分） |
| `messages` | 按 session 存的聊天记录 | role、content 块、usage |
| `mcps` / `skills` | 用户安装的工具库 | name、hub 来源、enabled |
| `teams` | 多智能体小队 | 队内 leader / worker 关系 |

`sessions.payload` 更新节奏不同：`config`（workspace、会话名、主备模型）改配置才变；`state`（AgentState 运行态快照）**每轮对话结束整份更新**——`messages` 只做历史展示，**续聊的短期记忆只靠 `state`**。

### 五步跑通第一轮对话

```bash
BASE=http://127.0.0.1:8000; USER_ID=eval-user-1

# ① 注册凭证（之后请求只引用 credential_id）
curl -sS -X POST "$BASE/credential/" -H "Content-Type: application/json" -H "X-User-ID: $USER_ID" \
  -d '{"data":{"type":"openai_credential","api_key":"$KEY","base_url":"$BASE_URL"}}'
# 201 → {"credential_id": "0441ce22…"}

# ② 创建 Agent（context_config/react_config/invite_config 不传有默认值）
curl -sS -X POST "$BASE/agent/" -H "Content-Type: application/json" -H "X-User-ID: $USER_ID" \
  -d '{"name":"CloudAgent1","system_prompt":"You are a concise assistant."}'
# 201 → {"agent_id": "a2d6fa18…"}

# ③ 创建 Session（挂上主备模型）
curl -sS -X POST "$BASE/sessions/" -H "Content-Type: application/json" -H "X-User-ID: $USER_ID" \
  -d '{"agent_id":"$AGENT_ID","name":"eval-session-1",
       "chat_model_config":{"type":"openai_chat","credential_id":"$CRED_ID",
                           "model":"chatling-plus","parameters":{"temperature":0.4}},
       "fallback_chat_model_config":{"type":"openai_chat","credential_id":"$CRED_ID",
                           "model":"chatling-turbo","parameters":{}}}'
# 201 → {"session_id": "9728c621…"}

# ④ 先订阅（SSE），再发消息
curl -N "$BASE/sessions/$SESSION_ID/stream?agent_id=$AGENT_ID" -H "X-User-ID: $USER_ID"

# ⑤ 触发对话
curl -sS -X POST "$BASE/chat/" -H "Content-Type: application/json" -H "X-User-ID: $USER_ID" \
  -d '{"agent_id":"$AGENT_ID","session_id":"$SESSION_ID",
       "input":{"name":"zhangsan","role":"user",
                "content":[{"type":"text","text":"用一句话介绍你自己"}]}}'
# 200 → {"status": "started"}   ← 正文从 ④ 的订阅口以事件流吐出
```

换一个 `X-User-ID` 查同一 session → 404（用户隔离）；同一 session 生成中再 POST → 409（会话互斥）。

### SSE 事件速查

一轮回复的事件序列：`REPLY_START → HINT_BLOCK → MODEL_CALL_START → TEXT_BLOCK_START → TEXT_BLOCK_DELTA … → TEXT_BLOCK_END → MODEL_CALL_END → REPLY_END`

| 事件 | 含义 | 前端用途 |
|---|---|---|
| `REPLY_START` | 一轮回复开始（带 reply_id） | 清空缓冲、显示「思考中」 |
| `HINT_BLOCK` | 系统注入的提示块（当前时间等） | 一般不渲染 |
| `MODEL_CALL_START/END` | 一次模型调用的起止（带模型名 / token 用量） | 思考中 / 用量统计 |
| `TEXT_BLOCK_START/DELTA/END` | 正文块的生命周期 | 打字机效果 |
| `TOOL_RESULT_TEXT_DELTA` | 工具结果文本增量 | 工具结果预览 |
| `REPLY_END` | 整轮结束（带 finished_reason、error） | 收尾、解锁输入框 |

命名规律：`*_START/_DELTA/_END` 是块的生命周期，`MODEL_CALL_*` 是一次推理调用；ReAct 多轮迭代时 `MODEL_CALL_*` 出现多次；事件按 `reply_id` 聚成一轮。

## 2.4 工具接入（API）

MCP 和 Skill 同一个模式：**先到用户的库（mcps / skills 表），再挂到某个 agent 的 workspace**。「入库」两条路：直接注册 / 从 Hub 安装。

**MCP 直接注册挂载**（写进该 agent 的 workspace，同 agent 所有 session 共用）：

```bash
curl -sS -X POST "$BASE/workspace/mcp?agent_id=$AGENT_ID&session_id=$SESSION_ID" \
  -H "Content-Type: application/json" -H "X-User-ID: $USER_ID" \
  -d '{"name":"meerflow-demo","is_stateful":false,
       "mcp_config":{"type":"http_mcp","url":"http://127.0.0.1:8080/mcp"}}'   # 201
```

`is_stateful`：HTTP 型常为 false，stdio 型必须 true。挂载后 `GET /workspace/mcp` 可查工具列表（含健康检查）。

**从 Hub 安装**（三步）：`GET /hub/mcp/{hub}/cards` 浏览卡片 → `POST /hub/mcp/{hub}/cards/{card_id}/install` 装进用户 mcps 表 → `POST /workspace/mcp/from-library {"mcp_ids":[...]}` 挂到 workspace。Hub 源可插拔（官方带 GitHub、Claw 两个源，可自建）。

**Skill**：直接上传走 `POST /workspace/skill/upload`（multipart，manifest 先声明再传 files，只落 workspace 不进 skills 表）；从 Hub 走 `POST /hub/skill/{hub}/cards/{name}/install` → `POST /workspace/skill/from-library {"skill_ids":[...]}`。Skill 不执行代码，模型读 SKILL.md 后按约定格式输出。

## 2.5 多智能体（API）

框架内置团队工具：`TeamCreate` / `AgentCreate` / `AgentInvite` / `TeamSay` / `TeamDelete`，队长 Agent 在 ReAct 里调它们完成协同。两种组队形态：

**形态一：SubAgent（模板造人）**。模板在 `create_app` 的 `custom_subagent_templates` 注册（运维侧，改模板要重启）；队长按模板描述选型，`AgentCreate` 造队员——每个队员独立 session、独立上下文，**共用队长的 workspace、继承队长的模型配置**；subagent 不允许再嵌套创建 subagent；用完即删（`TeamDelete` 后 teams / sessions / messages 一并清理），不进用户 agent 列表。

**形态二：常驻专家（AgentInvite 邀请）**。专家是用户自建的普通 agent，只是开了邀请配置：

```bash
curl -sS -X POST "$BASE/agent/" -H "Content-Type: application/json" -H "X-User-ID: $USER_ID" \
  -d '{"name":"FrontendSpecialist",
       "system_prompt":"你是前端专家。只从 UI/交互/性能角度给建议。完成后用 TeamSay 向队长汇报一次后停止。",
       "react_config":{"max_iters":15},
       "invite_config":{"invitable":true,
         "invite_description":"前端专家：页面结构、交互、Web 性能；适合拆「前端」切片。"}}'
```

给每个专家建一个**自用主 session**（挂模型，供邀请时继承）——有主 session 时队内交流的新建 session 优先复用专家的 workspace 和模型配置；没有则新建 workspace、模型配置用队长 session 的。团队解散只清这次团队相关的队内记录，专家自身的 agent / session / message 保留。

| | SubAgent | 常驻专家 |
|---|---|---|
| 用户建什么 | 只建队长；模板由 main.py 注册（运维侧） | N 个可邀请 agent + 各自主 session + 1 个队长 |
| 队长用的工具 | `TeamCreate` + `AgentCreate(subagent_type=…)` | `TeamCreate` + `AgentInvite` |
| 队员配置来源 | 模板（含权限、react、人设模板） | 专家 agent 自身 + 主 session |
| 模型配置 | 继承队长 | 有主 session 用自己的，否则用队长的 |
| 团队解散后 | 队员相关 teams/sessions/messages 全清理 | 只清队内记录，专家自身数据保留 |

**实测坑**：队长提示词要写死流程约束——成员「只 TeamSay 一次后停止」、队长「禁止对成员 TeamSay（会互唤醒）」「汇总完成前不要 TeamDelete」。不写会导致队员互唤醒、队长抢活自己写。

## 2.6 集群部署（Redis MessageBus）

单进程用内存总线；**多实例必须换 `RedisMessageBus`**——对话原生拆成两个接口、工具可能很慢、队员可能落在别的实例上。Redis 同时承担三件事：跨实例互斥锁、SSE 事件流转发、唤醒队列。两个核心队列：`inbox(sid)`（存放该 session 的慢工具结果 / 队员汇报）、`trigger(sid)`（就绪队列，可被**任意实例**的 WakeupDispatcher 抢占执行）。

- **跨实例对话**：订阅在 S1、POST /chat 落在 S3 → S3 后台拿 Redis 锁 `session:lock:{sid}` 执行（避免双跑）→ 事件经 Redis 转发 → S1 收到推给用户。
- **慢工具转后台**：工具超时（默认 10 秒）先返回占位、本轮正常结束 → 后台跑完 → 结果写 `inbox(sid)`、sid 进 `trigger(sid)` → 某实例的 WakeupDispatcher 抢到 → 新一轮执行，模型看到工具结果再回答。
- **多 agent 协同**：队长把 3 个队员任务推进各自 `trigger` → S1/S4/S5 各自抢占执行 → 结果写回 `inbox(队长sid)` + `trigger(队长sid)` → 队长再被唤醒汇总。

## 2.7 两种接法怎么选

| | SDK 自建 | Agent Service API |
|---|---|---|
| HTTP | 自己写几个口 | 十几组 router 一次挂齐；流在 session 接口不在 chat |
| 记忆 | 自己接 AgentState 落库 | 框架按 session 装配，storage 配什么存什么 |
| 同会话互斥 | 自己加锁（pg_try_advisory_lock → 409） | 框架自带；集群下 Redis 锁 |
| 工具挂载 | 构造 Agent 时挂 Toolkit（代码里） | API 注册到 workspace / Hub 安装（运行时） |
| 多智能体 | FunctionTool 包函数（同进程 await） | TeamCreate / AgentCreate / AgentInvite（可跨实例） |
| 多实例 | 总线和锁自己接 | RedisMessageBus + WakeupDispatcher 现成 |
| 模型管理 | 代码里初始化 | credential 表 + session 级主备模型 |
| 前端 | SSE 字段自己定 | 事件类型框架定，配官方 Web UI 最省事 |

**选 API**：要多租户、运行时动态组队、集群部署，或直接配官方 Web UI。**不选 API**：已有网关只想挂三五个口、流式路径和鉴权流要自己定。两条路不互斥——先用 API 快速验证业务形态，需要深度定制时再把编排逻辑沉到 SDK 层重写外壳。**第三部分就是这条路的全尺寸实践：运行时保持官方 Service 形态不动，平台能力全部外置到自研编排层。**

---

# 第三部分 软件造价评估平台实践

## 3.1 平台要做什么

用 6 个智能体覆盖软件造价评估的**全生命周期**，每个阶段一个智能体、一份产物、一道人工审批：

```
┌────────┐   ┌────────┐   ┌──────────┐   ┌────────┐   ┌────────┐   ┌─────────┐
│①需求生成│──▶│②原型设计│──▶│③工时预算  │──▶│④测试用例│──▶│⑤测试    │──▶│⑥验收审计 │
│ 智能体  │审 │ 智能体  │审 │ 罗盘智能体│审 │ 智能体  │审 │ 智能体  │审 │ 智能体   │
└────────┘批 └────────┘批 └──────────┘批 └────────┘批 └────────┘批 └─────────┘
   PRD         原型         功能点清单/      用例文档      测试报告      结算/审计
              (HTML等)      预算表                       (功能+单元)    汇总报告
              ▲             ▲                                          ▲
              └──── 人工审批不通过则退回当前阶段修订（可多轮）──────────────┘
```

（图取自 `platform-design/architecture.md` §1；HTML（HyperText Markup Language，超文本标记语言））

两类用户两种形态：项目经理 / 审批人 / 审计走**项目生命周期视图**（类禅道），需求提出者 / 开发走 **Agent 工作台**（类聊天三栏）。银行审计级留痕：谁审批的、什么意见、哪个版本有效，都要可查。

## 3.2 总体架构与三条铁律

```
┌──────────────────────────────────────────────────────────────────────┐
│ 前端 SPA（React 19 + Vite，一套代码、两个视图）                          │
│  ┌───────────────────────────┐    ┌─────────────────────────────────┐ │
│  │ 视图A·项目生命周期(类禅道)    │    │ 视图B·Agent工作台(类WorkBuddy三栏)│ │
│  │ 看板/详情/时间线/审批/版本链  │◀──▶│ 左:项目上下文 中:对话 右:产物预览  │ │
│  └───────────────────────────┘    └─────────────────────────────────┘ │
└───────────────────────────────┬──────────────────────────────────────┘
                        HTTPS/JWT│  前端只对接业务编排层（BFF 模式）
┌───────────────────────────────▼──────────────────────────────────────┐
│ 业务编排层 platform-backend（自研 FastAPI）——平台的"控制面"               │
│  用户/组/RBAC · 项目管理 · 阶段状态机 · 审批任务 · 产物版本链              │
│  知识库授权 · 项目档案(跨阶段记忆) · SSE 透传 · 文档导出(docx/xlsx)        │
│  业务库: PostgreSQL                                                   │
└──────┬──────────────────────────────────────────┬────────────────────┘
       │ HTTP（X-User-ID: sys:runtime）             │
┌──────▼──────────────────────────────────────────▼────────────────────┐
│ 智能体运行时层 agentscope-service（AgentScope）——平台的"执行面"          │
│  6×阶段智能体(AgentRecord) · 会话/上下文压缩 · 工具/技能/MCP             │
│  RAG 检索 · 项目 Workspace(产物落盘) · 长期记忆中间件 · SSE 事件流        │
└──────┬───────────────┬───────────────────┬──────────────┬─────────────┘
       │               │                   │              │
 ┌─────▼─────┐  ┌──────▼──────┐  ┌─────────▼─────┐  ┌─────▼─────────┐
 │ PostgreSQL │  │ Redis       │  │ Qdrant        │  │ 模型服务        │
 │ 会话/智能体  │  │ 消息总线/分布式锁│  │ 向量检索(每KB一库)│  │ vLLM / 智谱GLM │
 │ 记录存储     │  │             │  │               │  │ (OpenAI/Anthropic兼容)│
 └───────────┘  └─────────────┘  └───────────────┘  └───────────────┘
                 MinIO/S3：知识库文档原文 + 产物归档
```

（图取自 `platform-design/architecture.md` §2。图中缩写：SPA = Single-Page Application 单页应用；JWT = JSON Web Token 令牌；BFF = Backend for Frontend 面向前端的后端聚合层；RBAC = Role-Based Access Control 基于角色的访问控制。）

**三条铁律**（所有设计从这三条推导）：

1. **控制面与执行面分离**——业务流程（谁审批 / 走到哪步 / 哪个版本有效）用数据库 + 状态机解决，不塞进 Agent 自治协作；
2. **AgentScope 不直接面向最终用户**——鉴权 / 授权 / 审计 / 租户隔离全部收敛在编排层，运行时退居内网当「智能体引擎」；
3. **平台用户体系与运行时主体解耦**——运行时只看到 `sys:runtime` 一个主体（会话按主体隔离，挂服务主体后「谁能看哪个会话」由编排层判断透传，可见性规则只有一个真相来源）。

部署：仓库根 `start.sh` 六步拉起——PostgreSQL:5432 → Redis:6380（6379 被本机其它服务占用）→ AgentScope 运行时:8000 → 调试用 Web UI:5173 → L1 编排层:8100 → 平台前端:5174（★ 平台入口）。组件全部外置，本地各一副本即「伪多实例」。

## 3.3 文档先行：architecture.md

`platform-design/architecture.md`（v0.5）**先于全部实现代码完成**，git 历史佐证：首条平台提交就是设计文档，之后按 L1 骨架 → JWT + 状态机 → 防腐层 + 阶段会话 → HITL 透传 → 两视图前端 → 运行时入口独立的顺序推进。三个含义：

- **诚实的差距清单**：逐项列「AgentScope 已有 ✅ vs 平台需自建 ❌」——文档导出（docx / xlsx）、组级权限、业务流程 / 审批明确自建，不把不存在的能力当依赖；
- **决策记录驱动**：已决策 + 待定项分列（如废弃「每项目克隆智能体」改全局共享、测试沙箱定为阶段运行级），修订日志记录方案演化；
- **路线图可演示**：M1 骨架端到端 → M2 六阶段闭环 → M3 知识库 → M4 记忆沉淀 → M5 部署形态。

## 3.4 运行时层：只动「组装三件套」

`examples/platform_agent_service/` 派生自上游 `examples/agent_service/`——**上游保持零改动**方便随官方同步，平台差异全部收敛在本目录。与上游逐行 diff 后，`create_app` 的组件清单完全一致，差异只有三处，全部环境变量可覆盖：

| # | 改动 | 上游 | 平台 | 支持什么 |
|---|---|---|---|---|
| 1 | 存储 | `RedisStorage`（内存态） | `AsyncSQLAlchemyStorage` → PG 库 `agentscope` | 持久落盘、可审计、多实例共享；换目录启动不丢数据 |
| 2 | 消息总线 | `InMemoryMessageBus`（单进程） | `RedisMessageBus` | 多副本部署；分布式会话锁（并发 409）+ SSE 事件回放 |
| 3 | 下载签名密钥 | 无 | `download_secret` 固定值 | 重启后签名 URL 仍有效；多实例共享校验 |

**平台能力不是靠改框架实现的，而是靠「独立目录 + 组装参数」实现的**；上游有值得跟进的改动时手工 cherry-pick（README 里的同步纪律）。

## 3.5 编排层：四个自建机制

L1 是自研 FastAPI（`platform/backend/`），依赖仅 9 个包、**不 import agentscope**、独立 venv。四个机制各解决一个 AgentScope 没有原生覆盖的问题：

| 机制 | 解决什么 | 核心做法 |
|---|---|---|
| **JWT 鉴权** | 多租户用户体系（框架只有 X-User-ID 占位） | scrypt 口令哈希 + PyJWT HS256（HMAC-SHA256 签名算法）；注册自动入 default 组；运行时永远只见 `sys:runtime` |
| **stage-flow 状态机** | 长周期流程的可审计编排（框架只有会话内编排） | 两级状态机（项目级 + 阶段运行级），唯一实现收敛在 `flow.py` 约 200 行，替代 BPMN（Business Process Model and Notation，业务流程建模标记）引擎 |
| **runtime 防腐层** | 开源框架升级兼容 | `runtime_client.py` 是全平台唯一访问运行时的模块，8 个类型化操作，刻意收窄的出口 |
| **两视图前端** | 两类用户、两种工作形态 | 项目生命周期（ProjectDetail）+ Agent 工作台（Workbench 三栏），从官方 web_ui 一次性收割改造 |

关键细节：

- **状态机三重守卫**：阶段必须按序串行、同阶段不允许并存活跃 run、已 approved 不可重开；非法转移抛 `FlowError` → 409/400。三张核心表：`stage_runs`（round 记退回轮次）、`approval_tasks`（审批留痕，审计核心表）、`artifact_versions`（产物不可变版本链）。
- **防腐层三红利**：① 上游改接口只改这一个模块；② 传输失败统一映射 503/502（`RuntimeCallError` 与业务 `FlowError` 同构，API 层统一翻译）；③ `list_credentials` 丢掉原始 api_key 只回 id/name/type——安全投影，key 永不落 L1。防腐层（Anti-Corruption Layer，ACL）是领域驱动设计（DDD，Domain-Driven Design）的经典模式：在自己模型与外部系统之间放一层翻译，防止外部系统的变更渗透进内部模型。
- **自愈设计**：`ensure_stage_session` 懒创建会话 + 每次发消息前 PATCH 模型配置——运行时不可用时阶段照常开启，凭证后配也能自愈。
- 前端 M1 用轮询而非 SSE 透传（智能间隔：运行中 1.5s，否则 4s），SSE 是 M2 待办。

## 3.6 六智能体与两层 HITL

### 全局共享智能体

6 个阶段智能体**全局共享、挂在 `sys:runtime` 名下**，项目创建时零智能体创建（废弃了「每项目克隆」方案）。安全性由机制保证：`AgentState` 属于 Session 而非 Agent，**同一智能体开 N 个会话互不污染**——「定义共享、状态随会话」。智能体由 `scripts/seed.py` 幂等播种，6 个全部就位（需求分析提示词约束：三轮澄清提问、FR（Functional Requirement，功能需求）编号 + 优先级、不臆造需求、保留用户原话）。

### 两层 HITL，互不替代

**微观：对话内工具确认**（复用 AgentScope 原生权限暂停）：

```
工具调用命中 ASK → 运行时挂起 reply，tool_call 置 asking
  → 前端 Workbench 弹出确认条（逐个工具名）
  → 用户点「允许/拒绝」→ POST /stage-runs/{id}/confirm
  → L1 鉴权后经防腐层回执 → 运行时恢复挂起的 reply
```

**宏观：阶段产物审批**（L1 自建状态机，银行审计要求）：

```
对话满意后点「提交产物送审」
  → 产物落盘 artifacts/{project_id}/{stage}/runN-vM.md（不可变版本链）
  → run: in_progress → under_review，建 approval_tasks（审批人 = 项目首个 APPROVER 角色成员，缺省负责人自审；移除成员时其在途待审任务自动改道给负责人）
审批人在「审批中心」裁决
  → 通过：run 置 approved；非最后阶段自动推进 project.current_stage
  → 退回：必须填意见，run 置 returned
重新协作 → 再开同阶段新 run，round+1，退回意见随 kickoff 注入
```

为什么审批不放会话里：流程横跨数月、数百次人机交互，状态必须落在持久化数据库而非会话上下文；审批人 / 意见 / 版本锁定是业务数据不是对话内容；Agent 无状态可重跑，流程状态永不依赖某个会话是否存活。

## 3.7 数据落点：工作区草稿 vs 权威归档

- **工作区 = 过程草稿**：`examples/platform_agent_service/workspaces/{agent_id}/` 下，长期记忆中间件 + 智能体自己写的文件（真实样例：两轮问卷澄清记录逐条保留用户原话、PRD 每条 FR 标注来源 R1-xx / R2-xx、跨会话项目记忆为下阶段接力铺垫）；
- **artifact_versions = 权威归档**：提交送审时定格的不可变版本链。

丢了工作区可从归档恢复；工作区是智能体的工作记忆，归档是业务的事实源。

## 3.8 当前状态与路线图

**M1 已完成**（backend 进度清单全勾）：组织模型、项目模型、JWT 登录（含登录页自助注册）、阶段状态机、防腐层 + 阶段会话自愈、6 个阶段智能体播种、负责人 / 审批人双视角（审批中心收件箱 + 产物预览审批 + 成员管理）、阶段技能包（测试用例阶段自动装 7 法：等价类 / 边界值 / 判定表 / 场景法 / 状态迁移 / 正交配对 / 错误推测）、移除成员在途审批自动改道。已通的端到端流程：注册 → 登录 → 建项目 → 加审批人成员 → 启动阶段 → 对话（HITL 工具确认）→ 提交送审 → 审批人审批 → 自动推进下一阶段 → 已完成阶段只读回看。

**M2–M5 待办**：SSE 透传（现为轮询）、契约测试、知识库组授权、测试沙箱（Docker）、docx / xlsx 导出、记忆沉淀闭环、K8s 多实例部署。

---

# 参考资料

- **AgentScope**：https://github.com/agentscope-ai/agentscope ｜ 文档 https://docs.agentscope.io/zh/versions/2.0.9 ｜ 本仓库 `examples/agent_service/`、`examples/web_ui/`
- **LangGraph**：https://github.com/langchain-ai/langgraph ｜ DeepAgents：https://github.com/langchain-ai/deepagents
- **DeerFlow**：https://github.com/bytedance/deer-flow ｜ https://deerflow.tech
- **DeepSeek Harness**：https://github.com/deepseek-ai/deepseek-harness ｜ Cordis：https://github.com/cordiverse/cordis
- **Dify**：https://github.com/langgenius/dify ｜ https://docs.dify.ai
- **OpenCode**：https://github.com/anomalyco/opencode ｜ https://opencode.ai
- **平台设计**：本仓库 `platform-design/architecture.md`（v0.5）
