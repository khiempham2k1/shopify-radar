"""Shopify Radar API.

The Next.js server signs people in with Google, then calls this API with
`Authorization: Bearer $RADAR_API_TOKEN` and the person's email in
`X-Radar-User`. Browsers never call this API directly.
"""

from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from collections.abc import Iterator
from contextlib import asynccontextmanager
from datetime import date, datetime, time, timedelta, timezone
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, selectinload

from radar.config_loader import EDITABLE_FILES, load_config, read_text, save_text
from radar.db import describe_url, ensure_schema, session_factory
from radar.models import (
    AIAnalyzed,
    AIResult,
    AITag,
    AIUsage,
    CrawlRun,
    Item,
    ItemStatus,
    ItemTranscript,
    Report,
    Setting,
    Source,
    SourceStatus,
    utcnow,
)
from radar.settings import get_settings

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Local runs often start the API before `radar migrate`: create the schema then.
    log.warning("Shopify Radar API dùng DB: %s", describe_url())
    ensure_schema()
    yield


app = FastAPI(title="Shopify Radar API", version="0.1.0", lifespan=lifespan)


# ── dependencies ────────────────────────────────────────────────────


def get_session() -> Iterator[Session]:
    session = session_factory()()
    try:
        yield session
    finally:
        session.close()


def current_user(
    authorization: Annotated[str | None, Header()] = None,
    x_radar_user: Annotated[str | None, Header()] = None,
) -> str:
    token = get_settings().api_token
    if token and authorization != f"Bearer {token}":
        raise HTTPException(status_code=401, detail="Sai hoặc thiếu API token")
    return (x_radar_user or "").strip() or "unknown"


SessionDep = Annotated[Session, Depends(get_session)]
UserDep = Annotated[str, Depends(current_user)]


def is_admin(
    x_radar_user: Annotated[str | None, Header()] = None,
    x_radar_admin: Annotated[str | None, Header()] = None,
) -> bool:
    """Technical details (tools, config, database) are for Phase 2 accounts only.
    The web proxy sets X-Radar-Admin for them; a direct call that does not come
    through the proxy (no X-Radar-User, e.g. curl on the server) also counts."""
    return x_radar_admin == "1" or not (x_radar_user or "").strip()


AdminDep = Annotated[bool, Depends(is_admin)]


# ── helpers ─────────────────────────────────────────────────────────


def tz() -> ZoneInfo:
    return ZoneInfo(get_settings().timezone)


def local_midnight(days_ago: int = 0) -> datetime:
    today = datetime.now(tz()).date() - timedelta(days=days_ago)
    return datetime.combine(today, time.min, tz()).astimezone(timezone.utc)


def aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def iso(value: datetime | None) -> str | None:
    value = aware(value)
    return value.isoformat() if value else None


def best_result(item: Item) -> AIResult | None:
    active = [r for r in item.results if r.status == "active"]
    return max(active, key=lambda r: r.score) if active else None


def serialize_item(item: Item, analyzed_ids: set[int], full: bool = False) -> dict[str, Any]:
    result = best_result(item)
    status = item.status
    transcript = item.transcript
    today = datetime.now(tz()).date()
    data: dict[str, Any] = {
        "id": item.id,
        "source": {"id": item.source.id, "name": item.source.name, "kind": item.source.kind, "type": item.source.type},
        "url": item.url,
        "title": item.title,
        "summary": item.summary,
        "content": item.content if full else (item.content or "")[:600],
        "author": item.author,
        "media_type": item.media_type,
        "published_at": iso(item.published_at),
        "first_seen": iso(item.first_seen),
        "last_seen": iso(item.last_seen),
        "seen_count": item.seen_count,
        "score": item.score,
        "hot": item.hot,
        "official": item.official,
        "metrics": item.metrics or {},
        "extra": item.extra or {},
        "keyword_groups": item.keyword_groups or [],
        "priority": item.priority.split(", ") if item.priority else [],
        "analyzed": item.id in analyzed_ids,
        "tag": {"id": result.tag.id, "name": result.tag.tag} if result else None,
        "relevance": result.score if result else None,
        "sentiment": result.sentiment if result else None,
        "impact": result.impact if result else None,
        "affects": result.affects.split(",") if result and result.affects else [],
        "deadline": result.deadline.isoformat() if result and result.deadline else None,
        "days_left": (result.deadline - today).days if result and result.deadline else None,
        "status": status.status if status else "new",
        "owner": status.owner if status else "",
        "transcript": None,
    }
    if transcript is not None:
        data["transcript"] = {
            "status": transcript.status,
            "via": transcript.via,
            "points": transcript.points or [],
            "duration_s": transcript.duration_s,
            "error": transcript.error if transcript.status == "error" else "",
        }
        if full:
            data["transcript"]["segments"] = transcript.segments or []
    return data


