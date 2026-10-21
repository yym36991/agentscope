# -*- coding: utf-8 -*-
"""Anti-corruption layer to the AgentScope runtime (architecture.md §8.7).

This is the ONLY module in the platform allowed to talk to the runtime
(see the README boundary section). Everything it sends goes out as the
single service principal ``sys:runtime`` (§8.2) — platform users never
leak past this boundary.

The surface is deliberately narrow: the six operations the stage flow
needs, in typed wrappers, so a runtime API change shows up here as one
edit instead of scattered HTTP calls.
"""
from functools import lru_cache

import httpx

from app.config import get_settings


class RuntimeCallError(Exception):
    """A runtime call failed; ``status`` maps to the HTTP code.

    Mirrors :class:`app.services.flow.FlowError` so the API layer can
    translate both with one helper.
    """

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


class RuntimeClient:
    """Thin typed wrapper over the runtime's HTTP API."""

    def __init__(self) -> None:
        settings = get_settings()
        self._base_url = settings.runtime_base_url.rstrip("/")
        self._principal = settings.runtime_principal
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={"X-User-ID": self._principal},
            timeout=10.0,
        )
        # agent name -> agent id, filled by find_agent_by_name; the
        # platform seeds its agents once, so process-lifetime is enough.
        self._agent_ids: dict[str, str] = {}

    async def aclose(self) -> None:
        await self._client.aclose()

    # ---------- transport ----------

    async def _request(
        self, method: str, path: str, *, raw: bool = False, **kwargs: object
    ) -> object:
        """One request as sys:runtime; maps transport failures to 503/502.

        ``raw=True`` returns the body as text instead of JSON — for the
        workspace file endpoints, which stream raw bytes.
        """
        try:
            resp = await self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise RuntimeCallError(
                503, f"runtime unreachable at {self._base_url}: {exc}"
            ) from exc
        if resp.status_code >= 400:
            raise RuntimeCallError(
                502, f"runtime {method} {path} -> {resp.status_code}: {resp.text[:200]}"
            )
        if resp.status_code == 204 or not resp.content:
            return None
        return resp.text if raw else resp.json()

    # ---------- agents ----------

    async def find_agent_by_name(self, name: str) -> str | None:
        """Agent id for *name* (None if absent), with a small cache."""
        if name in self._agent_ids:
            return self._agent_ids[name]
        data = await self._request("GET", "/agent/")
        for agent in data["agents"]:  # type: ignore[index]
            agent_name = (agent.get("data") or {}).get("name") or agent.get(
                "name"
            )
            if agent_name == name:
                self._agent_ids[name] = agent["id"]
                return agent["id"]
        return None

    async def create_agent(self, name: str, system_prompt: str) -> str:
        """Seed an agent owned by sys:runtime; returns its id."""
        data = await self._request(
            "POST",
            "/agent/",
            json={"name": name, "system_prompt": system_prompt},
        )
        agent_id = data["agent_id"]  # type: ignore[index]
        self._agent_ids[name] = agent_id
        return agent_id

    # ---------- credentials ----------

    async def list_credentials(self) -> list[dict]:
        """Credentials under sys:runtime — SAFE PROJECTION ONLY.

        The runtime response carries the raw ``api_key``; it is dropped
        here and must never be logged or returned. Callers get
        ``{id, name, type}`` and that is all the platform needs.
        """
        data = await self._request("GET", "/credential/")
        safe = []
        for cred in data["credentials"]:  # type: ignore[index]
            payload = cred.get("data") or {}
            safe.append(
                {
                    "id": cred.get("id"),
                    "name": payload.get("name") or cred.get("name"),
                    "type": payload.get("type"),
                }
            )
        return safe

    async def default_chat_model_config(self) -> dict | None:
        """Platform-default ChatModelConfig, or None if unconfigured.

        Model choice is a platform setting; the credential is whatever
        the operator registered under sys:runtime first (exactly one in
        M1). Sessions created while this is None get PATCHed later by
        the chat relay once a credential shows up.
        """
        creds = await self.list_credentials()
        if not creds:
            return None
        return {
            "type": creds[0]["type"] or "anthropic",
            "credential_id": creds[0]["id"],
            "model": get_settings().runtime_model,
            "parameters": {},
        }

    # ---------- sessions ----------

    async def create_session(
        self, agent_id: str, name: str, chat_model_config: dict | None
    ) -> str:
        """Open a session (upsert per principal+agent+workspace).

        ``chat_model_config`` may be None — the chat relay self-heals
        it via PATCH once a credential exists.
        """
        body: dict = {"agent_id": agent_id, "name": name}
        if chat_model_config is not None:
            body["chat_model_config"] = chat_model_config
        data = await self._request("POST", "/sessions/", json=body)
        return data["session_id"]  # type: ignore[index]

    async def update_session_model(
        self, agent_id: str, session_id: str, chat_model_config: dict
    ) -> None:
        """Replace a session's chat model config (self-heal path)."""
        await self._request(
            "PATCH",
            f"/sessions/{session_id}",
            params={"agent_id": agent_id},
            json={"chat_model_config": chat_model_config},
        )

    async def set_session_permission_mode(
        self, agent_id: str, session_id: str, mode: str
    ) -> None:
        """Set the session's permission mode (e.g. ``accept_edits``).

        The runtime rejects this with 409 while a run holds the session,
        so apply it while the reply is parked (``awaiting_permission``).
        """
        await self._request(
            "PATCH",
            f"/sessions/{session_id}",
            params={"agent_id": agent_id},
            json={"permission_mode": mode},
        )

    # ---------- chat ----------

    async def send_message(
        self, agent_id: str, session_id: str, text: str
    ) -> None:
        """Fire-and-forget user message; output lands on the SSE stream."""
        await self._request(
            "POST",
            "/chat/",
            json={
                "agent_id": agent_id,
                "session_id": session_id,
                "input": {
                    "name": "user",
                    "role": "user",
                    "content": [{"type": "text", "text": text}],
                },
            },
        )

    async def confirm_tool_calls(
        self,
        agent_id: str,
        session_id: str,
        reply_id: str,
        tool_calls: list[dict],
        confirmed: bool,
    ) -> None:
        """Answer the runtime's human-in-the-loop permission prompt.

        *tool_calls* are the asking tool-call blocks (echoed back by
        id/name/input); the runtime resumes the parked reply with the
        verdict.
        """
        await self._request(
            "POST",
            "/chat/",
            json={
                "agent_id": agent_id,
                "session_id": session_id,
                "input": {
                    "type": "USER_CONFIRM_RESULT",
                    "reply_id": reply_id,
                    "confirm_results": [
                        {
                            "confirmed": confirmed,
                            "tool_call": {
                                "type": "tool_call",
                                "id": b["id"],
                                "name": b["name"],
                                "input": b["input"],
                            },
                        }
                        for b in tool_calls
                    ],
                },
            },
        )

    async def get_messages(
        self, agent_id: str, session_id: str
    ) -> dict:
        """Latest messages plus is_running, for polling clients."""
        data = await self._request(
            "GET",
            f"/sessions/{session_id}/messages",
            params={"agent_id": agent_id},
        )
        return {
            "messages": data["messages"],  # type: ignore[index]
            "is_running": data["is_running"],  # type: ignore[index]
            "has_more": data.get("has_more", False),  # type: ignore[union-attr]
            "event_cursor": data.get("event_cursor"),  # type: ignore[union-attr]
        }

    # ---------- workspace ----------

    async def list_workspace_dir(
        self, agent_id: str, session_id: str, path: str = ""
    ) -> list[dict]:
        """One directory level of a session's workspace.

        Empty *path* = workspace root. Each entry is
        ``{name, is_dir, size_bytes}`` (runtime's DirectoryListing).
        """
        data = await self._request(
            "GET",
            "/workspace/directories",
            params={"agent_id": agent_id, "session_id": session_id, "path": path},
        )
        return data["entries"]  # type: ignore[index]

    async def read_workspace_file(
        self, agent_id: str, session_id: str, path: str
    ) -> str:
        """One workspace file as text (runtime streams raw bytes)."""
        return await self._request(  # type: ignore[return-value]
            "GET",
            "/workspace/files",
            params={"agent_id": agent_id, "session_id": session_id, "path": path},
            raw=True,
        )


@lru_cache
def get_runtime_client() -> RuntimeClient:
    return RuntimeClient()
