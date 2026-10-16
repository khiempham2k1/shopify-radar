"""Overview brief: what stood out lately, what to read, which discussions to follow.

Written by Claude every `overview.brief_every_hours` when something new came in,
and stored as a Report with kind "brief". It reads, for the last
`overview.brief_days` days:

- the posts that passed classification (official and priority first, then by
  score), with what classification found;
- the community side: the latest community digest's overview and topics, and
  the Shopify Community threads and Discord messages behind them.

It writes a headline, a short summary, highlights pointing at their items,
and two reading lists with a one-line reason each: posts worth reading and
discussions worth reading. Ids are checked against what Claude was shown.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from radar.ai.client import CallSpec, ClaudeClient
from radar.ai.community import KIND as COMMUNITY_KIND
from radar.ai.community import (
    community_sources,
    latest_digest,
    message_text,
    own_text,
    place,
    when,
)
from radar.ai.insights import item_line
from radar.config_loader import RadarConfig, load_prompt
from radar.models import AIResult, Item, Report, Source, utcnow

log = logging.getLogger(__name__)

KIND = "brief"

PICK = {
    "type": "object",
    "properties": {"item_id": {"type": "integer"}, "why": {"type": "string"}},
    "required": ["item_id", "why"],
    "additionalProperties": False,
}
BRIEF_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "summary": {"type": "string"},
        "highlights": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"text": {"type": "string"}, "item_ids": {"type": "array", "items": {"type": "integer"}}},
                "required": ["text", "item_ids"],
                "additionalProperties": False,
            },
        },
        "must_read": {"type": "array", "items": PICK},
        "discussions": {"type": "array", "items": PICK},
    },
    "required": ["headline", "summary", "highlights", "must_read", "discussions"],
    "additionalProperties": False,
}


def settings(config: RadarConfig) -> dict[str, Any]:
    return config.section("overview")


def post_candidates(session: Session, config: RadarConfig, since: datetime, limit: int) -> list[Item]:
    """Posts of the window that classification kept (or priority topics), official first, then by score."""
    min_score = float(config.ai.get("min_score", 0.5))
    matched = select(AIResult.item_id).where(AIResult.status == "active", AIResult.score >= min_score)
    stmt = (
        select(Item)
        .join(Source, Source.id == Item.source_id)
        .where(
            Source.kind != COMMUNITY_KIND,
            Item.first_seen >= since,
            or_(Item.id.in_(matched), Item.priority.is_not(None)),
        )
        .options(selectinload(Item.results).selectinload(AIResult.tag))
        .order_by(Item.official.desc(), Item.priority.is_(None), Item.score.desc())
        .limit(limit)
    )
    return list(session.scalars(stmt).unique())


def discussion_candidates(session: Session, since: datetime, digest: Report | None, limit: int) -> list[Item]:
    """Community threads and messages of the window: those the digest points at, then threads by
    replies and messages by reactions."""
    sources = community_sources(session)
    if not sources:
        return []
    items = list(
        session.scalars(
            select(Item).where(Item.source_id.in_(list(sources)), func.coalesce(Item.published_at, Item.first_seen) >= since)
        )
    )
    cited: set[int] = set()
    if digest is not None:
        for section in ("topics", "open_questions"):
            for entry in (digest.content or {}).get(section, []):
                cited.update(entry.get("item_ids", []))

    def weight(item: Item) -> tuple[int, int]:
        metrics = item.metrics or {}
        return (item.id in cited, int(metrics.get("comments", 0)) + int(metrics.get("likes", 0)))

    return sorted(items, key=weight, reverse=True)[:limit]


def discussion_line(item: Item, places: dict[str, Source]) -> str:
    metrics = item.metrics or {}
    counts = ", ".join(f"{n} {label}" for label, n in (("trả lời", metrics.get("comments", 0)), ("reaction", metrics.get("likes", 0))) if n)
    head = f"[{item.id}] {place(item, places)} · {item.author or 'ẩn danh'}" + (f" · {counts}" if counts else "")
    if item.media_type == "message":
        body = item.summary or own_text(message_text(item))
    else:
        body = f"{item.title}" + (f" — {item.summary}" if item.summary else "")
    return f"{head}\n    {' '.join(body.split())[:500]}"


def digest_text(digest: Report | None) -> str:
    if digest is None:
        return "(chưa có)"
    content = digest.content or {}
    lines = [content.get("overview", "")]
    for topic in content.get("topics", []):
        lines.append(f"- {topic.get('title')}: {topic.get('summary')} (tin: {topic.get('item_ids')})")
    return "\n".join(line for line in lines if line) or "(trống)"


def latest_brief(session: Session) -> Report | None:
    return session.scalar(select(Report).where(Report.kind == KIND).order_by(Report.created_at.desc(), Report.id.desc()).limit(1))


def brief_due(session: Session, config: RadarConfig, now: datetime | None = None) -> bool:
    """Due when the last brief is older than brief_every_hours and something came in since."""
    now = now or utcnow()
    last = latest_brief(session)
    if last is None:
        return True
    created = last.created_at if last.created_at.tzinfo else last.created_at.replace(tzinfo=now.tzinfo)
    if created > now - timedelta(hours=float(settings(config).get("brief_every_hours", 6))):
        return False
    return session.scalar(select(func.count(Item.id)).where(Item.first_seen > last.created_at)) > 0


def build_brief(session: Session, config: RadarConfig, claude: ClaudeClient, now: datetime | None = None) -> Report | None:
    opts = settings(config)
    now = now or utcnow()
    days = int(opts.get("brief_days", 3))
    since = now - timedelta(days=days)
    names = {s.id: s.name for s in session.scalars(select(Source))}
    posts = post_candidates(session, config, since, int(opts.get("max_posts", 60)))
    digest = latest_digest(session)
    talks = discussion_candidates(session, since, digest, int(opts.get("max_discussions", 40)))
    if not posts and not talks:
        return None
    places = community_sources(session)
    prompt = load_prompt(
        "overview_brief",
        interests=config.interests,
        days=days,
        posts="\n".join(item_line(i, names) for i in posts) or "(không có)",
        digest=digest_text(digest),
        discussions="\n".join(discussion_line(i, places) for i in sorted(talks, key=when, reverse=True)) or "(không có)",
    )
    data = claude.call_json(CallSpec("brief", prompt.system, prompt.user, BRIEF_SCHEMA, effort=opts.get("brief_effort", "high"), max_tokens=16000))

    post_ids, talk_ids = {i.id for i in posts}, {i.id for i in talks}
    known = post_ids | talk_ids
    for point in data.get("highlights", []):
        point["item_ids"] = [i for i in point.get("item_ids", []) if i in known][:4]

    def picks(key: str, allowed: set[int], cap: int) -> list[dict[str, Any]]:
        seen: set[int] = set()
        out = []
        for pick in data.get(key, []):
            item_id = pick.get("item_id")
            if item_id in allowed and item_id not in seen:
                seen.add(item_id)
                out.append({"item_id": item_id, "why": (pick.get("why") or "").strip()})
        return out[:cap]

    data["must_read"] = picks("must_read", post_ids, int(opts.get("must_read", 6)))
    data["discussions"] = picks("discussions", talk_ids, int(opts.get("discussions", 5)))
    data.update(window_days=days, posts_considered=len(posts), discussions_considered=len(talks))
    report = Report(kind=KIND, period_start=since.date(), period_end=now.date(), content=data, items_considered=len(posts) + len(talks), model=claude.model)
    session.add(report)
    session.flush()
    return report


def refresh(session: Session, config: RadarConfig, claude: ClaudeClient, force: bool = False) -> int | None:
    """Run step: write a new brief when due. Returns its id, or None."""
    if not (force or brief_due(session, config)):
        return None
    report = build_brief(session, config, claude)
    return report.id if report else None