def item_query():
    return select(Item).options(
        selectinload(Item.source),
        selectinload(Item.results).selectinload(AIResult.tag),
        selectinload(Item.status),
        selectinload(Item.transcript),
    )


def visible_clause(min_score: float):
    """Shown on the dashboard: Claude matched it, or Claude has not seen it yet and
    it passed the keyword filter (the keyword fallback). Platform items and
    priority-topic items always count."""
    matched = select(AIResult.item_id).where(AIResult.status == "active", AIResult.score >= min_score)
    analyzed = select(AIAnalyzed.item_id)
    return or_(
        Item.id.in_(matched),
        Item.priority.is_not(None),
        and_(Item.id.not_in(analyzed), or_(Item.keyword_matched.is_(True), Source.kind == "platform")),
    )


def analyzed_ids(session: Session, ids: list[int]) -> set[int]:
    if not ids:
        return set()
    return set(session.scalars(select(AIAnalyzed.item_id).where(AIAnalyzed.item_id.in_(ids))))


# ── health ──────────────────────────────────────────────────────────


@app.get("/api/health")
def health(admin: AdminDep) -> dict[str, Any]:
    """Liveness; for admins also which database the API reads (password hidden) and how much is in it."""
    from radar.db import db_status

    return {"ok": True, **db_status()} if admin else {"ok": True}


@app.get("/api/me")
def me(user: UserDep) -> dict[str, str]:
    return {"user": user}


# ── items ───────────────────────────────────────────────────────────

Mode = Literal["new", "hot", "today", "week", "all"]
View = Literal["platform", "feed", "all"]
# hot: interaction vs. the same source, decaying with age; score: overall relevance; new: newest first.
Sort = Literal["hot", "score", "new"]


