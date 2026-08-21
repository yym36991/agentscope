# 公开信息简报助手 — 组内技术分享

面向同组开发。目标不是讲前端，也不是把 `create_app` 当全部内容。
**主线：同一件事，先用 SDK 自己拼一个后端，再对照 Agent Service 看框架替你干了什么。**

配套代码：`sdk_briefing.py`（纯 SDK + 薄 FastAPI）。演示产品仍用现成 Web UI + `main.py`。

建议时长 **45–60 分钟**（演示 8 分钟 + SDK 30 分钟 + create_app 对照 10 分钟 + 问答）。

---

## 0. 这场分享怎么讲

不要按「先介绍框架、再介绍产品」的顺序。同学会在前 10 分钟走神。

推荐顺序：

| 段 | 讲什么 | 为什么这样排 |
|---|---|---|
| 1 | 打开浏览器，问一句真实问题 | 领导要的是**使用场景**，先让大家看见交付物 |
| 2 | 把刚才那次对话拆成积木 | 从现象回到概念，每个概念都对应刚才发生过的事 |
| 3 | **用 SDK 把积木重新拼成一个服务**（主讲） | 同学以后写自己的助手，走的是这条路 |
| 4 | 对照 `create_app`：多用户、会话、团队工具、打开即用 | 说明「产品形态」和「会用 SDK」不是一回事 |
| 5 | 什么时候手写 SDK、什么时候直接 create_app | 给选择，避免「只会调工厂函数」 |

一句话定调：

> AgentScope 是两层。底下是 **SDK**（`Agent` / 模型 / 工具 / 记忆），你用 Python 组合；上面是 **Agent Service**（`create_app`），把同一套积木做成多用户 HTTP 应用。今天这个助手两条路都能做，**开发同学必须会底下那层。**

---

## 1. 使用场景：公开信息简报助手（演示）

给市场、产品、运营、HR 用的 **公开检索 + 摘要**。用户打开浏览器选「公开信息简报助手」，大白话提问，拿到一份带来源链接的简报。

不限定竞品。公司动态、行业新闻、招聘口径、政策原文、财报披露、召回公告，只要搜索引擎能打开，都走这一个入口。

```
用户 ──► Leader【公开信息简报助手】
          多轮澄清：查谁、查哪几面、查多久、用来干什么
            ① 信息检索：公开网页 + 链接
            ② 情报提炼：要点 / 变化点 / 影响
          Leader 按模板汇总 → 简报
```

**专家由 admin 预先配好**，普通用户不创建智能体、不贴 API Key。前端用现成 Web UI 即可，改不改都行。

### 现场试问（建议现场跑两条）

信息不全，用来看 Leader 会不会真的停下来问：

```
帮我看看贝壳找房最近在租房这块有什么动静。
```

四要素齐全，用来看会不会跳过澄清直接干：

```
上海这轮租赁指导价和核验新规，公开文件里怎么写的，近三个月，给产品内部参考。
```

其它角度（时间不够就口头举，不必全跑）：产品功能更新、舆情点名、校招口径、季报披露、竞品套餐价。不问：这段文案能不能对外发、改简历、规划行程——那不是检索+摘要。

### 演示时点一下即可、不要展开的

- 前端：现成界面，admin 把 Leader + 两位专家配好，共享给全员。
- 用户只跟 Leader 聊。专家是花名册，按需被拉进来。
- 报告末尾有免责：公开信息汇总，不是经营决策依据。

---

## 2. 先建立分层，再往下钻

```
┌─────────────────────────────────────────────┐
│  现成 Web UI（examples/web_ui）               │  ← 今天不当重点
├─────────────────────────────────────────────┤
│  Agent Service：create_app(...)               │  ← 对照讲，约 10 分钟
│  多用户 / 会话 / SSE / Team 工具 / 共享策略    │
├─────────────────────────────────────────────┤
│  SDK：Agent + Model + Toolkit + Msg + ...     │  ← 主讲
│  你自己决定谁调用谁、谁挂什么工具、HTTP 怎么包  │
└─────────────────────────────────────────────┘
```

`create_app` 很简单，是因为它把上半截都写好了。作为开发，如果只讲这一句，同学出去还是不会用 AgentScope。

下面整节都用「公开信息简报」当例子，不另换场景。

---

## 3. 【主讲】用 SDK 构造这个后端

