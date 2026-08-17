# Local Eval — PG + Redis + ChatLing

最小可测 Agent Service：对话存公司 PG，运行时协同走本机 Redis，模型走公司 ChatLing（OpenAI 兼容）。

## 0. 前置

- Python ≥ 3.11

## 1. 安装依赖（仓库根目录）

系统自带的 `python3` **没有** agentscope / uvicorn。必须用仓库里的虚拟环境：

```bash
cd /Users/a58/cdb/agentscope

# 已创建过可跳过
python3 -m venv .venv
source .venv/bin/activate

# 国内网络建议加镜像
UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
  uv pip install -e ".[service,storage-sql,storage-redis]" asyncpg
```

确认：

```bash
which python          # 应指向 .../agentscope/.venv/bin/python
python -c "import uvicorn, agentscope; print(agentscope.__version__)"
```

> 不要用裸的 `python main.py`（macOS 常没有 `python` 命令）；用 `.venv` 里的解释器，或先 `source .venv/bin/activate` 再 `python main.py`。

## 2. Redis（专用容器，端口 6380）

本机 **6379 往往已被 Langfuse 等占用且要求 AUTH**，不要抢这个口。
给 AgentScope 单独起一个无密码 Redis：

```bash
docker rm -f agentscope-redis 2>/dev/null
docker run -d --name agentscope-redis -p 6380:6379 redis:7
redis-cli -p 6380 ping   # 期望 PONG
```

停止：`docker stop agentscope-redis`

`.env` 里保持：

```bash
AGENTSCOPE_REDIS_HOST=127.0.0.1
AGENTSCOPE_REDIS_PORT=6380
```

## 3. 配置 `.env`

```bash
cd examples/local_eval
cp .env.example .env
# 编辑 .env：填 AGENTSCOPE_PG_URL、CHATLING_API_KEY 等
```

要点：

| 变量 | 作用 |
|------|------|
| `AGENTSCOPE_PG_URL` | 公司 PG；写 `postgresql://...` 即可，启动时会改成 `postgresql+asyncpg://` |
| `AGENTSCOPE_REDIS_*` | 本机 Redis |
| `CHATLING_*` | 仅给下面 curl 用；服务进程本身不读模型 key，模型靠 API 注册 credential |

## 4. 启动服务

```bash
cd /Users/a58/cdb/agentscope
source .venv/bin/activate

cd examples/local_eval
set -a && source .env && set +a
python main.py
# 或显式： /Users/a58/cdb/agentscope/.venv/bin/python main.py
```

看到类似输出即成功：

```text
Starting AgentScope local_eval on http://0.0.0.0:8000
  storage = PostgreSQL
  message_bus = Redis (127.0.0.1:6380)
```

健康检查：

```bash
curl -s http://127.0.0.1:8000/docs >/dev/null && echo OK
# 或打开 http://127.0.0.1:8000/docs
```

## 5. curl 冒烟（另开终端）

用 **`-i`**：把**状态行 + 响应头 + 响应体**一股脑打到终端（头和 body 中间有一个空行）。

> 说明：以前写的 `-D -` 里，第二个 `-` 不是空参数，在 curl 里表示「写到标准输出 stdout」。`-D 文件` 是把头写入文件，`-D -` 就是头打到屏幕。现在改成更直观的 `-i`，不再用 `-o` 落盘。

先加载环境变量（需要 `CHATLING_*`）：

```bash
cd /Users/a58/cdb/agentscope/examples/local_eval
set -a && source .env && set +a
export USER_ID=eval-user-1
export BASE=http://127.0.0.1:8000
```

### 5.1 注册 ChatLing credential

```bash
curl -i -sS -X POST "$BASE/credential/" \
  -H "Content-Type: application/json" \
  -H "X-User-ID: $USER_ID" \
  -d "{
    \"data\": {
      \"type\": \"openai_credential\",
      \"api_key\": \"$CHATLING_API_KEY\",
      \"base_url\": \"$CHATLING_BASE_URL\"
    }
  }"
```

