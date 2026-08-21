# -*- coding: utf-8 -*-
"""Keep intel-team handoffs inside ChatLing's request budget.

``default_mcps`` seeds Tavily onto every workspace, so invited experts
see search tools they must not use; Leader also tends to TeamSay the
full retrieval dump. Either one can 400 the model. This middleware:

- drops ``tavily_*`` from the model tool list unless the agent is the
  retrieval expert;
- caps ``TeamSay.content`` so a oversized dump is truncated before the
  recipient is woken.
"""
from __future__ import annotations

import json
from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import Any

from agentscope.middleware import MiddlewareBase

_SEARCH_AGENT_NAME = "信息检索"
_TEAMSAY_MAX_CHARS = 4000
_TRUNCATE_MARK = "\n\n…(已截断。请只用以上编号条目分析，不要要求补全文。)"


def _tool_name(schema: dict) -> str:
    fn = schema.get("function")
    if isinstance(fn, dict) and fn.get("name"):
        return str(fn["name"])
    return str(schema.get("name") or "")


def _truncate_teamsay_input(raw: str) -> str:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        if len(raw) <= _TEAMSAY_MAX_CHARS:
            return raw
        return raw[:_TEAMSAY_MAX_CHARS] + _TRUNCATE_MARK
    content = payload.get("content")
    if not isinstance(content, str) or len(content) <= _TEAMSAY_MAX_CHARS:
        return raw
    payload["content"] = content[:_TEAMSAY_MAX_CHARS] + _TRUNCATE_MARK
    return json.dumps(payload, ensure_ascii=False)


class IntelHandoffMiddleware(MiddlewareBase):
    """Strip search tools for non-retrievers; cap TeamSay payload size."""

    async def on_model_call(
        self,
        agent: Any,
        input_kwargs: dict,
        next_handler: Callable[..., Awaitable[Any]],
    ) -> Any:
        if getattr(agent, "name", None) != _SEARCH_AGENT_NAME:
            tools = list(input_kwargs.get("tools") or [])
            input_kwargs["tools"] = [
                schema
                for schema in tools
                if "tavily" not in _tool_name(schema).lower()
            ]
        return await next_handler(**input_kwargs)

    async def on_acting(
        self,
        agent: Any,
        input_kwargs: dict,
        next_handler: Callable[..., AsyncGenerator],
    ) -> AsyncGenerator:
        tool_call = input_kwargs.get("tool_call")
        if tool_call is not None and tool_call.name == "TeamSay":
            truncated = _truncate_teamsay_input(tool_call.input)
            if truncated != tool_call.input:
                tool_call.input = truncated
        async for item in next_handler(**input_kwargs):
            yield item
