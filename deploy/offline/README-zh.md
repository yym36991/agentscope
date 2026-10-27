# 内网离线部署指南（银行全离线形态）

对应 `platform-design/architecture.md` §10.2。目标：同一套代码，在内网用
on-prem 组件跑起来——数据不出域、模型走行内推理服务。

## 1. 离线包内容

在外网机器上执行 `bash deploy/offline/build-bundle.sh` 生成，连同**仓库源码**
一起拷入内网：

| 内容 | 说明 |
|---|---|
| `deploy/offline/backend-wheels/` + `backend-requirements.txt` | L1 编排层全部依赖（版本冻结快照） |
| `deploy/offline/runtime-wheels/` + `runtime-requirements.txt` | 运行时全部依赖 + 从源码构建的 `agentscope-*.whl` |
| `deploy/offline/platform-dist/` | 平台前端静态产物（vite build） |
| 仓库源码 | 平台代码 + AgentScope 源码（上游同步的 fork） |

注意：wheels 按构建机的**平台与 Python 版本**下载（Windows x64 / py3.12），
内网机器需一致；跨平台构建请用 `pip download --platform <tag> --only-binary=:all:`。

## 2. 组件矩阵（全部 on-prem）

| 组件 | 版本要求 | 用途 |
|---|---|---|
| PostgreSQL | 16+（本机用 18.4 便携版验证） | `platform` 业务库 + `agentscope` 运行时库，两库互不共享表 |
| Redis | **建议 6.2+**（5.x 可跑，见下） | 消息总线 / 分布式会话锁 / SSE 事件回放 |
| 模型服务 | 行内 vLLM（OpenAI 兼容）或 GLM 网关（Anthropic 兼容） | 阶段智能体对话；模型卡片 YAML 离线导入（本机已验证 GLM 卡片 + Anthropic 兼容端点） |
| 向量化凭证 | 同一网关的 embedding 端点 | 知识库 RAG（M3；无凭证时平台优雅降级，仅对话不可检索） |

Redis 5.x 降级说明：本机 5.0.14 便携版验证通过，但 5.x 不支持
`XTRIM MINID`——仓库已带降级补丁（`_redis_message_bus.log_trim` 遇
`ResponseError` 记警告跳过裁剪，append 侧 MAXLEN 兜底）；6.2+ 自动走原路径。

## 3. 部署步骤

```bash
# (1) 建库（psql 连行内 PG）
createdb platform agentscope   # 两库

# (2) L1 venv —— 完全离线
cd platform/backend
python -m venv .venv
.venv/Scripts/pip install --no-index \
    --find-links ../../deploy/offline/backend-wheels \
    -r ../../deploy/offline/backend-requirements.txt
.venv/Scripts/python -m alembic upgrade head

# (3) 运行时 venv —— 完全离线（agentscope wheel 在同一 wheels 目录）
cd <仓库根>
python -m venv .venv
.venv/Scripts/pip install --no-index \
    --find-links deploy/offline/runtime-wheels \
    -r deploy/offline/runtime-requirements.txt
.venv/Scripts/pip install --no-index \
    --find-links deploy/offline/runtime-wheels \
    ./deploy/offline/runtime-wheels/agentscope-*.whl

# (4) 前端：静态产物由任意静态服务器承载（nginx / express）
#     platform-dist/ → 平台 SPA；examples/web_ui → 运行时管理 UI

# (5) 按第 4 节环境变量起服务（可参考仓库根 start.sh 的启动顺序）
```

## 4. 环境变量（部署差异全在这里）

**运行时（examples/platform_agent_service/main.py，端口 8000，`AS_PORT` 可改）：**

| 变量 | 说明 |
|---|---|
| `AS_STORAGE_URL` | `postgresql+asyncpg://<user>@<pg-host>:5432/agentscope` |
| `AS_REDIS_HOST` / `AS_REDIS_PORT` | 行内 Redis |
| `AS_DOWNLOAD_SECRET` | **必设强随机值**（跨实例/跨重启的签名下载链接） |
| `AS_QDRANT_PATH` | 单机内嵌向量索引落盘目录 |
| `AS_PRICE_MCP_URL` | L1 的价格基准 MCP（默认 `http://<l1>:8100/mcp/price/`） |

**L1 编排层（platform/backend，端口 8100）：**

| 变量 | 说明 |
|---|---|
| `PLATFORM_DATABASE_URL` | `postgresql+asyncpg://<user>@<pg-host>:5432/platform` |
| `PLATFORM_JWT_SECRET` | **必设强随机值**（默认值仅供开发） |
| `PLATFORM_RUNTIME_BASE_URL` | 单运行时：`http://<runtime>:8000` |
| `PLATFORM_RUNTIME_BASE_URLS` | 多副本：逗号分隔，轮询 + 连接级故障转移（M5） |
| `PLATFORM_RUNTIME_MODEL` | 平台默认模型（如 `glm-5.3`） |

**多实例（M5）要点：**
- 运行时副本：多进程/多主机各起一份（同 PG + 同 Redis + 同
  `AS_DOWNLOAD_SECRET`），L1 设 `PLATFORM_RUNTIME_BASE_URLS` 指向全部副本，
  或前置 LB 只设单 URL；
- 会话互斥是两级的：同进程双投递 409（进程内 registry），跨副本投递被
  接受、任务在 Redis 分布式锁后**排队串行**（`verify_m5.py` 已在双副本上
  实测）；
- 多副本时向量索引必须共享（`QdrantStore(url=...)` 指向 Qdrant 服务），
  内嵌 path 模式是单进程独占的；知识库 blob 换 S3/MinIO、工作区换共享存储
  （单机同盘部署无此问题）。

## 5. 部署后验证

```bash
# 语义冒烟（栈在跑时）：多实例 + 导出 + 故障转移
cd platform/backend
.venv/Scripts/python -m scripts.verify_m5
# 离线安装机制（bundle 已构建时自动纳入 verify_m5 第 4 步）
```

`verify_m5.py` 会拉起 8001 副本实测：共享存储可见性、跨副本会话与 SSE、
分布式锁串行化、L1 故障转移、md→docx/xlsx 导出、离线 venv 机制。

## 6. 合规要点（§10.2）

- **数据不出域**：模型端点全部内网；凭证（api_key）只存在于运行时库，
  L1 侧物理不可见（防腐层安全投影）；
- **全量审计**：审批留痕（`approval_tasks`）+ 产物不可变版本链 +
  阶段状态机三重守卫；意见台账/追溯矩阵可从管理视图直接导出取证；
- **产物存储**：按行内要求落加密盘（`artifact_dir` / blobs 可指向加密卷）。
