"""Community talk (sources with kind: community — Discord, Shopify Community).

These items are not classified or rated one by one. Instead:

- every Shopify Community thread gets a short Vietnamese summary (batched
  Claude calls, community.summary_effort);
- every Discord message gets a Vietnamese translation, kept in `summary`
  (the page shows it, with the original one click away; community.translate_effort);
- images attached to Discord messages are looked at by Claude while their
  links still work (Discord's signed links expire within a day) and described
  in Vietnamese in `extra.image_note` (community.describe_images);
- a Vietnamese digest is written at most every `digest_every_hours` and
  stored as a Report with kind "community": overview, topics, open questions,
  each pointing at the messages it comes from. Each digest covers only what
  no earlier digest did (items stored since the previous one, said within the
  last `digest_hours`), so nothing is summed up twice; its item ids are kept
  so the page can show exactly the messages behind it.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from radar.ai.client import AIError, AITruncated, CallSpec, ClaudeClient
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


TRANSLATE_SCHEMA = {
    "type": "object",
    "properties": {
        "translations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "integer"}, "vi": {"type": "string"}},
                "required": ["id", "vi"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["translations"],
    "additionalProperties": False,
}


IMAGE_SCHEMA = {
    "type": "object",
    "properties": {"note": {"type": "string"}},
    "required": ["note"],
    "additionalProperties": False,
}
MAX_IMAGES_PER_MESSAGE = 4


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def when(item: Item) -> datetime:
    return _aware(item.published_at or item.first_seen)


def community_sources(session: Session) -> dict[str, Source]:
    return {s.id: s for s in session.scalars(select(Source).where(Source.kind == KIND))}


def window_items(session: Session, hours: int, now: datetime | None = None, stored_after: datetime | None = None) -> list[Item]:
    """Community items said in the last `hours`, oldest first; with `stored_after`,
    only those stored after that moment (not yet in an earlier digest)."""
    now = now or utcnow()
    since = now - timedelta(hours=hours)
    sources = community_sources(session)
    if not sources:
        return []
    query = select(Item).where(Item.source_id.in_(list(sources)), func.coalesce(Item.published_at, Item.first_seen) >= since)
    if stored_after is not None:
        query = query.where(Item.first_seen > stored_after)
    return sorted(session.scalars(query), key=when)


def latest_digest(session: Session) -> Report | None:
    return session.scalar(select(Report).where(Report.kind == KIND).order_by(Report.created_at.desc(), Report.id.desc()).limit(1))


def previous_digest(session: Session, report: Report) -> Report | None:
    return session.scalar(
        select(Report)
        .where(Report.kind == KIND, Report.created_at < report.created_at)
        .order_by(Report.created_at.desc(), Report.id.desc())
        .limit(1)
    )


DETAIL_LINE = re.compile(r"^\[(Ảnh|Tệp|Link|Nội dung ảnh): .*\]$")


def own_text(content: str) -> str:
    """What the person wrote, without the [Ảnh: …] / [Link: …] lines describing attachments."""
    return "\n".join(line for line in (content or "").splitlines() if not DETAIL_LINE.match(line.strip())).strip()


def message_text(item: Item) -> str:
    """A chat message with what its images show, as Claude reads it."""
    text = (item.content or "").strip()
    note = (item.extra or {}).get("image_note")
    return f"{text}\n[Nội dung ảnh: {note}]" if note else text


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
                text = " ".join(message_text(item).split())[:600]
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
    last = latest_digest(session)
    items = window_items(session, hours, now, stored_after=last.created_at if last else None)
    if not items:
        return None  # nothing new since the last digest
    sources = community_sources(session)
    text, included = render(items, sources, int(settings.get("max_chars", 80000)))
    tz = ZoneInfo(get_settings().timezone)
    start = min(when(items[0]), now)
    prompt = load_prompt(
        "community_digest",
        hours=hours,
        interests=config.interests,
        window=f"{start.astimezone(tz):%H:%M %d/%m} – {now.astimezone(tz):%H:%M %d/%m/%Y}",
        count=len(items),
        messages=text,
    )
    data = claude.call_json(
        CallSpec("community", prompt.system, prompt.user, DIGEST_SCHEMA, effort=settings.get("digest_effort", "high"), max_tokens=16000)
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
        all_item_ids=[i.id for i in items],
    )
    report = Report(kind=KIND, period_start=start.astimezone(tz).date(), period_end=now.astimezone(tz).date(), content=data, items_considered=len(items), model=claude.model)
    session.add(report)
    session.flush()
    return report


def delete_digests(session: Session) -> int:
    """Remove every community digest (the messages and translations stay); the next
    digest then covers the last `digest_hours` again."""
    reports = list(session.scalars(select(Report).where(Report.kind == KIND)))
    for report in reports:
        session.delete(report)
    session.flush()
    return len(reports)


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
        effort = config.section("community").get("summary_effort", "high")
        data = claude.call_json(CallSpec("community", prompt.system, prompt.user, SUMMARY_SCHEMA, effort=effort, max_tokens=16000))
        by_id = {i.id: i for i in chunk}
        for row in data.get("items", []):
            item = by_id.get(row.get("id"))
            if item is not None and row.get("summary"):
                item.summary = row["summary"].strip()
                done += 1
        session.flush()
    return done


def translate_messages(session: Session, config: RadarConfig, claude: ClaudeClient, limit: int = 600, batch: int = 30) -> int:
    """Vietnamese translation of recent Discord messages that have none yet."""
    sources = community_sources(session)
    if not sources:
        return 0
    since = utcnow() - timedelta(days=3)
    pending = list(
        session.scalars(
            select(Item)
            .where(
                Item.source_id.in_(list(sources)),
                Item.media_type == "message",
                or_(Item.summary == "", Item.summary.is_(None)),
                Item.first_seen >= since,
            )
            .order_by(Item.first_seen.desc())
            .limit(limit)
        )
    )
    pending = [i for i in pending if own_text(i.content)]  # only an image or a link: nothing to translate
    effort = config.section("community").get("translate_effort", "high")
    done = 0
    for start in range(0, len(pending), batch):
        done += _translate_chunk(session, claude, pending[start : start + batch], effort)
    return done


def _translate_chunk(session: Session, claude: ClaudeClient, chunk: list[Item], effort: str) -> int:
    listing = "\n\n".join(f"[id={i.id}] {message_text(i)[:1800]}" for i in chunk)
    prompt = load_prompt("community_translate", count=len(chunk), items=listing)
    try:
        data = claude.call_json(CallSpec("community", prompt.system, prompt.user, TRANSLATE_SCHEMA, effort=effort, max_tokens=16000))
    except AITruncated:
        if len(chunk) == 1:
            log.warning("Translation of message %s hit max_tokens; left untranslated", chunk[0].id)
            return 0
        middle = len(chunk) // 2
        return _translate_chunk(session, claude, chunk[:middle], effort) + _translate_chunk(session, claude, chunk[middle:], effort)
    by_id = {i.id: i for i in chunk}
    done = 0
    for row in data.get("translations", []):
        item = by_id.get(row.get("id"))
        text = (row.get("vi") or "").strip()
        if item is not None and text:
            item.summary = text
            done += 1
    session.flush()
    return done


def image_urls(item: Item) -> list[str]:
    from radar.collectors.discord import is_image

    return [a["url"] for a in (item.extra or {}).get("attachments", []) if is_image(a) and a.get("url")][:MAX_IMAGES_PER_MESSAGE]


def describe_images(session: Session, config: RadarConfig, claude: ClaudeClient) -> int:
    """Vietnamese description of the images attached to recent Discord messages."""
    settings = config.section("community")
    if not settings.get("describe_images", True):
        return 0
    sources = community_sources(session)
    if not sources:
        return 0
    since = utcnow() - timedelta(hours=20)  # attachment links expire after about a day
    candidates = session.scalars(
        select(Item)
        .where(Item.source_id.in_(list(sources)), Item.media_type == "message", Item.first_seen >= since)
        .order_by(Item.first_seen.desc())
    )
    pending = [i for i in candidates if image_urls(i) and "image_note" not in (i.extra or {}) and not (i.extra or {}).get("image_failed")]
    limit = int(settings.get("max_images_per_run", 40))
    done = 0
    for item in pending[:limit]:
        prompt = load_prompt("community_image", message=(item.content or "")[:1500], author=item.author or "ẩn danh")
        spec = CallSpec("community", prompt.system, prompt.user, IMAGE_SCHEMA, effort=settings.get("translate_effort", "high"), max_tokens=4000, images=image_urls(item))
        try:
            note = (claude.call_json(spec).get("note") or "").strip()
        except AIError as exc:  # link expired, image unreadable, refused…: do not try again
            log.warning("Image of message %s not described: %s", item.id, exc)
            item.extra = {**(item.extra or {}), "image_failed": True}
            continue
        item.extra = {**(item.extra or {}), "image_note": note}
        item.summary = ""  # translate again, now knowing what the image shows
        done += 1
    session.flush()
    return done


def refresh(session: Session, config: RadarConfig, claude: ClaudeClient, force: bool = False) -> dict[str, Any]:
    """Run step: describe attached images, translate new Discord messages, summarize new threads,
    rebuild the digest when due."""
    described = describe_images(session, config, claude)
    translated = translate_messages(session, config, claude)
    summarized = summarize_threads(session, config, claude)
    report = build_digest(session, config, claude) if (force or digest_due(session, config)) else None
    return {"images": described, "translated": translated, "summarized": summarized, "digest": report.id if report else None}