思想：把刚才浏览器里发生的事，改成 **你自己写的 Python**。不经过 `create_app`，也能变成一个 HTTP 服务。

跑起来：

```bash
cd examples/local_eval
set -a && source .env && set +a
python sdk_briefing.py
# http://127.0.0.1:8100/docs
```

### 3.1 积木地图（对着刚才的演示指）

| 刚才演示里发生的事 | SDK 对应物 | 本助手怎么用 |
|---|---|---|
| 选了 ChatLing，开始生成 | `OpenAICredential` + `OpenAIChatModel` | 公司网关，OpenAI 兼容 |
| Leader 边想边问、专家去搜 | `Agent` = ReAct 循环 | 三个 `Agent` 实例，提示词不同 |
| 用户一句话、模型一段回复 | `UserMsg` / `Msg` | 进出都是消息，不是裸字符串 |
| 检索专家真的去搜了网页 | `Toolkit` + `MCPClient` | 只给检索专家挂 Tavily |
| 简报按固定结构排 | Skill（`SKILL.md`） | 只给 Leader 挂 `intel-report` |
| 同一会话里记得你刚说的时间范围 | `AgentState`（短期上下文） | 每个会话一个 Leader 实例 |
| 对话太长被摘要 | `ContextConfig` | 框架自动压，一般不用手写压缩 |
| 不让提炼专家去搜 | 构造时就不给它 MCP | SDK 里这是构造问题，不是事后拦截 |
| 浏览器里一条条字蹦出来 | `agent.reply_stream()` → Event | 自己用 SSE 推到前端 |

讲到这里停一下：**同学要带走的不是类名表，是「每个现象都能在 SDK 里找到一个对象」。**

### 3.2 模型：先接通 ChatLing

SDK 不帮你「注册凭证到数据库」。你在进程里把模型和 Key 构造出来：

```python
from agentscope.credential import OpenAICredential
from agentscope.model import OpenAIChatModel

credential = OpenAICredential(
    api_key=os.environ["CHATLING_API_KEY"],
    base_url=os.environ["CHATLING_BASE_URL"],  # 公司网关
)
model = OpenAIChatModel(
    credential=credential,
    model=os.environ.get("CHATLING_MODEL", "chatling-plus"),
    stream=True,
    client_kwargs={"timeout": 120.0},
)
```

要点：

- 换模型 = 换 `ChatModel` 实现（DashScope / Anthropic / OpenAI…），`Agent` 代码不用动。
- `stream=True` 才能在 `reply_stream` 里拿到字增量。
- Agent Service 里同一件事被拆成「先 POST /credential，再写进 session」——因为要多用户、要落库、接口还得掩码。SDK 脚本没有这些需求，构造出来就能用。

### 3.3 最小 Agent：一个会思考、会调工具的循环

```python
from agentscope.agent import Agent, ReActConfig
from agentscope.message import UserMsg
from agentscope.permission import PermissionContext, PermissionMode
from agentscope.state import AgentState
from agentscope.tool import Toolkit

agent = Agent(
    name="信息检索",
    system_prompt="你只负责搜索公开网页，整理成带链接的条目。",
    model=model,
    toolkit=Toolkit(mcps=[tavily]),   # 下面细讲
    react_config=ReActConfig(max_iters=12),
    state=AgentState(
        permission_context=PermissionContext(mode=PermissionMode.BYPASS),
    ),
)

reply = await agent.reply(UserMsg(name="user", content="贝壳近三个月租房功能更新"))
print(reply.get_text_content())
```

`Agent` 内部就是 ReAct：想一步 → 调工具 → 看结果 → 再想，直到不再调工具或达到 `max_iters`。

给同学的记忆法：

- **system_prompt** = 这个角色是谁、不许干什么
- **toolkit** = 它手里有什么
- **state** = 它记得什么（含本轮对话）
- **model** = 它用哪颗脑子

三个专家就是三次 `Agent(...)`，差别几乎只在这四项。

演示服务里权限选 `BYPASS`，否则 MCP 可能停下来等人点确认——控制台有 HITL，自己写的 HTTP 服务没有那套卡片。

### 3.4 工具有三种，别混

这是最容易讲混的一块。对着本助手拆：

