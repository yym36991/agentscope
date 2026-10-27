# -*- coding: utf-8 -*-
"""Resource-hub relay routes: MCP / skill hubs and the shared library.

The runtime owns the registries (GitHub, ClawHub) and the single
sys:runtime library the six stage agents share. Browsing is open to
every signed-in platform user; installs and library edits are
admin-only — those change what the stage agents can do, and per §8.2
the platform, not end users, owns the runtime's resources.
"""
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from app.api.deps import get_current_user
from app.api.kbs import _flow_http, _require_admin
from app.models import User
from app.runtime_client import RuntimeCallError, get_runtime_client

router = APIRouter(tags=["resource-hubs"])


# ---------- MCP hubs ----------

@router.get("/hubs/mcp")
async def list_mcp_hubs(user: Annotated[User, Depends(get_current_user)]) -> list:
    del user
    try:
        return await get_runtime_client().relay_json("GET", "/hub/mcp")  # type: ignore[return-value]
    except RuntimeCallError as exc:
        raise _flow_http(exc)


@router.get("/hubs/mcp/{hub_id}/cards")
async def list_mcp_cards(
    user: Annotated[User, Depends(get_current_user)],
    hub_id: str,
    q: Annotated[str | None, Query(max_length=200)] = None,
    cursor: Annotated[str | None, Query(max_length=500)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
) -> dict:
    del user
    params = {"limit": limit}
    if q:
        params["q"] = q
    if cursor:
        params["cursor"] = cursor
    try:
        return await get_runtime_client().relay_json(
            "GET", f"/hub/mcp/{hub_id}/cards", params=params
        )  # type: ignore[return-value]
    except RuntimeCallError as exc:
        raise _flow_http(exc)


@router.get("/hubs/mcp/{hub_id}/cards/{card_id}")
async def get_mcp_card(
    hub_id: str,
    card_id: str,
    user: Annotated[User, Depends(get_current_user)],
) -> dict:
    del user
    try:
        return await get_runtime_client().relay_json(
            "GET", f"/hub/mcp/{hub_id}/cards/{card_id}"
        )  # type: ignore[return-value]
    except RuntimeCallError as exc:
        raise _flow_http(exc)


@router.post("/hubs/mcp/{hub_id}/cards/{card_id}/install")
async def install_mcp_card(
    hub_id: str,
    card_id: str,
    user: Annotated[User, Depends(get_current_user)],
    body: dict = Body(default_factory=dict),
) -> dict:
    _require_admin(user)
    try:
        return await get_runtime_client().relay_json(
            "POST",
            f"/hub/mcp/{hub_id}/cards/{card_id}/install",
            body=body,
        )  # type: ignore[return-value]
    except RuntimeCallError as exc:
        raise _flow_http(exc)


# ---------- skill hubs ----------

@router.get("/hubs/skill")
async def list_skill_hubs(user: Annotated[User, Depends(get_current_user)]) -> list:
    del user
    try:
        return await get_runtime_client().relay_json("GET", "/hub/skill")  # type: ignore[return-value]
    except RuntimeCallError as exc:
        raise _flow_http(exc)


@router.get("/hubs/skill/{hub_id}/cards")
async def list_skill_cards(
    user: Annotated[User, Depends(get_current_user)],
    hub_id: str,
    q: Annotated[str | None, Query(max_length=200)] = None,
    cursor: Annotated[str | None, Query(max_length=500)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
) -> dict:
    del user
    params = {"limit": limit}
    if q:
        params["q"] = q
    if cursor:
        params["cursor"] = cursor
    try:
        return await get_runtime_client().relay_json(
            "GET", f"/hub/skill/{hub_id}/cards", params=params
        )  # type: ignore[return-value]
    except RuntimeCallError as exc:
        raise _flow_http(exc)


@router.get("/hubs/skill/{hub_id}/cards/{card_id}")
async def get_skill_card(
    hub_id: str,
    card_id: str,
    user: Annotated[User, Depends(get_current_user)],
) -> dict:
    del user
    try:
        return await get_runtime_client().relay_json(
            "GET", f"/hub/skill/{hub_id}/cards/{card_id}"
        )  # type: ignore[return-value]
    except RuntimeCallError as exc:
        raise _flow_http(exc)


@router.post("/hubs/skill/{hub_id}/cards/{card_id}/install")
async def install_skill_card(
    user: Annotated[User, Depends(get_current_user)],
    hub_id: str,
    card_id: str,
    name: Annotated[str | None, Query(max_length=100)] = None,
) -> dict:
    _require_admin(user)
    params = {"name": name} if name else None
    try:
        return await get_runtime_client().relay_json(
            "POST",
            f"/hub/skill/{hub_id}/cards/{card_id}/install",
            params=params,
            body={},
        )  # type: ignore[return-value]
    except RuntimeCallError as exc:
        raise _flow_http(exc)


# ---------- shared library (sys:runtime's MCPs / skills) ----------

@router.get("/mcp-library")
async def list_mcp_library(user: Annotated[User, Depends(get_current_user)]) -> list:
    del user
    try:
        return await get_runtime_client().relay_json("GET", "/mcp")  # type: ignore[return-value]
    except RuntimeCallError as exc:
        raise _flow_http(exc)


@router.patch("/mcp-library/{mcp_id}")
async def update_mcp_library(
    mcp_id: str,
    user: Annotated[User, Depends(get_current_user)],
    body: dict = Body(default_factory=dict),
) -> dict:
    _require_admin(user)
    try:
        return await get_runtime_client().relay_json(
            "PATCH", f"/mcp/{mcp_id}", body=body
        )  # type: ignore[return-value]
    except RuntimeCallError as exc:
        raise _flow_http(exc)


@router.delete("/mcp-library/{mcp_id}", status_code=204)
async def delete_mcp_library(
    mcp_id: str, user: Annotated[User, Depends(get_current_user)] = None
) -> None:
    _require_admin(user)
    try:
        await get_runtime_client().relay_json("DELETE", f"/mcp/{mcp_id}")
    except RuntimeCallError as exc:
        raise _flow_http(exc)


@router.get("/skill-library")
async def list_skill_library(user: Annotated[User, Depends(get_current_user)]) -> list:
    del user
    try:
        return await get_runtime_client().relay_json("GET", "/skill")  # type: ignore[return-value]
    except RuntimeCallError as exc:
        raise _flow_http(exc)


@router.get("/skill-library/{skill_id}")
async def get_skill_library(
    skill_id: str, user: Annotated[User, Depends(get_current_user)] = None
) -> dict:
    del user
    try:
        return await get_runtime_client().relay_json(
            "GET", f"/skill/{skill_id}"
        )  # type: ignore[return-value]
    except RuntimeCallError as exc:
        raise _flow_http(exc)


@router.delete("/skill-library/{skill_id}", status_code=204)
async def delete_skill_library(
    skill_id: str, user: Annotated[User, Depends(get_current_user)] = None
) -> None:
    _require_admin(user)
    try:
        await get_runtime_client().relay_json("DELETE", f"/skill/{skill_id}")
    except RuntimeCallError as exc:
        raise _flow_http(exc)