终端里大致会看到：

```http
HTTP/1.1 201 Created
date: ...
content-type: application/json
content-length: ...

{"credential_id":"fc496fbf5cfc40349ba57fe55a8ff0e9"}
```

把 body 里的 id 赋给后续步骤（从上一段输出抄，或再跑一次只要 body）：

```bash
export CRED_ID=fc496fbf5cfc40349ba57fe55a8ff0e9
# 或：
# CRED_ID=$(curl -sS -X POST "$BASE/credential/" -H "Content-Type: application/json" \
#   -H "X-User-ID: $USER_ID" \
#   -d "{\"data\":{\"type\":\"openai_credential\",\"api_key\":\"$CHATLING_API_KEY\",\"base_url\":\"$CHATLING_BASE_URL\"}}" \
#   | python3 -c "import json,sys; print(json.load(sys.stdin)['credential_id'])")
```

| 头 / 字段 | 含义 |
|-----------|------|
| `HTTP/1.1 201 Created` | 创建成功（不是 200） |
| `content-type: application/json` | JSON 响应体 |
| `credential_id` | 服务端生成的凭证 ID；对应 PG `credentials.id` |

副作用：插入 `credentials` 一行。接口**只返回 id**，不回显 api_key。

### 5.2 创建 Agent

```bash
curl -i -sS -X POST "$BASE/agent/" \
  -H "Content-Type: application/json" \
  -H "X-User-ID: $USER_ID" \
  -d '{
    "name": "CloudAgent1",
    "system_prompt": "You are a concise cloud agent assistant. Reply in Chinese."
  }'
```

期望：`201` + body `{"agent_id":"..."}`。然后：

```bash
export AGENT_ID=从上面 body 抄过来的值
```

| 字段 | 含义 |
|------|------|
| `agent_id` | 对应 PG `agents.id`；后续 session / chat 都要带 |

响应体**不带回**完整 `context_config` 等，那些在库的 `payload` 里（默认值由服务端补全）。

### 5.3 创建 Session（挂上模型）

```bash
BASE=http://127.0.0.1:8000
USER_ID="eval-user-1"
CRED_ID="0441ce221433435e8e4c96a573d6f2a5"
AGENT_ID="a2d6fa1815a640fab173dc2a66aa1232"
curl -i -sS -X POST "$BASE/sessions/" \
  -H "Content-Type: application/json" \
  -H "X-User-ID: $USER_ID" \
  -d "{
    \"agent_id\": \"$AGENT_ID\",
    \"name\": \"eval-session-1\",
    \"chat_model_config\": {
      \"type\": \"openai_chat\",
      \"credential_id\": \"$CRED_ID\",
      \"model\": \"$CHATLING_MODEL\",
      \"parameters\": {
        \"temperature\": 0.4,
        \"top_p\": 0.6
      }
    }
  }"
```

期望：`201` + `{"session_id":"..."}`，然后 `export SESSION_ID=...`

| 字段 | 含义 |
|------|------|
| `session_id` | 对应 PG `sessions.id`；chat / SSE / messages 用它 |
| 请求里的 `chat_model_config` | 不在响应体回显，存在 session 配置里 |

### 5.4 打开 SSE（另开终端，先挂着）

```bash
curl -i -N \
  "$BASE/sessions/${SESSION_ID}/stream?agent_id=${AGENT_ID}" \
  -H "X-User-ID: $USER_ID"
```

要点：`200`，`content-type: text/event-stream`；之后是 `data: {...}` 和心跳 `:`。

### 5.5 触发一轮对话

```bash
curl -i -sS -X POST "$BASE/chat/" \
  -H "Content-Type: application/json" \
  -H "X-User-ID: $USER_ID" \
  -d "{
    \"agent_id\": \"$AGENT_ID\",
    \"session_id\": \"$SESSION_ID\",
    \"input\": {
      \"name\": \"eval-user\",
      \"role\": \"user\",
      \"content\": [{\"type\": \"text\", \"text\": \"用一句话介绍你自己\"}]
    }
  }"
```