| 种类 | 是什么 | 本助手谁用 |
|---|---|---|
| **Python 工具** `FunctionTool` / `ToolBase` | 你写的函数，模型按 JSON schema 调用 | Leader 的「去问检索专家」「去问提炼专家」 |
| **MCP** `MCPClient` | 外部标准工具服务，启动时拉工具列表 | 只有信息检索挂 Tavily |
| **Skill** `SKILL.md` | 给模型看的说明书，不是 RPC | 只有 Leader 挂报告模板 |

#### Python 工具：把另一个 Agent 变成函数

SDK 里没有 `TeamSay`。团队协作可以是普通函数：

```python
from agentscope.tool import FunctionTool, Toolkit

async def ask_searcher(task: str) -> str:
    """把检索任务派给信息检索专家。写清对象、维度、时间范围。"""
    msg = await searcher.reply(UserMsg(name="leader", content=task))
    return msg.get_text_content() or ""

async def ask_extractor(material: str) -> str:
    """把检索条目交给情报提炼。不要让它自己去搜。"""
    msg = await extractor.reply(UserMsg(name="leader", content=material))
    return msg.get_text_content() or ""

leader_toolkit = Toolkit(
    tools=[FunctionTool(ask_searcher), FunctionTool(ask_extractor)],
    skills_or_loaders=["demo_skills/intel-report"],
)
```

模型看到的是两个工具名 + docstring。Leader 决定何时调用、传什么。**编排权在模型，执行权在你的函数。**

这和 Agent Service 的 `AgentInvite` / `TeamSay` 是同一类事：都是「Leader 调工具，工具去叫醒另一个智能体」。差别是 Service 把建队、会话、跨进程唤醒都做了；SDK 里你自己 `await other.reply(...)`。

#### MCP：搜索不要自己写爬虫

```python
from agentscope.mcp import MCPClient, HttpMCPConfig

tavily = MCPClient(
    name="tavily",
    is_stateful=False,
    mcp_config=HttpMCPConfig(
        url=f"https://mcp.tavily.com/mcp/?tavilyApiKey={key}",
    ),
)
searcher_toolkit = Toolkit(mcps=[tavily])
```

HTTP MCP 无状态，不必 `connect()`。挂上之后模型能调 `tavily_search` 等工具，和调 `FunctionTool` 看起来一样。

**必讲的对比：**

- SDK：检索专家的 `Toolkit(mcps=[tavily])`，提炼专家的 toolkit 里根本没有搜索。职责隔离是构造出来的。
- `create_app`：`default_mcps` 会种进**每个**工作区，邀请出来的专家也会看见 Tavily，所以才需要 `IntelHandoffMiddleware` 把非检索专家的 `tavily_*`  comp掉。这不是 SDK 的锅，是「默认配置图省事」的代价。

#### Skill：报告长什么样，写成文件而不是写死在提示词里

`demo_skills/intel-report/SKILL.md` 规定简报的章节和免责口径。Leader 的 toolkit 传入该目录即可。改排版改文件，不用改 Python。

和 MCP 的区别：Skill 是**给模型读的方法**；MCP 是**给模型调的接口**。

### 3.5 记忆：这次演示只用短期

| 层 | 本助手 | 同学以后什么时候才需要 |
|---|---|---|
| 一轮回复内的工具结果 | ReAct 自动放进上下文 | 默认就有 |
| 同一会话多轮澄清 | 同一个 `Agent` 实例的 `state` | 多轮对话都要 |
| 窗口快满时压缩 | `ContextConfig`（默认约 80% 触发） | 长会话 |
| 跨会话记住用户偏好 | 长期记忆中间件（Mem0 / ReMe） | **本次明确不用** |

讲法：用户第一句只说「看看贝壳」，第二句补「近三个月、做周报」——Leader 能接上，是因为还是那个 Agent 对象。`sdk_briefing.py` 用 `session_id` 映射到同一个 Leader。换一个 session_id 就是另一段对话，互不影响。

Agent Service 把这套 state 序列化进 PostgreSQL，所以换一台机器还能续聊。SDK 示例存在进程内存里，重启就没了——**这正好用来讲「服务化多出来的是持久化，不是智能本身」。**

### 3.6 中间件：改行为，不改 Agent 源码

七个钩子（reply / reasoning / acting / model_call / permission / compress / system_prompt）。本助手在 Service 里用过一处：截断过长的 `TeamSay`，避免 ChatLing 400。

SDK 版如果 Leader 传给提炼的材料已经在 `ask_extractor` 里截断，这段中间件可以不写。要讲的是能力：日志、限流、藏工具、改系统提示，都往中间件放，不要去改 `Agent` 类。

