# -*- coding: utf-8 -*-
"""Offline Skill Hub for local_eval — no network, serves demo_skills."""
from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import AsyncIterator

import frontmatter

from agentscope.app.hub import (
    SkillArchive,
    SkillCard,
    SkillHubBase,
    SkillHubPage,
)

_DEMO_SKILLS_DIR = Path(__file__).resolve().parent / "demo_skills"

_HUB_ID = "local-eval"


def _titleize(slug: str) -> str:
    return " ".join(part.capitalize() for part in slug.replace("_", "-").split("-"))


def _zip_folder(root: Path) -> bytes:
    """Zip every file under ``root``, paths relative to ``root`` itself."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        for path in sorted(root.rglob("*")):
            if path.is_file():
                archive.write(path, arcname=str(path.relative_to(root)))
    return buf.getvalue()


def _load_cards() -> dict[str, tuple[SkillCard, Path]]:
    """Build one card per ``demo_skills/<slug>/SKILL.md``.

    Folders without a readable SKILL.md, or whose frontmatter lacks the
    ``name`` / ``description`` the runtime loader requires, are skipped
    rather than raising — one broken demo folder should not take the
    whole service down at import time.
    """
    if not _DEMO_SKILLS_DIR.is_dir():
        raise FileNotFoundError(
            f"LocalEvalSkillHub needs {_DEMO_SKILLS_DIR}. "
            "Restore examples/local_eval/demo_skills/ and restart.",
        )

    cards: dict[str, tuple[SkillCard, Path]] = {}
    for folder in sorted(p for p in _DEMO_SKILLS_DIR.iterdir() if p.is_dir()):
        skill_md = folder / "SKILL.md"
        if not skill_md.is_file():
            continue
        text = skill_md.read_text(encoding="utf-8")
        meta = frontmatter.loads(text)
        name = str(meta.get("name") or "").strip()
        description = " ".join(
            str(meta.get("description") or "").split(),
        )
        if not name or not description:
            continue
        cards[folder.name] = (
            SkillCard(
                hub_id=_HUB_ID,
                id=folder.name,
                name=name,
                display_name=_titleize(folder.name),
                description=description,
                tags=["eval"],
                author="local-eval",
                version="1.0.0",
                markdown=text,
            ),
            folder,
        )

    if not cards:
        raise FileNotFoundError(
            f"No usable skill found under {_DEMO_SKILLS_DIR}. Each skill "
            "needs a folder with a SKILL.md carrying name + description.",
        )
    return cards


class LocalEvalSkillHub(SkillHubBase):
    """Hub backed by every folder under ``demo_skills/``."""

    def __init__(self) -> None:
        super().__init__(
            hub_id=_HUB_ID,
            display_name="Local Eval Skill Hub",
            description="Offline catalog for AgentScope local_eval.",
        )
        self._entries = _load_cards()

    async def list_skills(
        self,
        user_id: str,
        q: str | None = None,
        cursor: str | None = None,
        limit: int = 20,
    ) -> SkillHubPage:
        cards = [card for card, _ in self._entries.values()]
        if q:
            needle = q.lower()
            cards = [
                card
                for card in cards
                if needle in card.name.lower()
                or needle in card.display_name.lower()
                or needle in card.description.lower()
            ]
        return SkillHubPage(cards=cards[:limit])

    async def get_skill(self, user_id: str, card_id: str) -> SkillCard:
        if card_id not in self._entries:
            raise KeyError(card_id)
        return self._entries[card_id][0]

    async def download(
        self,
        user_id: str,
        card_id: str,
        version: str | None = None,
    ) -> SkillArchive:
        if card_id not in self._entries:
            raise KeyError(card_id)

        payload = _zip_folder(self._entries[card_id][1])

        async def _stream() -> AsyncIterator[bytes]:
            yield payload

        return SkillArchive(format="zip", stream=_stream())
