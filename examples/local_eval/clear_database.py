#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""清空 local_eval 所用 PostgreSQL 中的应用表数据（保留表结构 / alembic_version）。

用法（在 examples/local_eval 下，已 source .env）::

    # 交互确认
    python clear_database.py

    # 跳过确认（仿 deer-flow verify.sh clear-database.py --yes）
    python clear_database.py --yes

可选同时清空本机 AgentScope Redis（默认 6380）::

    python clear_database.py --yes --also-redis

不清 workspace 磁盘目录；需要时可手动::

    rm -rf workspaces/*

依赖：与 ``main.py`` 相同，使用已安装的 **asyncpg**（不必装 psycopg2）。
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from pathlib import Path

_here = Path(__file__).resolve().parent


def _load_dotenv() -> None:
    """Load ``.env`` into ``os.environ`` if present (does not override)."""
    env_path = _here / ".env"
    if not env_path.is_file():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        os.environ.setdefault(key, value)


def _asyncpg_dsn(url: str) -> str:
    """Normalize URL for asyncpg (no ``+asyncpg`` dialect suffix)."""
    if url.startswith("postgresql+asyncpg://"):
        return url.replace("postgresql+asyncpg://", "postgresql://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql://", 1)
    return url


def _mask_url(url: str) -> str:
    return re.sub(r":([^:@/]+)@", ":***@", url)


def _clear_redis(host: str, port: int) -> None:
    try:
        import redis
    except ImportError:
        print(
            "警告: 未安装 redis 包，跳过 --also-redis。"
            f"可用: redis-cli -p {port} FLUSHDB",
            file=sys.stderr,
        )
        return
    client = redis.Redis(host=host, port=port, decode_responses=True)
    client.ping()
    client.flushdb()
    print(f"已清空 Redis {host}:{port} 当前 DB")


async def _truncate_public_tables(dsn: str) -> None:
    try:
        import asyncpg
    except ImportError:
        print(
            "错误: 需要 asyncpg。"
            "请先激活仓库 .venv（与 main.py 相同依赖）。",
            file=sys.stderr,
        )
        sys.exit(1)

    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch(
            "SELECT tablename FROM pg_tables "
            "WHERE schemaname = 'public' "
            "ORDER BY tablename",
        )
        targets = [
            r["tablename"]
            for r in rows
            if r["tablename"] != "alembic_version"
        ]
        if not targets:
            print("无应用表（空库或尚未 create_tables），跳过 PG。")
            return
        sql = (
            "TRUNCATE TABLE "
            + ", ".join(f'"{t}"' for t in targets)
            + " RESTART IDENTITY CASCADE"
        )
        await conn.execute(sql)
        print(f"已清空 {len(targets)} 张表: {', '.join(targets)}")
    finally:
        await conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="清空 AgentScope local_eval PG 应用表数据",
    )
    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="跳过确认",
    )
    parser.add_argument(
        "--also-redis",
        action="store_true",
        help="同时 FLUSHDB 本机 AgentScope Redis",
    )
    args = parser.parse_args()

    _load_dotenv()
    raw_url = os.getenv("AGENTSCOPE_PG_URL", "").strip()
    if not raw_url:
        print(
            "错误: 缺少 AGENTSCOPE_PG_URL。"
            "请先 cp .env.example .env 并填写，或 set -a && source .env",
            file=sys.stderr,
        )
        sys.exit(1)

    dsn = _asyncpg_dsn(raw_url)
    print(f"数据库: {_mask_url(dsn)}")
    print("将 TRUNCATE public 下除 alembic_version 外的所有表（保留结构）")

    if not args.yes:
        if input("确认? [y/N] ").strip().lower() not in ("y", "yes"):
            print("已取消")
            return

    asyncio.run(_truncate_public_tables(dsn))

    if args.also_redis:
        host = os.getenv("AGENTSCOPE_REDIS_HOST", "127.0.0.1")
        port = int(os.getenv("AGENTSCOPE_REDIS_PORT", "6380"))
        try:
            _clear_redis(host, port)
        except Exception as e:  # pylint: disable=broad-except
            print(f"清空 Redis 失败: {e}", file=sys.stderr)
            sys.exit(1)

    print(
        "提示: 表结构仍在；下次测 API 需重新 "
        "credential → agent → session。"
        " workspace 磁盘未删（可选 rm -rf workspaces/*）。",
    )


if __name__ == "__main__":
    main()
