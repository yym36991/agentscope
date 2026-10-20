# -*- coding: utf-8 -*-
"""L1 orchestration backend — application factory.

Business control plane of the cost assessment platform (architecture.md
§2). It never imports agentscope and never touches the runtime's
database: all runtime access goes over HTTP, and only from the (future)
``app/runtime_client`` module (§8.7 anti-corruption layer).
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import auth, routes


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    from app.db import engine

    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Software Cost Assessment Platform API",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.include_router(routes.router)
    app.include_router(auth.router)
    return app


app = create_app()