### 3.7 多智能体：两种拼法，现场画一下

**拼法 A — 代码编排（你写死顺序）**

```python
raw = await searcher.reply(UserMsg(..., content=task))
analysis = await extractor.reply(UserMsg(..., content=raw.get_text_content()))
brief = await writer.reply(UserMsg(..., content=analysis.get_text_content()))
```

适合流程固定、要可测、不想让模型自己决定叫谁。检索 → 提炼 → 套模板，本助手的主路径其实就是这个。

**拼法 B — 工具编排（Leader 自己决定叫谁）**

Leader 持有 `ask_searcher` / `ask_extractor`，提示词里写「先问清再搜，搜完再提炼」。模型可能多轮澄清（本轮不调工具），要素齐了再调工具。

`sdk_briefing.py` 用的是 **B**，因为演示里最有价值的行为是「该问的时候问、不该问的时候开工」。A 做不到多轮澄清，除非你在 Python 里再写一套问询状态机。

**拼法 C — Agent Service 的 Team 工具**

`TeamCreate` → `AgentInvite` → `TeamSay`。这是 **app 层工具**，不在 `agentscope.agent` 里。它多出来的是：为专家开新会话、Redis 跨进程唤醒、花名册可邀请。智能仍是底下的 `Agent.reply`。

分享时把这句话说死：

> 同学自己做内部工具，优先 A 或 B。只有当你需要「浏览器里动态组队、多用户、多实例」时，才需要 C。

### 3.8 包一层 HTTP：这就叫「用 SDK 构造后端服务」

SDK 不自带路由。最小后端就是 FastAPI 调 `reply` / `reply_stream`：

```python
@app.post("/chat")
async def chat(body: ChatIn):
    team = get_or_create_session(body.session_id)
    msg = await team.leader.reply(UserMsg(name="user", content=body.message))
    return {"reply": msg.get_text_content()}

@app.post("/chat/stream")
async def chat_stream(body: ChatIn):
    team = get_or_create_session(body.session_id)
    async def events():
        async for ev in team.leader.reply_stream(
            UserMsg(name="user", content=body.message),
        ):
            if isinstance(ev, TextBlockDeltaEvent):
                yield f"data: {ev.delta}\n\n"
        yield "data: [DONE]\n\n"
    return StreamingResponse(events(), media_type="text/event-stream")
```

你要自己写的只有：鉴权、session 字典、怎么把 Event 变成 SSE。对话内核、工具循环、MCP 调用都不用写。

对照 `create_app`：它额外给了用户隔离、会话落库、权限钩子、工作区、Hub、现成 `/chat` `/sessions/{id}/stream`。对产品有用，对「学会 AgentScope」不是第一步。

### 3.9 现场带跑 `sdk_briefing.py`

另开终端（8000 上的 Web UI 演示可以同时留着，端口不冲突）：

```bash
curl -sS http://127.0.0.1:8100/chat \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"demo","message":"帮我看看贝壳找房最近在租房这块有什么动静。"}'
```

预期：返回的是澄清问题，不是简报。同一 `session_id` 再发：

```bash
curl -sS http://127.0.0.1:8100/chat \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"demo","message":"主要看产品功能，近三个月，内部周报。"}'
```

预期：开始调 `ask_searcher` → `ask_extractor`，最后是带链接的简报。

让同学打开 `sdk_briefing.py`，从上到下指：模型 → 三个 Agent → 两个函数工具 → FastAPI。文件不长，正好当教材。

---

## 4. 【对照】create_app 这一路（简讲）

演示用的产品后端就是 `examples/local_eval/main.py` 里这一句：

```python
app = create_app(
    storage=AsyncSQLAlchemyStorage(pg_url, create_tables=True),
    message_bus=RedisMessageBus(host=..., port=...),
    workspace_manager=LocalWorkspaceManager(
        basedir="workspaces",
        default_mcps=[tavily],
        skill_paths=["demo_skills/intel-report"],
    ),
    resource_access_policy=AdminCatalogPolicy(admin_user),
    extra_agent_middlewares=_intel_agent_middlewares,
)
```

然后 `uvicorn.run("main:app")`。不写路由、不写表结构、不写前端。

和 SDK 示例的对应：

