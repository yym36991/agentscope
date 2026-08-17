# -*- coding: utf-8 -*-
"""Offline Skill Hub for local_eval — no network, serves demo_skills."""
from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import AsyncIterator

from agentscope.app.hub import (
    SkillArchive,
    SkillCard,
    SkillHubBase,
    SkillHubPage,
)

_DEMO_SKILL = (
    Path(__file__).resolve().parent / "demo_skills" / "greet-eval" / "SKILL.md"
)


def _load_skill_md() -> str:
    if not _DEMO_SKILL.is_file():
        raise FileNotFoundError(
            f"LocalEvalSkillHub needs {_DEMO_SKILL}. "
            "Restore examples/local_eval/demo_skills/greet-eval/SKILL.md "
            "and restart.",
        )
    return _DEMO_SKILL.read_text(encoding="utf-8")


def _zip_bytes(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        for name, text in files.items():
            archive.writestr(name, text)
    return buf.getvalue()


class LocalEvalSkillHub(SkillHubBase):
    """One-card hub backed by ``demo_skills/greet-eval``."""

    def __init__(self) -> None:
        super().__init__(
            hub_id="local-eval",
            display_name="Local Eval Skill Hub",
            description="Offline catalog for AgentScope local_eval.",
        )
        skill_md = _load_skill_md()
        self._card = SkillCard(
            hub_id="local-eval",
            id="greet-eval",
            name="greet-eval",
            display_name="Greet Eval",
            description=(
                "Eval greeting skill. Use when the user asks to greet "
                "via skill."
            ),
            tags=["eval"],
            author="local-eval",
            version="1.0.0",
            markdown=skill_md,
        )
        self._skill_md = skill_md

    async def list_skills(
        self,
        user_id: str,
        q: str | None = None,
        cursor: str | None = None,
        limit: int = 20,
    ) -> SkillHubPage:
        cards = [self._card]
        if q and q.lower() not in self._card.name.lower():
            cards = []
        return SkillHubPage(cards=cards[:limit])

    async def get_skill(self, user_id: str, card_id: str) -> SkillCard:
        if card_id != self._card.id:
            raise KeyError(card_id)
        return self._card

    async def download(
        self,
        user_id: str,
        card_id: str,
        version: str | None = None,
    ) -> SkillArchive:
        if card_id != self._card.id:
            raise KeyError(card_id)

        payload = _zip_bytes({"SKILL.md": self._skill_md})

        async def _stream() -> AsyncIterator[bytes]:
            yield payload

        return SkillArchive(format="zip", stream=_stream())
