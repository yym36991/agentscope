# -*- coding: utf-8 -*-
"""SDK smoke: primary model timeout/retry then fallback model.

Usage (from this directory, venv active, .env loaded):
    set -a && source .env && set +a
    python eval_timeout_retry.py

Flow:
  1. Primary (CHATLING_MODEL, default chatling-plus) with timeout=0.001
     and max_retries=2 → 3 timed-out attempts.
  2. Agent switches to fallback (CHATLING_FALLBACK_MODEL) with a normal
     timeout → should succeed.

Logs (console + logs/sdk_timeout_retry.log):
  - ``Attempt N failed ... Retrying``
  - ``All 3 attempt(s) failed``
  - ``Fallback to model '...'``
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from agentscope import setup_logger
from agentscope.agent import Agent
from agentscope.agent._config import ModelConfig
from agentscope.credential import OpenAICredential
from agentscope.message import UserMsg
from agentscope.model import OpenAIChatModel

_here = Path(__file__).resolve().parent
_log_dir = _here / "logs"
_log_dir.mkdir(exist_ok=True)
_log_file = _log_dir / "sdk_timeout_retry.log"

setup_logger(
    os.getenv("AGENTSCOPE_LOG_LEVEL", "INFO"),
    filepath=str(_log_file),
)


def _require(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        print(f"Missing {name}. Source .env first.", file=sys.stderr)
        sys.exit(1)
    return value


async def _run_timeout_retry_then_fallback() -> None:
    primary_name = os.getenv("CHATLING_MODEL", "chatling-plus").strip()
    fallback_name = os.getenv(
        "CHATLING_FALLBACK_MODEL",
        "chatling-turbo-0729",
    ).strip()

    cred = OpenAICredential(
        api_key=_require("CHATLING_API_KEY"),
        base_url=_require("CHATLING_BASE_URL"),
    )

    # Primary: force timeout so ChatModelBase inner retry runs, then fails.
    primary = OpenAIChatModel(
        credential=cred,
        model=primary_name,
        stream=False,
        max_retries=2,
        retry_delay=0.5,
        client_kwargs={"timeout": 0.001},
        parameters=OpenAIChatModel.Parameters(temperature=0.4, top_p=0.6),
    )
    # Fallback: same credential/base_url, different model name, normal timeout.
    fallback = OpenAIChatModel(
        credential=cred,
        model=fallback_name,
        stream=False,
        max_retries=2,
        retry_delay=0.5,
        client_kwargs={"timeout": 60.0},
        parameters=OpenAIChatModel.Parameters(temperature=0.4, top_p=0.6),
    )

    agent = Agent(
        name="timeout-eval",
        model=primary,
        system_prompt="You are a short eval agent. Reply briefly in Chinese.",
        # Agent outer max_retries defaults to 0: one pass on primary, then
        # switch to fallback_model (primary's own max_retries still apply).
        model_config=ModelConfig(fallback_model=fallback),
    )

    print(f"Log file: {_log_file}")
    print(f"Primary={primary_name!r} (timeout=0.001) → fallback={fallback_name!r}")
    try:
        reply = await agent.reply(UserMsg(name="user", content="说一声你好"))
        print(f"Reply OK via fallback path: {reply}")
    except Exception as exc:  # pylint: disable=broad-except
        print(f"Final error: {type(exc).__name__}: {exc}")

    text = _log_file.read_text(encoding="utf-8")
    markers = ("Retrying", "All ", "Fallback to model", "exhausted all")
    excerpts = [
        line
        for line in text.splitlines()
        if any(m in line for m in markers)
    ]
    print("--- log excerpts ---")
    for line in excerpts[-15:]:
        print(line)


if __name__ == "__main__":
    asyncio.run(_run_timeout_retry_then_fallback())
