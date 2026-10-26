# -*- coding: utf-8 -*-
"""M3 acceptance harness (architecture.md §12 M3): permission use cases
+ price baseline dual track.

Covers:
1. Admin-only price import (CSV) and member rejection;
2. The price-baseline MCP tool returning imported rows exactly;
3. Group-level KB visibility (§7.2 filter-first): a granted group sees
   the KB, another group gets 403 on the same id;
4. Project KB links (owner binds, link lists back);
5. KB creation degrading gracefully while the runtime lacks an
   embedding credential (clear 503, nothing persisted).

The KB row + grants are seeded over SQL because real creation needs
the runtime embedding credential the operator has not registered yet —
the row carries agentscope_kb_id=NULL and exercises exactly the L1
authorization surface M3 owns. Run from platform/backend:

    .venv/Scripts/python -m scripts.verify_m3
"""
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

BASE = "http://127.0.0.1:8100"
PG = dict(host="127.0.0.1", port=5432, user="postgres", database="platform")

PRICE_CSV = """region,item_type,name,value,unit,effective_year,source,notes
全国,人月费率,一线城市软件工程师人月费率,28000,元/人月,2025,行业基准数据（示意）,含五险一金
全国,人月费率,二线城市软件工程师人月费率,23000,元/人月,2025,行业基准数据（示意）,
北京,人月费率,北京软件研发人月费率基准,31500,元/人月,2025,北京软件造价评估技术创新联盟（示意值）,
全国,生产率基准,预估功能点法生产率基准,7.0,人时/功能点,2025,行业基准数据（示意）,UFP 口径
全国,生产率基准,预算功能点法生产率基准,8.5,人时/功能点,2025,行业基准数据（示意）,
全国,调整因子,规模变更调整因子,1.26,系数,2025,GB/T 36964（示意）,需求变更风险
全国,调整因子,应用类型调整因子-交易处理,1.0,系数,2025,GB/T 36964（示意）,
北京,调整因子,质量特性调整因子基准,1.05,系数,2025,北京联盟基准（示意）,
"""

_T0 = time.time()


def log(msg: str) -> None:
    print(f"[{time.time() - _T0:6.1f}s] {msg}", flush=True)


async def register_and_login(
    client: httpx.AsyncClient, username: str, password: str = "Verify12345"
) -> str:
    r = await client.post(
        "/auth/register",
        json={
            "username": username,
            "password": password,
            "display_name": username,
        },
    )
    assert r.status_code in (201, 409), r.text  # 409 = previous run
    r = await client.post(
        "/auth/login", json={"username": username, "password": password}
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def promote_admin() -> None:
    """platadmin is pre-registered by the operator (or a previous run)."""
    import asyncpg

    conn = await asyncpg.connect(**PG)
    await conn.execute(
        "UPDATE users SET role = 'ADMIN' WHERE username = 'platadmin'"
    )
    await conn.close()


async def seed_kb_and_groups() -> int:
    """Create 造价一部 group + a test KB granted (read) to default.

    Idempotent on the KB name; returns the KB id.
    """
    import asyncpg

    conn = await asyncpg.connect(**PG)
    try:
        gid = await conn.fetchval(
            "INSERT INTO groups (name, created_at) VALUES ('造价一部', now()) "
            "ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name "
            "RETURNING id"
        )
        kb_id = await conn.fetchval(
            "INSERT INTO kbs (name, kb_type, description, agentscope_kb_id, "
            "owner_group_id, created_at) "
            "VALUES ('测试-制度规范库', 'SPEC', 'M3 授权用例验证库', NULL, "
            "NULL, now()) ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name "
            "RETURNING id"
        )
        await conn.execute(
            "INSERT INTO kb_grants (kb_id, group_id, level) "
            "VALUES ($1, 1, 'READ') "
            "ON CONFLICT (kb_id, group_id) DO NOTHING",
            kb_id,
        )
        return kb_id
    finally:
        await conn.close()


async def move_to_group(username: str, group_name: str) -> None:
    """Swap a user's default membership for *group_name* (test setup)."""
    import asyncpg

    conn = await asyncpg.connect(**PG)
    try:
        uid = await conn.fetchval(
            "SELECT id FROM users WHERE username = $1", username
        )
        gid = await conn.fetchval(
            "SELECT id FROM groups WHERE name = $1", group_name
        )
        await conn.execute(
            "DELETE FROM group_members WHERE user_id = $1 AND group_id = 1", uid
        )
        await conn.execute(
            "INSERT INTO group_members (user_id, group_id) VALUES ($1, $2) "
            "ON CONFLICT DO NOTHING",
            uid,
            gid,
        )
    finally:
        await conn.close()


async def mcp_query(region: str, item_type: str) -> str:
    """One stateful streamable-http MCP round-trip against L1's mount."""
    base = f"{BASE}/mcp/price/"
    headers = {"Accept": "application/json, text/event-stream"}
    init = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "verify-m3", "version": "0"},
        },
    }
    with httpx.Client(timeout=15) as c:
        r = c.post(base, json=init, headers=headers)
        sid = r.headers.get("mcp-session-id")
        h = {**headers, "mcp-session-id": sid}
        c.post(base, json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers=h)
        r = c.post(
            base,
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "query_price_baseline",
                    "arguments": {"region": region, "item_type": item_type},
                },
            },
            headers=h,
        )
        for line in r.text.splitlines():
            if line.startswith("data:"):
                result = json.loads(line[5:])
                return "".join(
                    b.get("text", "") for b in result["result"]["content"]
                )
    return ""