期望：`200` + `{"status":"started","session_id":"..."}`（回复在 SSE，不在本接口）。

| 字段 | 含义 |
|------|------|
| `status` | `started` = 已调度后台 run |
| `session_id` | 回显会话 |

### 5.6 查历史消息 / 多用户隔离

```bash
curl -i -sS \
  "$BASE/sessions/${SESSION_ID}/messages?agent_id=${AGENT_ID}" \
  -H "X-User-ID: $USER_ID"

curl -i -sS \
  "$BASE/sessions/${SESSION_ID}/messages?agent_id=${AGENT_ID}" \
  -H "X-User-ID: other-user"
```

| 字段（本用户 200） | 含义 |
|--------------------|------|
| `messages` | 持久化消息 |
| `is_running` | 是否还有 run 在跑 |
| `has_more` | 是否可翻更早消息 |

他用户常见 `404` + `{"detail":"Session '…' not found."}`。

## 6. 上传并使用自定义 Skill

Skill 是带 `SKILL.md` 的文件夹（YAML frontmatter 需要 `name` + `description`）。
仓库里已放示例：`demo_skills/greet-eval/`。

上传走 **`POST /workspace/skill/upload`**（挂到当前 session 的 workspace），不是改框架代码。

```bash
cd /Users/a58/cdb/agentscope/examples/local_eval

SKILL_DIR=demo_skills/greet-eval
SKILL_MD="${SKILL_DIR}/SKILL.md"
SIZE=$(wc -c < "$SKILL_MD" | tr -d ' ')

# manifest.path 必须是「文件夹名/相对路径」，且含 SKILL.md
MANIFEST=$(python3 -c "import json; print(json.dumps({
  'entries': [{'path': 'greet-eval/SKILL.md', 'size': $SIZE}]
}))")

curl -i -sS -X POST \
  "$BASE/workspace/skill/upload?agent_id=${AGENT_ID}&session_id=${SESSION_ID}" \
  -H "X-User-ID: $USER_ID" \
  -F "manifest=${MANIFEST}" \
  -F "files=@${SKILL_MD};filename=greet-eval/SKILL.md"
```

期望：`201 Created`。

确认已挂上：

```bash
curl -sS "$BASE/workspace/skill?agent_id=${AGENT_ID}&session_id=${SESSION_ID}" \
  -H "X-User-ID: $USER_ID" | python3 -m json.tool
```

磁盘上会出现：`workspaces/<agent_id>/skills/greet-eval/SKILL.md`。

使用（SSE 挂着时发 chat）：

```bash
curl -i -sS -X POST "$BASE/chat/" \
  -H "Content-Type: application/json" \
  -H "X-User-ID: $USER_ID" \
  -d "{
    \"agent_id\": \"$AGENT_ID\",
    \"session_id\": \"$SESSION_ID\",
    \"input\": {
      \"name\": \"eval-user\",
      \"role\": \"user\",
      \"content\": [{
        \"type\": \"text\",
        \"text\": \"请用 greet-eval 这个 skill 跟我打个招呼\"
      }]
    }
  }"
```

Skill 主要注入系统提示/说明，不是像 MCP 那样的 RPC；模型应按 `SKILL.md` 正文格式回复（示例里应出现 `【Skill: greet-eval】`）。

## 7. Hub → 用户库 → workspace（Skill）

`local_eval` 挂了离线 Hub：`LocalEvalSkillHub`（`hub_id=local-eval`，卡片 `greet-eval`）。
**改 `main.py` 后需重启服务。**

流程分两步：install 只写 PG `skills`；挂到 workspace 才会下载 ZIP。

