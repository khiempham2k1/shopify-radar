"""Community talk (sources with kind: community — Discord, Shopify Community).

These items are not classified or rated one by one. Instead:

- every Shopify Community thread gets a short Vietnamese summary (one batched
  Claude call per run, effort low);
- a Vietnamese digest of everything said in the last `digest_hours` (24) is
  rebuilt at most every `digest_every_hours` and stored as a Report with
  kind "community": overview, topics, open questions, each pointing at the
  messages it comes from.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from radar.ai.client import CallSpec, ClaudeClient
from radar.config_loader import RadarConfig, load_prompt
from radar.models import Item, Report, Source, utcnow
from radar.settings import get_settings

log = logging.getLogger(__name__)

KIND = "community"
TOPIC_KINDS = ["question", "problem", "tip", "news", "discussion"]

DIGEST_SCHEMA = {
    "type": "object",
    "properties": {
        "overview": {"type": "string"},
        "topics": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                    "kind": {"type": "string", "enum": TOPIC_KINDS},
                    "sources": {"type": "array", "items": {"type": "string"}},
                    "item_ids": {"type": "array", "items": {"type": "integer"}},
                },
                "required": ["title", "summary", "kind", "sources", "item_ids"],
                "additionalProperties": False,
            },
        },
        "open_questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"text": {"type": "string"}, "item_ids": {"type": "array", "items": {"type": "integer"}}},
                "required": ["text", "item_ids"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["overview", "topics", "open_questions"],
    "additionalProperties": False,
}

SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "integer"}, "summary": {"type": "string"}},
                "required": ["id", "summary"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def when(item: Item) -> datetime:
    return _aware(item.published_at or item.first_seen)


def community_sources(session: Session) -> dict[str, Source]:
    return {s.id: s for s in session.scalars(select(Source).where(Source.kind == KIND))}


def window_items(session: Session, hours: int, now: datetime | None = None) -> list[Item]:
    """Community items said in the last `hours`, oldest first."""
    now = now or utcnow()
    since = now - timedelta(hours=hours)
    sources = community_sources(session)
    if not sources:
        return []
    rows = session.scalars(
        select(Item).where(Item.source_id.in_(list(sources)), func.coalesce(Item.published_at, Item.first_seen) >= since)
    )
    return sorted(rows, key=when)


def place(item: Item, sources: dict[str, Source]) -> str:
    """Where it was said: "Discord #general" or "Shopify Community"."""
    source = sources.get(item.source_id)
    name = source.name if source else item.source_id
    channel = (item.extra or {}).get("channel")
    return f"{name} #{channel}" if channel else name


def render(items: list[Item], sources: dict[str, Source], max_chars: int) -> tuple[str, int]:
    """Messages grouped by place, each place given an equal share of the budget
    (newest kept when a busy channel is cut). Returns (text, how many were included)."""
    tz = ZoneInfo(get_settings().timezone)
    groups: dict[str, list[Item]] = defaultdict(list)
    for item in items:
        groups[place(item, sources)].append(item)
    share = max_chars // max(1, len(groups))
    blocks, included = [], 0
    for name, group in groups.items():
        lines, used = [], 0
        for item in reversed(group):  # newest first while filling the share
            if item.media_type == "message":
                text = " ".join(item.content.split())[:400]
                reply = " ↪" if (item.extra or {}).get("reply_to") else ""
                line = f"[{item.id}] {when(item).astimezone(tz):%d/%m %H:%M}{reply} {item.author}: {text}"
            else:
                body = " ".join((item.content or "").split())[:700]
                line = f"[{item.id}] {when(item).astimezone(tz):%d/%m %H:%M} Chủ đề: {item.title}\n    {body}"
            if used + len(line) > share and lines:
                break
            lines.append(line)
            used += len(line) + 1
        included += len(lines)
        blocks.append(f"## {name} ({len(group)} tin)\n" + "\n".join(reversed(lines)))
    return "\n\n".join(blocks), included


def build_digest(session: Session, config: RadarConfig, claude: ClaudeClient, now: datetime | None = None) -> Report | None:
    settings = config.section("community")
    hours = int(settings.get("digest_hours", 24))
    now = now or utcnow()
    items = window_items(session, hours, now)
    if not items:
        return None
    sources = community_sources(session)
    text, included = render(items, sources, int(settings.get("max_chars", 80000)))
    tz = ZoneInfo(get_settings().timezone)
    start = now - timedelta(hours=hours)
    prompt = load_prompt(
        "community_digest",
        hours=hours,
        interests=config.interests,
        window=f"{start.astimezone(tz):%H:%M %d/%m} – {now.astimezone(tz):%H:%M %d/%m/%Y}",
        count=len(items),
        messages=text,
    )
    data = claude.call_json(
        CallSpec("community", prompt.system, prompt.user, DIGEST_SCHEMA, effort=settings.get("digest_effort", "medium"), max_tokens=16000)
    )
    known = {i.id for i in items}
    for section in ("topics", "open_questions"):
        for entry in data.get(section, []):
            entry["item_ids"] = [i for i in entry.get("item_ids", []) if i in known][:5]
    counts: dict[str, int] = defaultdict(int)
    for item in items:
        counts[place(item, sources)] += 1
    data.update(
        window_start=start.isoformat(),
        window_end=now.isoformat(),
        places=[{"name": name, "count": n} for name, n in sorted(counts.items(), key=lambda kv: -kv[1])],
        included=included,
    )
    report = Report(kind=KIND, period_start=start.astimezone(tz).date(), period_end=now.astimezone(tz).date(), content=data, items_considered=len(items), model=claude.model)
    session.add(report)
    session.flush()
    return report


def digest_due(session: Session, config: RadarConfig, now: datetime | None = None) -> bool:
    now = now or utcnow()
    every = float(config.section("community").get("digest_every_hours", 6))
    last = session.scalar(select(func.max(Report.created_at)).where(Report.kind == KIND))
    return last is None or _aware(last) <= now - timedelta(hours=every)


def summarize_threads(session: Session, config: RadarConfig, claude: ClaudeClient, limit: int = 120, batch: int = 15) -> int:
    """Vietnamese summary for new Shopify Community threads (not for chat messages)."""
    sources = community_sources(session)
    if not sources:
        return 0
    since = utcnow() - timedelta(days=3)
    pending = list(
        session.scalars(
            select(Item)
            .where(
                Item.source_id.in_(list(sources)),
                Item.media_type != "message",
                or_(Item.summary == "", Item.summary.is_(None)),
                Item.first_seen >= since,
            )
            .order_by(Item.first_seen.desc())
            .limit(limit)
        )
    )
    done = 0
    for start in range(0, len(pending), batch):
        chunk = pending[start : start + batch]
        listing = "\n\n".join(f"[id={i.id}] Tiêu đề: {i.title}\nNội dung: {' '.join((i.content or '').split())[:1500]}" for i in chunk)
        prompt = load_prompt("community_summarize", count=len(chunk), items=listing)
        data = claude.call_json(CallSpec("community", prompt.system, prompt.user, SUMMARY_SCHEMA, effort="low", max_tokens=16000))
        by_id = {i.id: i for i in chunk}
        for row in data.get("items", []):
            item = by_id.get(row.get("id"))
            if item is not None and row.get("summary"):
                item.summary = row["summary"].strip()
                done += 1
        session.flush()
    return done


def refresh(session: Session, config: RadarConfig, claude: ClaudeClient, force: bool = False) -> dict[str, Any]:
    """Run step: summarize new threads, rebuild the digest when due."""
    summarized = summarize_threads(session, config, claude)
    report = build_digest(session, config, claude) if (force or digest_due(session, config)) else None
    return {"summarized": summarized, "digest": report.id if report else None}
