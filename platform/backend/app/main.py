# -*- coding: utf-8 -*-
"""L1 orchestration backend — application factory.

Business control plane of the cost assessment platform (architecture.md
§2). It never imports agentscope and never touches the runtime's
database: all runtime access goes over HTTP, and only from the (future)
``app/runtime_client`` module (§8.7 anti-corruption layer).
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import auth, hubs, kbs, projects, routes
from app import mcp_server


@asynccontextmanager
async def lifespan(app: FastAPI):
    # The price-baseline MCP sub-app builds its session manager inside
    # its own lifespan; mounted Starlette apps never receive the
    # parent's lifespan events, so enter the sub-app's lifespan here —
    # the composition fastmcp's ASGI docs prescribe.
    async with app.state.price_mcp_app.lifespan(app.state.price_mcp_app):
        yield
    from app.db import engine
    from app.runtime_client import get_runtime_client

    await get_runtime_client().aclose()
    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Software Cost Assessment Platform API",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.include_router(routes.router)
    app.include_router(auth.router)
    app.include_router(projects.router)
    app.include_router(kbs.router)
    app.include_router(hubs.router)
    price_mcp_app = mcp_server.mcp.http_app(path="/")
    app.state.price_mcp_app = price_mcp_app
    # http://<host>:<port>/mcp/price/ — streamable-http endpoint the
    # runtime's default_mcps consumes (§7.1 structured price track).
    app.mount("/mcp/price", price_mcp_app)
    return app


app = create_app()
