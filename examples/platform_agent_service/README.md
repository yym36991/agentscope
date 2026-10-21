# 平台 Agent Service（造价平台运行时入口）

软件全生命周期管控平台的 AgentScope 运行时（architecture.md §2 的运行时层）。
**派生自上游示例 [`examples/agent_service`](../agent_service)**——那边保持
零改动，方便随上游同步；平台的组装差异全部收敛在本目录。

## 与上游示例的差异（仅组装，无功能增删）

| 项 | 上游 `agent_service` | 本目录 |
|---|---|---|
| 落盘 | `RedisStorage` | `AsyncSQLAlchemyStorage` → PG 库 `agentscope`（`AS_STORAGE_URL`） |
| 消息总线 | `InMemoryMessageBus`（注释里推荐 Redis） | `RedisMessageBus`（`AS_REDIS_HOST`/`AS_REDIS_PORT`） |
| 下载签名密钥 | 随机 | 固定（`AS_DOWNLOAD_SECRET`），重启/多实例下签名 URL 不失效 |

三者都是环境变量可覆盖，默认值即本机开发环境（PG 5432 / Redis 6379）。

## 运行

```bash
# 由仓库根 start.sh 第 [3/6] 项自动拉起（推荐），或手动：
cd examples/platform_agent_service
../../.venv/Scripts/python main.py     # 端口 8000, API 文档 /docs
```

前置：PostgreSQL（库 `agentscope`）与 Redis 已启动（start.sh [1/6][2/6]），
AgentScope venv 已装 `sql` extra（sqlalchemy/asyncpg）。

会话工作区落在 `workspaces/`（git 忽略）；智能体/会话/消息等持久数据
都在 PG 里，因此**换目录启动不丢数据**——工作区文件随目录走。

## 上游同步

上游 `agent_service/main.py` 若有值得跟进的改动（新渠道/新中间件配置），
手工 cherry-pick 到本目录的 main.py，组装三件套不要被覆盖回去。
