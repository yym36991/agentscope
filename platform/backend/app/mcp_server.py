# -*- coding: utf-8 -*-
"""Price-baseline MCP server (architecture.md §7.1 dual track).

The budget agent queries the structured ``price_items`` table through
this MCP tool instead of retrieving numbers from a vector store —
costing figures must be exact and auditable, never "recalled". The
server is mounted into the L1 FastAPI app and consumed by the runtime
via its ``default_mcps`` (streamable-http), so every stage agent can
call it; only the budget blueprint tells its agent to.

No auth: a read-only localhost endpoint, same trust level as the
health route. Revisit if L1 is ever exposed beyond the deployment
boundary (§10).
"""
from fastmcp import FastMCP
from sqlalchemy import or_, select

from app.db import SessionLocal
from app.models import PriceItem

mcp = FastMCP("price-baseline", instructions=(
    "银行软件造价评估的价格基准查询工具。金额与系数一律以此工具"
    "返回值为准，不要凭记忆报价。"
))


@mcp.tool
async def query_price_baseline(
    region: str | None = None,
    item_type: str | None = None,
    keyword: str | None = None,
) -> str:
    """查询价格基准表（人月费率、调整因子、生产率基准等）。

    Args:
        region: 地区，如 "北京"、"全国"；省略则不过滤。
        item_type: 条目类型，如 "人月费率"、"调整因子"、"生产率基准"；
            省略则不过滤。
        keyword: 名称关键词（模糊匹配）；省略则不过滤。

    Returns:
        匹配的基准条目列表（地区、类型、名称、数值、单位、年份、
        来源），按年份降序。为空时建议换用更宽的查询条件。
    """
    stmt = select(PriceItem).order_by(
        PriceItem.effective_year.desc(), PriceItem.id
    )
    if region:
        stmt = stmt.where(PriceItem.region == region)
    if item_type:
        stmt = stmt.where(PriceItem.item_type == item_type)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(or_(PriceItem.name.like(like), PriceItem.notes.like(like)))
    async with SessionLocal() as db:
        rows = (await db.scalars(stmt.limit(50))).all()
    if not rows:
        return "没有匹配的价格基准条目。可尝试：不传 region（用全国基准）、"
        "更换 item_type 或去掉 keyword。"
    lines = []
    for r in rows:
        line = (
            f"- {r.region}｜{r.item_type}｜{r.name}：{r.value} {r.unit}"
            f"（{r.effective_year} 年，来源：{r.source or '未注明'}）"
        )
        if r.notes:
            line += f"｜{r.notes}"
        lines.append(line)
    return "\n".join(lines)


@mcp.tool
async def list_price_types() -> str:
    """列出价格基准表里现有的地区与条目类型，帮助选择查询条件。"""
    async with SessionLocal() as db:
        regions = (await db.scalars(
            select(PriceItem.region).distinct().order_by(PriceItem.region)
        )).all()
        types = (await db.scalars(
            select(PriceItem.item_type).distinct().order_by(PriceItem.item_type)
        )).all()
    return (
        f"地区：{'、'.join(regions) or '（空）'}\n"
        f"条目类型：{'、'.join(types) or '（空）'}"
    )