| 你在 SDK 里手写的 | create_app 里谁接 |
|---|---|
| `OpenAIChatModel(...)` | 用户/admin 在 UI 里配 Credential，按 session 解开 |
| 三个 `Agent(...)` | admin 在界面创建，提示词存在 PG |
| `FunctionTool(ask_searcher)` | 框架挂 `AgentInvite` / `TeamSay` |
| `Toolkit(mcps=[tavily])` | `default_mcps`（注意：会进所有工作区） |
| `skills_or_loaders=[...]` | `skill_paths` + 工作区 Skill 面板 |
| `dict[session_id, Agent]` | PostgreSQL `sessions` / `messages` |
| 进程内 `await other.reply` | Redis MessageBus 唤醒另一个 session |
| 自己写的 `/chat` | 框架现成 `/chat` + SSE |
| 没有「别人的智能体」 | `AdminCatalogPolicy`：运维账号的助手只读共享 |

`create_app` 作为开发仍有东西可讲，但只讲**接线决策**，不要把源码当课：

1. 存储用公司 PG、总线用 Redis → 两个进程才能续聊
2. 搜索必须种在工作区默认 MCP → 被邀请的专家吃不到「某个会话里临时挂的 MCP」
3. `AdminCatalogPolicy` → 打开就能聊，会话仍按用户隔离
4. `extra_agent_middlewares` → 产品化之后才补上的防护

配置手册仍是 `intel_team_setup.md`：先专家后 Leader、每个专家先开一次会话选 ChatLing、改提示词必须新开会话。分享时说「运维做一次，用户永远看不到」即可。

---

## 5. 两条路怎么选（给同学带回去）

| 你要做的事 | 建议 |
|---|---|
| 学会 AgentScope、写内部脚本、接进现有 FastAPI | **SDK**（今天的 `sdk_briefing.py`） |
| 给非开发同事一个打开就能聊的产品 | **create_app** + 现成 Web UI |
| 流程极死、要单测、模型不许自己选专家 | SDK + 代码编排（拼法 A） |
| 要多轮澄清、专家常驻花名册、多实例 | create_app + Invite |
| 两者都要 | 先 SDK 把角色和工具验证对，再把提示词/MCP 搬进 Service |

常见误区：

- 「用了 create_app 就是自研了一套 Agent 框架」——路由是框架的，你做的是选存储、选 MCP、写策略和提示词。
- 「SDK 不能做服务」——`Agent.reply` 外面套 FastAPI 就是服务。缺的是多租户和持久化，不是智能。
- 「多智能体必须用 Team 工具」——两个 `Agent` 互相 `reply`，或 Leader 调 `FunctionTool`，都是多智能体。

---

## 6. 分享现场流程（可直接当讲稿）

1. **开场（1 min）**  
   今天只做一个助手：公开信息简报。前端不重要。开发要会 SDK，create_app 是产品化。

2. **演示（7 min）**  
   用 Web UI 跑第 1 节两条试问。边跑边说：现在提问的是 Leader；现在工具栏出现搜索的是检索专家；最后出来的结构是 Skill。

3. **拆积木（5 min）**  
   投影 3.1 的表，用刚才的现象填「SDK 对应物」。

4. **主讲 SDK（25 min）**  
   打开 `sdk_briefing.py`，按 模型 → Agent → 三种工具 → 两种编排 → FastAPI 往下讲。中途 curl 一次澄清、一次出简报。

5. **对照 create_app（8 min）**  
   打开 `main.py` 的 `create_app(...)`，用第 4 节那张表一行行对。强调：admin 配专家、MCP 必须 default、共享策略 20 行。

6. **收束（3 min）**  
   回去先把 `sdk_briefing.py` 改成你们自己的一个专家（例如只检索、不提炼），能跑通再考虑 Service。

---

## 7. 同学课后怎么练

1. 跑通 `python sdk_briefing.py`，用 curl 走完澄清 → 简报。
2. 给 Leader 再加一个 Python 工具，例如把简报写到本地文件（`Write` 或自己的 `FunctionTool`）。
3. 把 Tavily 换成你们已有的搜索 HTTP——只改 `MCPClient` 或写成 `FunctionTool`，三个 Agent 的提示词可以不动。
4. 有余力再看 `main.py` + `intel_team_setup.md`，把同一套提示词贴进 Web UI，体会 Service 多出来的会话和邀请。

不要求这轮接长期记忆、知识库、飞书、定时任务。那些是框架有、本场景用不上的；分享时点名边界即可。