```bash
# 0) 看已注册的 Hub
curl -sS "$BASE/hub/skill" -H "X-User-ID: $USER_ID" | python3 -m json.tool

# 1) 浏览 / 搜卡片
curl -sS "$BASE/hub/skill/local-eval/cards" \
  -H "X-User-ID: $USER_ID" | python3 -m json.tool

curl -sS "$BASE/hub/skill/local-eval/cards/greet-eval" \
  -H "X-User-ID: $USER_ID" | python3 -m json.tool

# 2) Install → 写入用户库（PG skills），此时 workspace 不变
curl -i -sS -X POST \
  "$BASE/hub/skill/local-eval/cards/greet-eval/install" \
  -H "X-User-ID: $USER_ID"

# 3) 确认库里有了（记下返回的 id）
curl -sS "$BASE/skill" -H "X-User-ID: $USER_ID" | python3 -m json.tool
SKILL_ID=$(curl -sS "$BASE/skill" -H "X-User-ID: $USER_ID" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)[0]['id'])")

# 4) 从库挂到当前 agent workspace（这时才 download）
curl -i -sS -X POST \
  "$BASE/workspace/skill/from-library?agent_id=${AGENT_ID}&session_id=${SESSION_ID}" \
  -H "Content-Type: application/json" \
  -H "X-User-ID: $USER_ID" \
  -d "{\"skill_ids\": [\"$SKILL_ID\"]}"

curl -sS "$BASE/workspace/skill?agent_id=${AGENT_ID}&session_id=${SESSION_ID}" \
  -H "X-User-ID: $USER_ID" | python3 -m json.tool
```

| 步骤 | 写哪里 |
|------|--------|
| `POST .../install` | PG `skills`（用户库元数据） |
| `POST .../from-library` | `workspaces/<agent_id>/skills/`（从 Hub 再下 ZIP） |

若 workspace 里已有同名 `greet-eval`（先前 upload），from-library 可能去重/加后缀，以 `GET /workspace/skill` 为准。

可选：接真 ClawHub（需能访问 `clawhub.ai`）时在 `create_app` 里加  
`skill_hubs=[LocalEvalSkillHub(), ClawSkillHub(api_token=os.getenv("CLAWHUB_API_TOKEN"))]`，  
然后对 `hub_id=clawhub` 走同样 curl。

## 8. 日志与超时/重试（SDK）

AgentScope 框架日志走标准库 `logging`，logger 名 **`as`**（`agentscope.setup_logger`）。

| 输出 | 位置 |
|------|------|
| 服务（`main.py`） | **控制台** + `logs/agentscope-service-<PORT>.log` |
| SDK 超时脚本 | **控制台** + `logs/sdk_timeout_retry.log` |
| Uvicorn access/error | 仍打控制台（不是 `as` logger） |

```bash
# 看服务日志（重启 main.py 后才会写文件）
tail -f logs/agentscope-service-8000.log

# SDK：主模型极短 timeout → 重试耗尽 → Fallback 到 CHATLING_FALLBACK_MODEL
set -a && source .env && set +a
python eval_timeout_retry.py
# 日志：Attempt ... Retrying → All 3 attempt(s) failed → Fallback to model '...'
grep -E 'Retrying|All .* failed|Fallback to model' logs/sdk_timeout_retry.log
```

**换模型（fallback）配在哪**

| 路径 | 怎么配 |
|------|--------|
| SDK | `Agent(..., model=primary, model_config=ModelConfig(fallback_model=fallback))` |
| Agent Service | session 的 `fallback_chat_model_config`（创建/PATCH session；可与主模型共用同一 credential，只改 `model` 名） |

顺序：主模型自身 `max_retries` 先打完 → Agent 再切 fallback（Agent 外层 `ModelConfig.max_retries` 默认 0，避免和模型内重试叠乘）。

## 9. 双实例（同 Redis MessageBus）交叉 SSE

本机模拟两台机：同一 PG + 同一 Redis，两个 uvicorn（不同端口）。