@app.get("/api/items")
def list_items(
    session: SessionDep,
    _: UserDep,
    view: View = "feed",
    mode: Mode = "all",
    source: str | None = None,
    tag: int | None = None,
    sentiment: Literal["neg", "neu", "pos"] | None = None,
    impact: Literal["high", "med", "low"] | None = None,
    affects: Literal["theme", "partner", "merchant"] | None = None,
    status: Literal["new", "doing", "done", "dismissed"] | None = None,
    q: str | None = None,
    priority: bool = False,
    sort: Sort | None = None,
    all_changes: bool = False,
    days: int = Query(60, ge=1, le=365),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    config = load_config(session)
    min_score = float(config.ai.get("min_score", 0.5))
    hot = float(config.scoring.get("hot_threshold", 5.0))
    now = utcnow()

    stmt = item_query().join(Source, Source.id == Item.source_id).outerjoin(ItemStatus, ItemStatus.item_id == Item.id)
    # Community talk (Discord, Shopify Community) has its own page: /api/community.
    conditions = [Item.last_seen >= now - timedelta(days=days), Source.kind != "community"]
    if view == "platform":
        conditions.append(Source.kind == "platform")
    elif view == "feed":
        conditions.append(Source.kind != "platform")
    if status == "dismissed":
        conditions.append(ItemStatus.status == "dismissed")
    else:
        # all_changes (Platform page): also the official changes Claude judged unrelated to themes,
        # so nothing Shopify announced is ever out of reach.
        if not (all_changes and view == "platform"):
            conditions.append(visible_clause(min_score))
        conditions.append(or_(ItemStatus.status.is_(None), ItemStatus.status != "dismissed"))
        if status == "new":
            conditions.append(or_(ItemStatus.status.is_(None), ItemStatus.status == "new"))
        elif status:
            conditions.append(ItemStatus.status == status)
    if mode == "new":
        conditions.append(Item.first_seen >= now - timedelta(hours=6))
    elif mode == "hot":
        conditions += [Item.hot >= hot, Item.last_seen >= now - timedelta(hours=48)]
    elif mode == "today":
        conditions.append(Item.first_seen >= local_midnight())
    elif mode == "week":
        conditions.append(Item.first_seen >= now - timedelta(days=7))
    if source:
        conditions.append(Item.source_id == source)
    if priority:
        conditions.append(Item.priority.is_not(None))
    if tag is not None or sentiment or impact or affects:
        sub = select(AIResult.item_id).where(AIResult.status == "active", AIResult.score >= min_score)
        if tag is not None:
            sub = sub.where(AIResult.tag_id == tag)
        if sentiment:
            sub = sub.where(AIResult.sentiment == sentiment)
        if impact:
            sub = sub.where(AIResult.impact == impact)
        if affects:
            sub = sub.where(AIResult.affects.contains(affects))
        conditions.append(Item.id.in_(sub))
    if q:
        pattern = f"%{q.strip()}%"
        in_transcript = select(ItemTranscript.item_id).where(ItemTranscript.text.ilike(pattern))
        conditions.append(or_(Item.title.ilike(pattern), Item.summary.ilike(pattern), Item.content.ilike(pattern), Item.id.in_(in_transcript)))

    stmt = stmt.where(*conditions)
    total = session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    newest = func.coalesce(Item.published_at, Item.first_seen).desc()
    sort = sort or ("new" if view == "platform" else "hot")
    # Shopify's own items come first, then the chosen order.
    order = {
        "new": [newest],
        "score": [Item.official.desc(), Item.score.desc(), newest],
        "hot": [Item.official.desc(), Item.hot.desc(), Item.score.desc(), newest],
    }[sort]
    items = list(session.scalars(stmt.order_by(*order).limit(limit).offset(offset)).unique())
    done = analyzed_ids(session, [i.id for i in items])
    return {"items": [serialize_item(i, done) for i in items], "total": total or 0}


def get_item_or_404(session: Session, item_id: int) -> Item:
    item = session.scalars(item_query().where(Item.id == item_id)).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy item")
    return item


@app.get("/api/items/{item_id}")
def get_item(item_id: int, session: SessionDep, _: UserDep) -> dict[str, Any]:
    item = get_item_or_404(session, item_id)
    return serialize_item(item, analyzed_ids(session, [item.id]), full=True)


class ItemPatch(BaseModel):
    status: Literal["new", "doing", "done", "dismissed"] | None = None
    owner: str | None = None


@app.patch("/api/items/{item_id}")
def patch_item(item_id: int, body: ItemPatch, session: SessionDep, user: UserDep) -> dict[str, Any]:
    item = get_item_or_404(session, item_id)
    row = item.status or ItemStatus(item_id=item.id)
    if item.status is None:
        session.add(row)
    if body.status is not None:
        row.status = body.status
    if body.owner is not None:
        row.owner = body.owner.strip()[:200]
    row.updated_by = user
    row.updated_at = utcnow()
    session.commit()
    session.refresh(item)
    return serialize_item(item, analyzed_ids(session, [item.id]))


# ── overview ────────────────────────────────────────────────────────


def todo_items(session: Session, min_score: float, todo_threshold: float, limit: int = 20) -> list[Item]:
    """High-impact platform changes not done yet, then high-score discussions not handled."""
    open_status = or_(ItemStatus.status.is_(None), ItemStatus.status.in_(["new", "doing"]))
    platform = select(AIResult.item_id).where(AIResult.status == "active", AIResult.impact == "high", AIResult.score >= min_score)
    base = item_query().join(Source, Source.id == Item.source_id).outerjoin(ItemStatus, ItemStatus.item_id == Item.id)
    since = utcnow() - timedelta(days=60)
    changes = list(
        session.scalars(base.where(Source.kind == "platform", Item.id.in_(platform), open_status, Item.last_seen >= since)).unique()
    )
    changes.sort(key=lambda i: (best_result(i).deadline or date.max, -aware(i.first_seen).timestamp()))
    feed = list(
        session.scalars(
            base.where(
                Source.kind.not_in(["platform", "community"]),
                Item.score >= todo_threshold,
                visible_clause(min_score),
                open_status,
                Item.last_seen >= utcnow() - timedelta(days=7),
            ).order_by(Item.official.desc(), Item.score.desc())
        ).unique()
    )
    return (changes + feed)[:limit]


def priority_items(session: Session, days: int = 30, limit: int = 12) -> list[Item]:
    """Newest items on a priority topic (config/priorities.txt), not dismissed."""
    stmt = (
        item_query()
        .outerjoin(ItemStatus, ItemStatus.item_id == Item.id)
        .where(
            Item.priority.is_not(None),
            Item.last_seen >= utcnow() - timedelta(days=days),
            or_(ItemStatus.status.is_(None), ItemStatus.status != "dismissed"),
        )
        .order_by(Item.official.desc(), func.coalesce(Item.published_at, Item.first_seen).desc())
        .limit(limit)
    )
    return list(session.scalars(stmt).unique())


@app.get("/api/overview")
def overview(session: SessionDep, _: UserDep) -> dict[str, Any]:
    config = load_config(session)
    min_score = float(config.ai.get("min_score", 0.5))
    now = utcnow()
    week_ago, two_weeks_ago = now - timedelta(days=7), now - timedelta(days=14)

    rows = session.execute(
        select(Item.id, Item.first_seen, Source.kind)
        .join(Source, Source.id == Item.source_id)
        .where(Item.first_seen >= local_midnight(13), visible_clause(min_score), Source.kind != "community")
    ).all()
    daily: dict[date, Counter[str]] = defaultdict(Counter)
    new_7d = new_prev = 0
    for _, first_seen, kind in rows:
        first_seen = aware(first_seen)
        daily[first_seen.astimezone(tz()).date()][kind] += 1
        if first_seen >= week_ago:
            new_7d += 1
        elif first_seen >= two_weeks_ago:
            new_prev += 1
    today = datetime.now(tz()).date()
    series = []
    for offset in range(13, -1, -1):
        day = today - timedelta(days=offset)
        counts = daily.get(day, Counter())
        series.append({"date": day.isoformat(), "platform": counts["platform"], "social": counts["social"], "web": counts["web"]})

    def tag_counts(start: datetime, end: datetime) -> Counter[str]:
        result = session.execute(
            select(AITag.tag, func.count(AIResult.id))
            .join(AIResult, AIResult.tag_id == AITag.id)
            .join(Item, Item.id == AIResult.item_id)
            .where(AIResult.status == "active", AIResult.score >= min_score, Item.first_seen >= start, Item.first_seen < end)
            .group_by(AITag.tag)
        ).all()
        return Counter(dict(result))

    this_week, last_week = tag_counts(week_ago, now + timedelta(minutes=1)), tag_counts(two_weeks_ago, week_ago)
    topics = [{"tag": t, "count": n, "previous": last_week.get(t, 0)} for t, n in this_week.most_common(8)]

    def negative_ratio(start: datetime, end: datetime) -> float | None:
        result = session.execute(
            select(AIResult.sentiment, func.count())
            .join(Item, Item.id == AIResult.item_id)
            .join(Source, Source.id == Item.source_id)
            .where(AIResult.status == "active", AIResult.score >= min_score, Source.kind == "social", Item.first_seen >= start, Item.first_seen < end)
            .group_by(AIResult.sentiment)
        ).all()
        counts = dict(result)
        total = sum(counts.values())
        return round(counts.get("neg", 0) / total, 3) if total else None

    todo = todo_items(session, min_score, float(config.scoring.get("todo_threshold", 7.0)))
    priority = priority_items(session)
    deadlines = [
        r.deadline
        for i in todo
        if (r := best_result(i)) is not None and r.deadline is not None and (r.deadline - today).days <= 90
    ]
    last_run = session.scalar(select(CrawlRun).where(CrawlRun.finished_at.is_not(None)).order_by(CrawlRun.finished_at.desc()).limit(1))
    done = analyzed_ids(session, [i.id for i in todo + priority])
    return {
        "kpis": {
            "new_7d": new_7d,
            "new_prev_7d": new_prev,
            "todo": len(todo),
            "todo_unassigned": sum(1 for i in todo if not (i.status and i.status.owner)),
            "deadlines_90d": len(deadlines),
            "nearest_deadline_days": min(((d - today).days for d in deadlines), default=None),
            "negative_ratio": negative_ratio(week_ago, now + timedelta(minutes=1)),
            "negative_ratio_prev": negative_ratio(two_weeks_ago, week_ago),
        },
        "daily": series,
        "topics": topics,
        "todo": [serialize_item(i, done) for i in todo],
        "priority": {"topics": [t.name for t in config.priorities], "items": [serialize_item(i, done) for i in priority]},
        "last_run": iso(last_run.finished_at) if last_run else None,
        "schedule": config.schedule.get("collect", ""),
    }


# ── community (Discord, Shopify Community) ──────────────────────────


def community_ref(item: Item, places: dict[str, str]) -> dict[str, Any]:
    from radar.ai.community import place

    return {
        "id": item.id,
        "url": item.url,
        "title": item.title,
        "text": (item.content or "")[:500],
        "summary": item.summary,
        "author": item.author,
        "place": place(item, places),
        "when": iso(item.published_at or item.first_seen),
        "reactions": (item.metrics or {}).get("likes", 0),
        "comments": (item.metrics or {}).get("comments", 0),
        "is_reply": bool((item.extra or {}).get("reply_to")),
    }


@app.get("/api/community")
def community_page(
    session: SessionDep,
    _: UserDep,
    digest: int | None = None,
    hours: int = Query(24, ge=1, le=168),
    per_channel: int = Query(40, ge=1, le=200),
) -> dict[str, Any]:
    """What people discuss: the Vietnamese digest (latest, or the one asked for), community
    threads with their summaries, and recent messages per Discord channel. Not rated."""
    from radar.ai.community import KIND, community_sources, place, window_items

    sources = community_sources(session)
    digests = list(session.scalars(select(Report).where(Report.kind == KIND).order_by(Report.created_at.desc()).limit(30)))
    chosen = next((d for d in digests if d.id == digest), None) if digest else (digests[0] if digests else None)

    digest_out = None
    if chosen is not None:
        content = dict(chosen.content or {})
        ids = {i for section in ("topics", "open_questions") for entry in content.get(section, []) for i in entry.get("item_ids", [])}
        refs = {i.id: community_ref(i, sources) for i in session.scalars(select(Item).where(Item.id.in_(ids)))} if ids else {}
        for section in ("topics", "open_questions"):
            content[section] = [{**entry, "items": [refs[i] for i in entry.get("item_ids", []) if i in refs]} for entry in content.get(section, [])]
        digest_out = {"id": chosen.id, "created_at": iso(chosen.created_at), "items_considered": chosen.items_considered, **content}

    items = window_items(session, hours)
    threads = [community_ref(i, sources) for i in reversed(items) if i.media_type != "message"]
    channels: dict[str, list[dict[str, Any]]] = {}
    for item in reversed(items):  # newest first
        if item.media_type == "message":
            channels.setdefault(place(item, sources), []).append(community_ref(item, sources))
    return {
        "digest": digest_out,
        "digests": [{"id": d.id, "created_at": iso(d.created_at), "items_considered": d.items_considered} for d in digests],
        "hours": hours,
        "threads": threads,
        "channels": [{"name": name, "count": len(msgs), "messages": msgs[:per_channel]} for name, msgs in channels.items()],
        "sources": [{"id": s.id, "name": s.name, "enabled": s.enabled} for s in sources.values()],
    }


# ── editions ────────────────────────────────────────────────────────


@app.get("/api/editions")
def editions(session: SessionDep, _: UserDep) -> list[dict[str, Any]]:
    config = load_config(session)
    min_score = float(config.ai.get("min_score", 0.5))
    edition_sources = [s.id for s in session.scalars(select(Source).where(Source.type == "editions"))]
    if not edition_sources:
        return []
    items = list(session.scalars(item_query().where(Item.source_id.in_(edition_sources))).unique())
    grouped: dict[str, list[Item]] = defaultdict(list)
    for item in items:
        grouped[item.extra.get("edition", "?")].append(item)
    out = []
    for name, group in grouped.items():
        relevant = [i for i in group if (r := best_result(i)) is not None and r.score >= min_score]
        tags = Counter(best_result(i).tag.tag for i in relevant)
        sections = Counter(i.extra.get("section") or "Khác" for i in relevant)
        out.append(
            {
                "edition": name,
                "url": group[0].url.split("#")[0],
                "first_seen": iso(min(aware(i.first_seen) for i in group)),
                "total": len(group),
                "relevant": len(relevant),
                "unanalyzed": sum(1 for i in group if not best_result(i)),
                "tags": [{"tag": t, "count": n} for t, n in tags.most_common()],
                "sections": [{"section": s, "count": n} for s, n in sections.most_common()],
            }
        )
    out.sort(key=lambda e: e["first_seen"] or "", reverse=True)
    return out


# ── sources & health ────────────────────────────────────────────────


@app.get("/api/sources")
def sources(session: SessionDep, _: UserDep) -> list[dict[str, Any]]:
    rows = session.scalars(select(Source).order_by(Source.kind, Source.name))
    return [{"id": s.id, "name": s.name, "kind": s.kind, "type": s.type, "enabled": s.enabled} for s in rows]


@app.get("/api/tags")
def tags(session: SessionDep, _: UserDep) -> list[dict[str, Any]]:
    rows = session.scalars(select(AITag).where(AITag.status == "active").order_by(AITag.priority))
    return [{"id": t.id, "name": t.tag, "description": t.description} for t in rows]


@app.get("/api/health/sources")
def source_health(session: SessionDep, _: UserDep, admin: AdminDep) -> dict[str, Any]:
    day_ago = utcnow() - timedelta(days=1)
    latest_ids = select(func.max(SourceStatus.id)).group_by(SourceStatus.source_id)
    latest = {s.source_id: s for s in session.scalars(select(SourceStatus).where(SourceStatus.id.in_(latest_ids)))}
    new_24h = dict(
        session.execute(select(Item.source_id, func.count()).where(Item.first_seen >= day_ago).group_by(Item.source_id)).all()
    )
    out = []
    for source in session.scalars(select(Source).order_by(Source.kind, Source.name)):
        status = latest.get(source.id)
        out.append(
            {
                "id": source.id,
                "name": source.name,
                "kind": source.kind,
                "type": source.type,
                "enabled": source.enabled,
                "configured_backends": (source.config or {}).get("backends") or [],
                "status": status.status if status else ("off" if not source.enabled else "never"),
                "backend": status.backend if status else "",
                "message": status.message if status else "",
                "last_run": iso(status.created_at) if status else None,
                "duration_ms": status.duration_ms if status else 0,
                "items_last_run": status.items_count if status else 0,
                "new_24h": new_24h.get(source.id, 0),
            }
        )
    transcripts = session.execute(
        select(ItemTranscript.status, ItemTranscript.via, func.count(), func.sum(ItemTranscript.audio_seconds))
        .where(ItemTranscript.updated_at >= day_ago)
        .group_by(ItemTranscript.status, ItemTranscript.via)
    ).all()
    videos = {"subtitle_24h": 0, "groq_24h": 0, "audio_minutes_24h": 0, "failed_24h": 0, "processing": 0, "skipped_24h": 0}
    for st, via, count, audio in transcripts:
        if st == "done":
            videos["subtitle_24h" if via == "subtitle" else "groq_24h"] += count
            videos["audio_minutes_24h"] += round((audio or 0) / 60)
        elif st == "error":
            videos["failed_24h"] += count
        elif st == "processing":
            videos["processing"] += count
        elif st == "skipped":
            videos["skipped_24h"] += count
    from radar.doctor import LOGIN_STATUS_KEY

    if not admin:
        # Public view: status and counts only, no tool names, error details or logins.
        for row in out:
            row.update(configured_backends=[], backend="", message="")
        return {"sources": out, "videos": videos, "logins": None, "groq_keys": []}
    from radar.transcribe.groq_pool import GroqKeyPool

    login_row = session.get(Setting, LOGIN_STATUS_KEY)
    logins = json.loads(login_row.value) if login_row else {"checked_at": None, "checks": []}
    groq_keys = GroqKeyPool(list(get_settings().groq_api_keys), session=session).status()
    return {"sources": out, "videos": videos, "logins": logins, "groq_keys": groq_keys}


# ── reports (Giai đoạn 2) ───────────────────────────────────────────


def serialize_report(session: Session, report: Report, full: bool) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": report.id,
        "kind": report.kind,
        "period_start": report.period_start.isoformat(),
        "period_end": report.period_end.isoformat(),
        "created_at": iso(report.created_at),
        "items_considered": report.items_considered,
        "model": report.model,
    }
    if full:
        content = report.content or {}
        ids = {i for section in ("risks", "opportunities") for p in content.get(section, []) for i in p.get("item_ids", [])}
        refs = {i.id: {"id": i.id, "title": i.title, "url": i.url} for i in session.scalars(select(Item).where(Item.id.in_(ids)))} if ids else {}
        data["content"] = content
        data["items"] = refs
    return data