async def main() -> None:
    await promote_admin()
    async with httpx.AsyncClient(base_url=BASE, timeout=30) as client:
        admin_token = await register_and_login(
            client, "platadmin", password="Plat12345"
        )
        suffix = str(int(time.time()))
        token_a = await register_and_login(client, "m3a" + suffix)
        token_b = await register_and_login(client, "m3b" + suffix)
        kb_id = await seed_kb_and_groups()
        await move_to_group("m3b" + suffix, "造价一部")
        log("用户就绪: platadmin(管理员), m3a(default 组), m3b(造价一部组)")
        log(f"测试 KB #{kb_id} 就绪（default 组可读）")

        # -- 1. price import: admin only ------------------------------
        r = await client.post(
            "/admin/price-items/import",
            files={"file": ("price-2025.csv", PRICE_CSV.encode(), "text/csv")},
            headers=auth(token_a),
        )
        assert r.status_code == 403, f"member import must 403, got {r.status_code}"
        log("用例 1a 通过: 普通成员导入被拒 (403)")

        r = await client.post(
            "/admin/price-items/import",
            files={"file": ("price-2025.csv", PRICE_CSV.encode(), "text/csv")},
            headers=auth(admin_token),
        )
        assert r.status_code == 200, r.text
        out = r.json()
        assert out["imported"] == 8, out
        log(f"用例 1b 通过: 管理员导入 8 条 (覆盖 {out['replaced_regions']})")

        r = await client.get(
            "/price-items", params={"region": "北京"}, headers=auth(token_a)
        )
        rows = r.json()
        assert len(rows) == 2, rows
        rates = [x for x in rows if x["item_type"] == "人月费率"]
        assert rates and rates[0]["value"] == 31500.0, rates
        log(f"用例 1c 通过: 成员按地区查询到 {len(rows)} 条北京基准")

        # -- 2. MCP tool over the mounted endpoint --------------------
        text = await mcp_query("北京", "人月费率")
        assert "31500" in text, text
        log(f"用例 2 通过: MCP query_price_baseline(北京,人月费率) -> {text[:60]}…")

        # -- 3. KB visibility: filter first, retrieve second ----------
        r = await client.get("/kbs", headers=auth(token_a))
        ids = [k["id"] for k in r.json()]
        assert kb_id in ids, ids
        log("用例 3a 通过: default 组成员可见测试 KB")

        r = await client.get("/kbs", headers=auth(token_b))
        assert kb_id not in [k["id"] for k in r.json()], r.json()
        log("用例 3b 通过: 造价一部组成员列表不可见")

        r = await client.get(f"/kbs/{kb_id}/documents", headers=auth(token_b))
        assert r.status_code == 403, f"expected 403, got {r.status_code}"
        r = await client.post(
            f"/kbs/{kb_id}/search",
            json={"query": "制度"},
            headers=auth(token_b),
        )
        assert r.status_code == 403, f"expected 403, got {r.status_code}"
        log("用例 3c 通过: 跨组直接访问 documents/search 均 403")

        # -- 4. project kb links (owner binds) ------------------------
        r = await client.post(
            "/projects",
            json={"name": "M3验证-知识库绑定"},
            headers=auth(token_a),
        )
        project_id = r.json()["id"]
        r = await client.post(
            f"/projects/{project_id}/kb-links",
            json={"kb_id": kb_id, "stage": "budget"},
            headers=auth(token_a),
        )
        assert r.status_code == 201, r.text
        r = await client.get(
            f"/projects/{project_id}/kb-links", headers=auth(token_a)
        )
        links = r.json()
        assert len(links) == 1 and links[0]["kb_name"] == "测试-制度规范库"
        assert links[0]["stage"] == "budget"
        log("用例 4 通过: 项目属主绑定 KB 到 budget 阶段并可列出")
        r = await client.post(
            f"/projects/{project_id}/kb-links",
            json={"kb_id": kb_id, "stage": "budget"},
            headers=auth(token_b),
        )
        assert r.status_code in (403, 404), r.status_code
        log("用例 4b 通过: 非项目成员无法绑定")

        # -- 5. KB creation degrades without embedding credential -----
        r = await client.post(
            "/kbs",
            json={"name": "正式制度库", "kb_type": "spec", "description": "x"},
            headers=auth(admin_token),
        )
        assert r.status_code == 503, f"expected 503, got {r.status_code}"
        assert "凭证" in r.json()["detail"], r.text
        import asyncpg

        conn = await asyncpg.connect(**PG)
        n = await conn.fetchval(
            "SELECT count(*) FROM kbs WHERE name = '正式制度库'"
        )
        await conn.close()
        assert n == 0
        log("用例 5 通过: 无向量化凭证时创建 KB 返回 503 且零落库")

    log("M3 验证全部通过")


if __name__ == "__main__":
    asyncio.run(main())
