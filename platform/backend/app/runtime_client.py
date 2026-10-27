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
import itertools
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
    """Thin typed wrapper over the runtime's HTTP API.

    One client per runtime base URL: with ``runtime_base_urls`` set
    (architecture.md §10.1) requests round-robin across replicas and a
    connect-phase failure (replica down, request never delivered) falls
    through to the next one. Only connect errors are retried — a
    read timeout after delivery must not re-send a POST.
    """

    def __init__(self) -> None:
        settings = get_settings()
        urls = [
            u.strip().rstrip("/")
            for u in (settings.runtime_base_urls or "").split(",")
            if u.strip()
        ] or [settings.runtime_base_url.rstrip("/")]
        self._base_urls = urls
        self._principal = settings.runtime_principal
        self._clients = [
            httpx.AsyncClient(
                base_url=url,
                headers={"X-User-ID": self._principal},
                timeout=10.0,
                # Runtime endpoints are internal (localhost / intranet):
                # never route them through a user's system proxy. With
                # trust_env=True httpx picks up the Windows registry
                # proxy, which turns a dead replica into a proxy 502
                # instead of a connect error — breaking failover (and
                # leaking internal traffic to an external hop).
                trust_env=False,
            )
            for url in urls
        ]
        self._rr = itertools.count()
        # agent name -> agent id, filled by find_agent_by_name; the
        # platform seeds its agents once, so process-lifetime is enough.
        self._agent_ids: dict[str, str] = {}

    async def aclose(self) -> None:
        for client in self._clients:
            await client.aclose()

    # ---------- transport ----------

    async def _request(
        self, method: str, path: str, *, raw: bool = False, **kwargs: object
    ) -> object:
        """One request as sys:runtime; maps transport failures to 503/502.

        ``raw=True`` returns the body as text instead of JSON — for the
        workspace file endpoints, which stream raw bytes.
        """
        n = len(self._clients)
        start = next(self._rr) % n
        last_exc: Exception | None = None
        for i in range(n):
            client = self._clients[(start + i) % n]
            try:
                resp = await client.request(method, path, **kwargs)
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                # Replica down before the request was delivered — safe
                # to try the next one for any method, including POSTs.
                last_exc = exc
                continue
            except httpx.HTTPError as exc:
                raise RuntimeCallError(
                    503, f"runtime unreachable at {client.base_url}: {exc}"
                ) from exc
            if resp.status_code >= 400:
                # 404/409 keep their meaning (not found / session busy) so
                # callers can react; anything else is an unexpected runtime
                # failure and maps to 502.
                status = (
                    resp.status_code if resp.status_code in (404, 409) else 502
                )
                raise RuntimeCallError(
                    status,
                    f"runtime {method} {path} -> {resp.status_code}: {resp.text[:200]}",
                )
            if resp.status_code == 204 or not resp.content:
                return None
            return resp.text if raw else resp.json()
        raise RuntimeCallError(
            503,
            f"runtime unreachable at all {n} replica(s) "
            f"({', '.join(self._base_urls)}): {last_exc}",
        )

    # ---------- agents ----------

    async def find_agent_record(self, name: str) -> dict | None:
        """Full agent record for *name* (None if absent).

        The seed refresh path diffs the stored system_prompt against
        its target and PATCHes on change — the record, not just the id.
        """
        data = await self._request("GET", "/agent/")
        for agent in data["agents"]:  # type: ignore[index]
            agent_name = (agent.get("data") or {}).get("name") or agent.get(
                "name"
            )
            if agent_name == name:
                return agent
        return None

    async def find_agent_by_name(self, name: str) -> str | None:
        """Agent id for *name* (None if absent), with a small cache."""
        if name in self._agent_ids:
            return self._agent_ids[name]
        agent = await self.find_agent_record(name)
        if agent is None:
            return None
        self._agent_ids[name] = agent["id"]
        return agent["id"]

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

    async def update_agent(self, agent_id: str, *, system_prompt: str) -> None:
        """Replace an agent's system prompt (seed refresh path).

        Partial PATCH: id, name, workspace and skills stay put, so
        existing sessions and the skill partition are unaffected —
        only future replies pick up the new prompt.
        """
        await self._request(
            "PATCH",
            f"/agent/{agent_id}",
            json={"system_prompt": system_prompt},
        )

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

    async def build_chat_model_config(self, model: str | None = None) -> dict | None:
        """ChatModelConfig for *model* (default: the platform default).

        None if no credential exists yet — the caller decides whether
        to create the session bare and self-heal later via PATCH.
        The credential is whatever the operator registered under
        sys:runtime first; per-stage model choice rides on ``model``.
        """
        creds = await self.list_credentials()
        if not creds:
            return None
        return {
            "type": creds[0]["type"] or "anthropic",
            "credential_id": creds[0]["id"],
            "model": model or get_settings().runtime_model,
            "parameters": {},
        }

    # ---------- sessions ----------

    async def create_session(
        self,
        agent_id: str,
        name: str,
        chat_model_config: dict | None,
        workspace_id: str | None = None,
        kb_ids: list[str] | None = None,
    ) -> str:
        """Open a new session; returns its id.

        ``chat_model_config`` may be None — the chat relay self-heals
        it via PATCH once a credential exists. ``workspace_id`` is the
        §8.5 explicit binding (doc stages share the project workspace,
        the testing stage gets a per-run one). ``kb_ids`` mounts the
        RAG middleware (§7.2) — None/empty means no KB wired.
        """
        body: dict = {"agent_id": agent_id, "name": name}
        if chat_model_config is not None:
            body["chat_model_config"] = chat_model_config
        if workspace_id is not None:
            body["workspace_id"] = workspace_id
        if kb_ids:
            body["knowledge_config"] = {
                "knowledge_base_ids": kb_ids,
                "parameters": {},
            }
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

    # ---------- knowledge bases ----------

    async def embedding_model_config(self) -> dict | None:
        """EmbeddingModelConfig for KB creation, or None if the runtime
        has no OpenAI-compatible credential yet.

        The operator registers it under sys:runtime (zhipu's
        OpenAI-compatible endpoint serves embedding-3); until then KB
        creation fails with a clear message and RAG stays off —
        chat keeps working, matching the best-effort skill installs.
        """
        creds = await self.list_credentials()
        for cred in creds:
            if cred["type"] == "openai_credential":
                return {
                    "type": "openai_credential",
                    "credential_id": cred["id"],
                    "model": get_settings().runtime_embedding_model,
                    "dimensions": get_settings().runtime_embedding_dimensions,
                }
        return None

    async def create_kb(self, name: str, description: str = "") -> str:
        """Create a runtime KB under sys:runtime; returns its id.

        The embedding model is pinned at creation (runtime rule);
        dimensions come from settings and must match the model.
        """
        embedding = await self.embedding_model_config()
        if embedding is None:
            raise RuntimeCallError(
                503,
                "运行时还没有可用于向量化的凭证（sys:runtime 名下缺少 "
                "openai 类型 credential）——请管理员在运维控制台注册后再"
                "创建知识库",
            )
        data = await self._request(
            "POST",
            "/knowledge_bases/",
            json={
                "name": name,
                "description": description,
                "embedding_model_config": embedding,
            },
        )
        return data["knowledge_base_id"]  # type: ignore[index]

    async def upload_kb_document(
        self,
        kb_id: str,
        filename: str,
        data: bytes,
        content_type: str | None = None,
    ) -> dict:
        """Register a document for indexing (async on the runtime)."""
        return await self._request(  # type: ignore[return-value]
            "POST",
            f"/knowledge_bases/{kb_id}/documents",
            files={"file": (filename, data, content_type)},
        )

    async def delete_kb(self, kb_id: str) -> None:
        """Drop a runtime KB; its documents and vectors go with it."""
        await self._request("DELETE", f"/knowledge_bases/{kb_id}")

    async def list_kb_documents(self, kb_id: str) -> list[dict]:
        data = await self._request(
            "GET", f"/knowledge_bases/{kb_id}/documents"
        )
        return data.get("documents", [])  # type: ignore[union-attr]

    async def kb_document_status(self, kb_id: str) -> list[dict]:
        data = await self._request(
            "GET", f"/knowledge_bases/{kb_id}/documents/status"
        )
        return data.get("documents", [])  # type: ignore[union-attr]

    async def search_kb(
        self, kb_id: str, query: str, top_k: int = 5
    ) -> list[dict]:
        data = await self._request(
            "POST",
            f"/knowledge_bases/{kb_id}/search",
            json={"query": query, "top_k": top_k},
        )
        return data.get("results", [])  # type: ignore[union-attr]

    async def update_session_knowledge(
        self, agent_id: str, session_id: str, kb_ids: list[str]
    ) -> None:
        """(Re)bind the session's RAG mount (§7.2: the stage's usable
        KBs, already intersected with the sender's visibility)."""
        await self._request(
            "PATCH",
            f"/sessions/{session_id}",
            params={"agent_id": agent_id},
            json={
                "knowledge_config": {
                    "knowledge_base_ids": kb_ids,
                    "parameters": {},
                }
            },
        )

    # ---------- resource hubs & shared library ----------

    async def relay_json(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        body: dict | None = None,
    ) -> object:
        """Forward one hub / library call to the runtime as sys:runtime.

        The hub pages browse registries (GitHub, ClawHub) and manage the
        single shared library the six stage agents draw from, so there is
        no per-user projection to apply — the runtime's JSON passes
        through unchanged. The API layer owns the authz split (browse for
        everyone, install/edit for admins).
        """
        kwargs: dict[str, object] = {}
        if params is not None:
            kwargs["params"] = params
        if body is not None:
            kwargs["json"] = body
        return await self._request(method, path, **kwargs)

    # ---------- skills ----------

    async def add_workspace_skill(
        self, agent_id: str, session_id: str, skill_path: str
    ) -> None:
        """Install a local skill dir into the agent's workspace partition.

        Deliberately uses the runtime's deprecated path-based endpoint:
        the platform and runtime are co-deployed on one host with a
        shared filesystem, and the path call is the simplest contract
        (a multi-instance deployment would switch to the folder-upload
        endpoint). Re-installing an unchanged skill is a no-op on the
        runtime side (SKILL.md hash dedup), so callers may retry freely.
        """
        await self._request(
            "POST",
            "/workspace/skill",
            params={"agent_id": agent_id, "session_id": session_id},
            json={"skill_path": skill_path},
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

    async def get_session_status(self, agent_id: str, session_id: str) -> str:
        """Unified session status.

        One of ``running`` / ``idle`` / ``awaiting_permission`` /
        ``awaiting_external_result`` — cluster liveness plus the
        parking state derived from the persisted agent state (the
        message list alone can go stale after a failed reply).
        """
        data = await self._request(
            "GET",
            f"/sessions/{session_id}/status",
            params={"agent_id": agent_id},
        )
        return data["status"]  # type: ignore[index]

    async def interrupt_session(self, agent_id: str, session_id: str) -> None:
        """Abort a running or HITL-parked reply (idempotent on idle).

        The escape hatch for a parked session whose confirmation can no
        longer be answered — the parked tool calls close as interrupted
        and the session returns to idle.
        """
        await self._request(
            "POST",
            f"/sessions/{session_id}/interrupt",
            params={"agent_id": agent_id},
        )

    # ---------- chat ----------

    async def send_message(
        self,
        agent_id: str,
        session_id: str,
        text: str,
        blocks: list[dict] | None = None,
        speaker: str = "user",
    ) -> None:
        """Fire-and-forget user message; output lands on the SSE stream.

        *speaker* is the Msg name — display-level attribution of which
        project member said this (the audit "who said what"), not an
        identity: the request still goes out as sys:runtime and the
        runtime grants nothing based on the name.

        *blocks* are extra content blocks appended after the text —
        e.g. the DataBlock of an uploaded file (base64 image/PDF) or an
        inlined TextBlock. Text alone is the plain chat path.
        """
        content: list[dict] = []
        if text:
            content.append({"type": "text", "text": text})
        if blocks:
            content += blocks
        if not content:
            return
        await self._request(
            "POST",
            "/chat/",
            json={
                "agent_id": agent_id,
                "session_id": session_id,
                "input": {
                    "name": speaker,
                    "role": "user",
                    "content": content,
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