@app.get("/api/reports")
def list_reports(session: SessionDep, _: UserDep) -> list[dict[str, Any]]:
    rows = session.scalars(select(Report).where(Report.kind == "weekly").order_by(Report.period_start.desc()).limit(52))
    return [serialize_report(session, r, full=False) for r in rows]


@app.get("/api/reports/{report_id}")
def get_report(report_id: int, session: SessionDep, _: UserDep) -> dict[str, Any]:
    report = session.get(Report, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy báo cáo")
    return serialize_report(session, report, full=True)


@app.post("/api/reports/weekly")
def create_weekly_report(session: SessionDep, _: UserDep) -> dict[str, Any]:
    from radar.ai.client import AIError
    from radar.pipeline import weekly_report

    try:
        report = weekly_report(session)
    except AIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return serialize_report(session, report, full=True)


# ── settings (Giai đoạn 2) ──────────────────────────────────────────


@app.get("/api/settings")
def get_settings_files(session: SessionDep, _: UserDep) -> list[dict[str, Any]]:
    out = []
    for name in EDITABLE_FILES:
        row = session.get(Setting, name)
        out.append(
            {
                "name": name,
                "value": read_text(name, session),
                "origin": "db" if row else "file",
                "updated_by": row.updated_by if row else "",
                "updated_at": iso(row.updated_at) if row else None,
            }
        )
    return out


class SettingBody(BaseModel):
    value: str


@app.put("/api/settings/{name}")
def put_setting(name: str, body: SettingBody, session: SessionDep, user: UserDep) -> dict[str, Any]:
    if name not in EDITABLE_FILES:
        raise HTTPException(status_code=404, detail="Không có cài đặt này")
    try:
        save_text(session, name, body.value, user)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # yaml errors etc.
        raise HTTPException(status_code=400, detail=f"Nội dung không hợp lệ: {exc}") from exc
    session.commit()
    row = session.get(Setting, name)
    return {"name": name, "value": row.value, "origin": "db", "updated_by": row.updated_by, "updated_at": iso(row.updated_at)}


@app.delete("/api/settings/{name}")
def reset_setting(name: str, session: SessionDep, _: UserDep) -> dict[str, Any]:
    if name not in EDITABLE_FILES:
        raise HTTPException(status_code=404, detail="Không có cài đặt này")
    row = session.get(Setting, name)
    if row is not None:
        session.delete(row)
        session.commit()
    return {"name": name, "value": read_text(name, None), "origin": "file", "updated_by": "", "updated_at": None}


# ── usage & cost (Giai đoạn 2) ──────────────────────────────────────


@app.get("/api/usage")
def usage(session: SessionDep, _: UserDep, days: int = Query(30, ge=1, le=365)) -> dict[str, Any]:
    since = local_midnight(days - 1)
    rows = list(session.scalars(select(AIUsage).where(AIUsage.created_at >= since)))
    by_task: dict[str, dict[str, float]] = defaultdict(lambda: {"calls": 0, "cost": 0.0, "input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0})
    by_day: dict[str, float] = defaultdict(float)
    by_model: dict[str, float] = defaultdict(float)
    for r in rows:
        t = by_task[r.task]
        t["calls"] += 1
        t["cost"] += r.cost_usd
        t["input_tokens"] += r.input_tokens
        t["output_tokens"] += r.output_tokens
        t["cache_read_tokens"] += r.cache_read_tokens
        by_day[aware(r.created_at).astimezone(tz()).date().isoformat()] += r.cost_usd
        by_model[r.model] += r.cost_usd
    today = datetime.now(tz()).date()
    daily = [{"date": (today - timedelta(days=o)).isoformat(), "cost": round(by_day.get((today - timedelta(days=o)).isoformat(), 0.0), 4)} for o in range(days - 1, -1, -1)]
    transcripts = session.execute(
        select(func.count(), func.sum(ItemTranscript.audio_seconds)).where(ItemTranscript.via == "groq", ItemTranscript.status == "done", ItemTranscript.updated_at >= since)
    ).one()
    return {
        "days": days,
        "total_cost": round(sum(r.cost_usd for r in rows), 4),
        "by_task": [{"task": k, **{kk: (round(vv, 4) if kk == "cost" else int(vv)) for kk, vv in v.items()}} for k, v in sorted(by_task.items())],
        "by_model": [{"model": k, "cost": round(v, 4)} for k, v in by_model.items()],
        "daily": daily,
        "groq": {"videos": transcripts[0] or 0, "audio_minutes": round((transcripts[1] or 0) / 60)},
    }