```bash
# 终端 1（若 8000 已在跑可跳过）
set -a && source .env && set +a
python main.py

# 终端 2
set -a && source .env && set +a
AGENTSCOPE_PORT=8001 python main.py
```

交叉测（SSE 挂一台，chat 打另一台）：

```bash
export A=http://127.0.0.1:8000 B=http://127.0.0.1:8001
# 用已有 USER / AGENT / SESSION，或按第 5 节在 A 上新建
# 务必确认 session 的 model / credential 有效（否则只有 REPLY_END error，没有正文）

# Case：SSE 订在 A(8000)，chat 打到 B(8001)
curl -i -N "$A/sessions/$SESSION_ID/stream?agent_id=$AGENT_ID" -H "X-User-ID: $USER_ID"

# 另开终端：
curl -i -sS -X POST "$B/chat/" -H "Content-Type: application/json" -H "X-User-ID: $USER_ID" \
  -d "{\"agent_id\":\"$AGENT_ID\",\"session_id\":\"$SESSION_ID\",\"input\":{\"name\":\"u\",\"role\":\"user\",\"content\":[{\"type\":\"text\",\"text\":\"只回复：CROSS-B-TO-A\"}]}}"
```

**期望**：

1. **总线通了**：A 的 SSE / Probe（代理 8000）能看到 `REPLY_START` → … → `REPLY_END`（即使 chat 打在 8001）
2. **有正文**：出现 `TEXT_BLOCK_DELTA`；若只有 `REPLY_END error`（如 `invalid_request` / `setup`），是 **该 session 模型/凭证问题**，不是双实例没转发

Probe 只代理 `8000` 时：请把 **SSE 订在 A**；chat 可以打 B。若 SSE 也订在 B，Probe 看不到（它不连 8001）。

| 点 | 说明 |
|----|------|
| 流不乱 | 靠 Redis pub/sub + session events；跨进程可收 |
| 同 session 并发 chat | Redis session 锁串行；两边 POST 都可能先 `started`，实际 run 排队 |
| 两台真云主机 | PG + Redis 必须共用；`LocalWorkspaceManager` 磁盘不共享，skills/MCP 文件需共享存储或接受 per-node workspace |

## 10. 清空数据库（评测前重置）

仿 deer-flow `clear-database.py --yes`：清空 **PG 应用表数据**，**保留表结构**，并跳过 `alembic_version`（若有）。  
驱动用 **asyncpg**（与 `main.py` 相同），不需要 `psycopg2`。

```bash
cd /Users/a58/cdb/agentscope
source .venv/bin/activate
cd examples/local_eval
set -a && source .env && set +a

# 交互确认
python clear_database.py

# 跳过确认；建议同时清 Redis，避免旧 inbox / session events 干扰
python clear_database.py --yes --also-redis
```

| 清了什么 | 没清什么 |
|----------|----------|
| PG：`agents` / `sessions` / `messages` / `credentials` / `teams` / `skills` / … | 表结构；`alembic_version` |
| `--also-redis`：当前 Redis DB | `workspaces/` 磁盘（可选手动 `rm -rf workspaces/*`） |

**清空后还要不要重建？要。** 服务重启与否都一样——库空了，就必须重新走第 5 节：

1. `POST /credential/` → 新 `CRED_ID`  
2. `POST /agent/` → 新 `AGENT_ID`  
3. `POST /sessions/`（带 `chat_model_config`）→ 新 `SESSION_ID`  
4. 再订 SSE、发 chat  

旧的 `CRED_ID` / `AGENT_ID` / `SESSION_ID` 全部失效。  
改过 `main.py`（例如加了 `custom_subagent_templates`）需要 **重启** `python main.py`。

## 11. 多智能体（Team）冒烟

