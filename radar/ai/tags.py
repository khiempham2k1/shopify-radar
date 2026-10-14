"""Tag set derived from interests.txt (TrendRadar's two-stage AI filter, step 1).

Tags are versioned by a hash of interests.txt. When the file changes, Claude
compares old tags with the new text: a small change keeps existing results and
only adds/removes tags; a large change (change_ratio ≥ reclassify_threshold)
deprecates everything so recent items are classified again.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from radar.ai.client import CallSpec, ClaudeClient
from radar.config_loader import RadarConfig, load_prompt
from radar.models import AIAnalyzed, AIResult, AITag, utcnow

log = logging.getLogger(__name__)

TAGS_SCHEMA = {
    "type": "object",
    "properties": {
        "tags": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"tag": {"type": "string"}, "description": {"type": "string"}},
                "required": ["tag", "description"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["tags"],
    "additionalProperties": False,
}

UPDATE_SCHEMA = {
    "type": "object",
    "properties": {
        "keep_ids": {"type": "array", "items": {"type": "integer"}},
        "add": TAGS_SCHEMA["properties"]["tags"],
        "change_ratio": {"type": "number"},
    },
    "required": ["keep_ids", "add", "change_ratio"],
    "additionalProperties": False,
}


@dataclass
class TagSync:
    tags: list[AITag]
    changed: bool
    full_reclassify: bool


def active_tags(session: Session) -> list[AITag]:
    return list(session.scalars(select(AITag).where(AITag.status == "active").order_by(AITag.priority, AITag.id)))


def _current_hash(session: Session) -> str | None:
    return session.scalar(select(AITag.prompt_hash).where(AITag.status == "active").order_by(AITag.id.desc()).limit(1))


def _next_version(session: Session) -> int:
    return (session.scalar(select(AITag.version).order_by(AITag.version.desc()).limit(1)) or 0) + 1


def _add_tags(session: Session, entries: list[dict], start_priority: int, version: int, prompt_hash: str) -> None:
    for offset, entry in enumerate(entries):
        name = (entry.get("tag") or "").strip()
        if name:
            session.add(
                AITag(
                    tag=name[:200],
                    description=(entry.get("description") or "").strip(),
                    priority=start_priority + offset,
                    status="active",
                    version=version,
                    prompt_hash=prompt_hash,
                )
            )


def sync_tags(session: Session, config: RadarConfig, claude: ClaudeClient) -> TagSync:
    current = config.interests_hash
    stored = _current_hash(session)
    tags = active_tags(session)
    if stored == current and tags:
        return TagSync(tags=tags, changed=False, full_reclassify=False)
    if not config.interests:
        raise ValueError("interests.txt đang trống")

    version = _next_version(session)
    now = utcnow()
    effort = config.ai.get("classify_effort", "low")

    if not tags:
        prompt = load_prompt("extract_tags", interests=config.interests)
        data = claude.call_json(CallSpec("tags", prompt.system, prompt.user, TAGS_SCHEMA, effort=effort, max_tokens=4000))
        _add_tags(session, data["tags"], 1, version, current)
        session.flush()
        return TagSync(tags=active_tags(session), changed=True, full_reclassify=True)

    old = "\n".join(f"{t.id}. {t.tag} — {t.description}" for t in tags)
    prompt = load_prompt("update_tags", interests=config.interests, old_tags=old)
    data = claude.call_json(CallSpec("tags", prompt.system, prompt.user, UPDATE_SCHEMA, effort=effort, max_tokens=4000))
    threshold = float(config.ai.get("reclassify_threshold", 0.6))
    full = float(data.get("change_ratio", 1.0)) >= threshold
    keep = set() if full else {int(i) for i in data.get("keep_ids", [])}

    removed = [t.id for t in tags if t.id not in keep]
    if removed:
        session.execute(update(AITag).where(AITag.id.in_(removed)).values(status="deprecated", deprecated_at=now))
        session.execute(update(AIResult).where(AIResult.tag_id.in_(removed)).values(status="deprecated"))
    for t in tags:
        if t.id in keep:
            t.prompt_hash = current
    new_entries = data.get("add", [])
    if full:
        # Large change: rebuild the tag set from scratch and classify recent items again.
        prompt = load_prompt("extract_tags", interests=config.interests)
        new_entries = claude.call_json(
            CallSpec("tags", prompt.system, prompt.user, TAGS_SCHEMA, effort=effort, max_tokens=4000)
        )["tags"]
        session.execute(delete(AIAnalyzed))
    start = max((t.priority for t in tags if t.id in keep), default=0) + 1
    _add_tags(session, new_entries, start, version, current)
    session.flush()
    log.info("Tags updated: kept %d, removed %d, added %d, full=%s", len(keep), len(removed), len(new_entries), full)
    return TagSync(tags=active_tags(session), changed=True, full_reclassify=full)
