"""Load team-edited configuration.

Files live in config/. From Giai đoạn 2 the Settings page can save a new
version into the `settings` table; a saved version wins over the file.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

import yaml
from sqlalchemy.orm import Session

from radar.filter.keywords import KeywordConfig, parse_keywords
from radar.models import Setting
from radar.areas import Area, parse_areas
from radar.priority import PriorityTopic, parse_priorities
from radar.settings import get_settings

EDITABLE_FILES = ("sources.yaml", "keywords.txt", "priorities.txt", "impact_areas.txt", "interests.txt", "terms.txt")


def read_text(name: str, session: Session | None = None) -> str:
    if session is not None and name in EDITABLE_FILES:
        row = session.get(Setting, name)
        if row is not None:
            return row.value
    path = get_settings().config_dir / name
    return path.read_text(encoding="utf-8") if path.exists() else ""


def save_text(session: Session, name: str, value: str, user: str) -> None:
    if name not in EDITABLE_FILES:
        raise ValueError(f"Không sửa được {name}")
    validate_text(name, value)
    row = session.get(Setting, name)
    if row is None:
        session.add(Setting(key=name, value=value, updated_by=user))
    else:
        row.value = value
        row.updated_by = user


def validate_text(name: str, value: str) -> None:
    """Raise ValueError with a readable message when the new content cannot be used."""
    if name == "sources.yaml":
        data = yaml.safe_load(value) or {}
        if not isinstance(data, dict) or not isinstance(data.get("sources", []), list):
            raise ValueError("sources.yaml phải là một object có danh sách 'sources'")
        ids = [s.get("id") for s in data.get("sources", [])]
        if any(not i for i in ids):
            raise ValueError("Mỗi nguồn cần có 'id'")
        if len(ids) != len(set(ids)):
            raise ValueError("Có 'id' nguồn bị trùng")
    elif name == "keywords.txt":
        parse_keywords(value)
    elif name == "priorities.txt":
        parse_priorities(value)
    elif name == "impact_areas.txt":
        parse_areas(value)


@dataclass
class RadarConfig:
    raw: dict[str, Any]
    keywords: KeywordConfig
    interests: str
    terms: str
    sources: list[dict[str, Any]] = field(default_factory=list)
    priorities: list[PriorityTopic] = field(default_factory=list)
    areas: list[Area] = field(default_factory=list)

    def section(self, name: str) -> dict[str, Any]:
        return self.raw.get(name) or {}

    @property
    def ai(self) -> dict[str, Any]:
        return self.section("ai")

    @property
    def video(self) -> dict[str, Any]:
        return self.section("video")

    @property
    def scoring(self) -> dict[str, Any]:
        return self.section("scoring")

    @property
    def schedule(self) -> dict[str, Any]:
        return self.section("schedule")

    @property
    def official(self) -> dict[str, Any]:
        return self.section("official")

    @property
    def freshness(self) -> dict[str, Any]:
        return self.section("freshness")

    def max_age_days(self, source: dict[str, Any]) -> int:
        """Items published longer ago than this are skipped (0 = no limit, default 30)."""
        return int(source.get("max_age_days", self.freshness.get("max_age_days", 30)) or 0)

    @property
    def model(self) -> str:
        return self.ai.get("model", "claude-opus-5-5")

    @property
    def interests_hash(self) -> str:
        return hashlib.sha256(self.interests.strip().encode("utf-8")).hexdigest()[:16]


def load_config(session: Session | None = None) -> RadarConfig:
    raw = yaml.safe_load(read_text("sources.yaml", session)) or {}
    sources = [s for s in raw.get("sources", []) if s.get("enabled", True)]
    return RadarConfig(
        raw=raw,
        keywords=parse_keywords(read_text("keywords.txt", session)),
        interests=read_text("interests.txt", session).strip(),
        terms=read_text("terms.txt", session).strip(),
        sources=sources,
        priorities=parse_priorities(read_text("priorities.txt", session)),
        areas=parse_areas(read_text("impact_areas.txt", session)),
    )


@dataclass
class Prompt:
    system: str
    user: str


def load_prompt(name: str, **values: Any) -> Prompt:
    """Read config/prompts/<name>.txt and fill {placeholders} we were given.

    Only names passed in `values` are replaced, so literal braces in the prompt
    (for example JSON) are left alone.
    """
    text = (get_settings().config_dir / "prompts" / f"{name}.txt").read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace("{" + key + "}", str(value))
    parts = re.split(r"^\[(system|user)\]\s*$", text, flags=re.MULTILINE)
    sections: dict[str, str] = {}
    for i in range(1, len(parts) - 1, 2):
        sections[parts[i]] = parts[i + 1].strip()
    if "user" not in sections:
        raise ValueError(f"Prompt {name} thiếu phần [user]")
    return Prompt(system=sections.get("system", ""), user=sections["user"])