Agent Service 在 **非 worker** 会话上会自动挂 `TeamCreate` / `AgentCreate` / `TeamSay` / `TeamDelete`。  
leader 调工具 → 框架建 worker agent+session → Redis inbox/wakeup → worker `TeamSay` 回报 → 再唤醒 leader 汇总。  
用户只 chat / SSE **同一个 leader 的 `(AGENT_ID, SESSION_ID)`**。

**正常流程（防乒乓）：**

1. `TeamCreate` → 多次 `AgentCreate`（`prompt` 写清任务，并写「只 TeamSay 一次后停」）  
2. Worker **只汇报一次** → 停  
3. Leader **只对用户汇总一次** → 停（**禁止** TeamSay 回成员致谢/追问）  
4. （可选）再 `TeamDelete` 清理  

`researcher` 模板已在 `main.py` 写死「只 TeamSay 一次、忽略致谢」；**改 `main.py` 后必须重启服务**。

### 11.0 正确用法清单（推荐按这个调）

| 调整项 | 怎么做 |
|--------|--------|
| 清干净再测 | `clear_database.py --yes --also-redis`，打断积压的 wakeup |
| Leader 人设 | system_prompt：汇总后停止；禁止对成员 TeamSay |
| Leader 迭代 | `react_config.max_iters` 建议 30～40（够建队+汇总，别无限） |
| Worker 模板 | 用 `subagent_type=researcher`（见 `main.py`）；默认 `default` 较松，易闲聊 |
| AgentCreate 的 prompt | 每人一句：「完成后仅 TeamSay 一次给 leader，然后停止」 |
| 用户任务话术 | 明确「三人各汇报一次 → 你只汇总一次 → 结束」 |
| 成功判定 | leader 一次清晰汇总 + `REPLY_END` 后 **不再**连续新 `REPLY_START`；日志 Inbox 很快停 |
| 仍刷屏时 | 立即 `--also-redis` 清队列；不要在脏 session 上续聊 |

框架**不会**硬限制「每人只能 TeamSay 一次」——要靠模板 + 提示词。部署（PG/Redis）不用为治乒乓而改。

### 11.1 重测前清库

半截失败 / 乒乓中的 session 会污染上下文。重测前：

```bash
cd /Users/a58/cdb/agentscope/examples/local_eval
set -a && source .env && set +a
python clear_database.py --yes --also-redis
# 可选：rm -rf workspaces/*
```

然后 **重新** credential → **一个** TeamLeader → **一个** session。旧 ID 全部作废。

### 11.2 关键：用哪套 ID？

**建队发生在「某一个已挂模型的 session」上**，不是「某个没有 session 的 agent 空壳」。

| 错误理解 | 正确做法 |
|----------|----------|
| 先建 A+session，再另建 TeamLeader，SSE/chat 仍用 A 的 session | `agent_id` 与 `session_id` **必须是一对** |
| 只建 TeamLeader agent，不建 session 就 chat | **不行**，必须先为该 agent `POST /sessions/` |
| 终端 A / B 用不同的 agent 或 session | **不行**，A/B 同一对 `(AGENT_ID, SESSION_ID)` |

### 11.3 创建 leader

```bash
export BASE=http://127.0.0.1:8000
export USER_ID=eval-user-1
export CRED_ID=feb8b979ec174e83bc5189b018220555

curl -i -sS -X POST "$BASE/agent/" \
  -H "Content-Type: application/json" \
  -H "X-User-ID: $USER_ID" \
  -d '{
    "name": "TeamLeader",
    "system_prompt": "你是团队领导。流程：TeamCreate → AgentCreate(subagent_type=researcher) → 等成员各 TeamSay 一次 → 只向用户做一次中文汇总后停止。禁止对成员 TeamSay（含致谢/追问，会触发互唤醒）。汇总完成前不要 TeamDelete；全部完成后可 TeamDelete（无参 {}）。AgentCreate 的 prompt 必须要求成员「只 TeamSay 一次后停止」。",
    "react_config": { "max_iters": 40 }
  }'
export AGENT_ID=返回的_agent_id

curl -i -sS -X POST "$BASE/sessions/" \
  -H "Content-Type: application/json" \
  -H "X-User-ID: $USER_ID" \
  -d "{
    \"agent_id\": \"$AGENT_ID\",
    \"name\": \"team-leader-session\",
    \"chat_model_config\": {
      \"type\": \"openai_chat\",
      \"credential_id\": \"$CRED_ID\",
      \"model\": \"$CHATLING_MODEL\",
      \"parameters\": {\"temperature\": 0.3, \"top_p\": 0.6}
    }
  }"
export SESSION_ID=返回的_session_id

echo "AGENT_ID=$AGENT_ID SESSION_ID=$SESSION_ID CRED_ID=$CRED_ID"
```

### 11.4 订 SSE + 发拆分任务

```bash
# 终端 A
curl -i -N \
  "$BASE/sessions/${SESSION_ID}/stream?agent_id=${AGENT_ID}" \
  -H "X-User-ID: $USER_ID"

# 终端 B
curl -i -sS -X POST "$BASE/chat/" \
  -H "Content-Type: application/json" \
  -H "X-User-ID: $USER_ID" \
  -d "{
    \"agent_id\": \"$AGENT_ID\",
    \"session_id\": \"$SESSION_ID\",
    \"input\": {
      \"name\": \"eval-user\",
      \"role\": \"user\",
      \"content\": [{
        \"type\": \"text\",
        \"text\": \"请组建小队：前端/后端/测试各写 3 条要点，你汇总成一段中文。1) TeamCreate 2) 三次 AgentCreate，subagent_type=researcher；每人 prompt 写：只输出要点，完成后仅 TeamSay 一次给 leader 然后停止 3) 收齐三次汇报后，只对我汇总一次并结束。禁止 TeamSay 回成员；禁止自己写完三方向；无参用 {}。\"
      }]
    }
  }"
```

### 11.5 期望现象

| 观察点 | 期望 |
|--------|------|
| SSE（leader） | `TeamCreate` / `AgentCreate` 成功；一次汇总正文后停 |
| PG `teams` / `agents` / `sessions` | 有队、有 `source=team` 成员、有 worker session |
| 服务日志 | 短暂 Inbox 注入后应明显变少，不应每秒刷 |
| 失败信号 | 反复 `exceeds max iteration` + 多 session 持续 injecting → 仍在乒乓 |

### 11.6 已知坑

| 现象 | 原因 | 处理 |
|------|------|------|
| `TeamDelete` 空参 JSON 错 | 已修空白→`{}` | 重启服务吃到修复；汇总后再 Delete |
| 反复 `max_iters` + Inbox 刷屏 | TeamSay 互唤醒 | 清单 §11.0；清 Redis；收紧模板/话术 |
| 汇总后又 `REPLY_START` | 又被 wakeup | leader 禁止回成员；SSE 可 Ctrl+C |
| 半截失败续聊 | 脏上下文 | 清库或新 session |

**说明：**`GET .../stream` 会一直挂着等事件；业务停的标志是不再出现新的 `REPLY_START`，不是 curl 自己退出。

双实例下 worker 可能跑在另一端口；leader SSE 仍订原 `(AGENT_ID, SESSION_ID)` 即可。

## 架构对应关系

| 组件 | 本例配置 |
|------|----------|
| Storage | 公司 PG（`AsyncSQLAlchemyStorage`） |
| MessageBus | 本机 Docker Redis `agentscope-redis`（`127.0.0.1:6380`，`RedisMessageBus`） |
| 模型 | ChatLing，经 `/credential` + session `chat_model_config` |
| 身份 | 请求头 `X-User-ID`（占位鉴权） |
| 多智能体 | Team 工具 + Redis wakeup；可选 `custom_subagent_templates`（`researcher`） |

单进程即可；多 worker / 多机以后同样用 Redis MessageBus，不必改业务 API。
