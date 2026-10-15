"""Run collectors and store what they return.

Items are unique by (source, url). Seeing an item again bumps last_seen and
seen_count and appends its metrics to item_metrics_history (TrendRadar's
rank_history idea). Each source run writes one source_status row.

Only fresh items are stored: anything published longer ago than the source's
max_age_days is skipped, so a search that surfaces a three-year-old video does
not bring it into the dashboard. Priority topics (config/priorities.txt) are
added to every source's search queries and always pass the keyword filter.

The same post is stored once across sources (radar/dedupe.py): when a new item
shares a key with an item already stored (same page, same tweet, or for
announcement sources the same shared link or text), it is attached to that
item under extra.also instead of becoming a new row.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, or_, select, update
from sqlalchemy.orm import Session

from radar.collectors import CollectedItem, Http, make_collector
from radar.collectors.web import WebSearchCollector
from radar.config_loader import RadarConfig
from radar.dedupe import hashed, item_keys
from radar.official import is_official, official_first
from radar.filter.keywords import KeywordConfig
from radar.models import (
    AIAnalyzed,
    AIResult,
    CrawlRun,
    Item,
    ItemKey,
    ItemMetricsHistory,
    ItemStatus,
    ItemTranscript,
    Source,
    SourceStatus,
    utcnow,
)
from radar.priority import PriorityTopic, priority_value

log = logging.getLogger(__name__)


@dataclass
class IngestStats:
    new: int = 0
    seen: int = 0
    blocked: int = 0
    too_old: int = 0
    merged: int = 0


def sync_sources(session: Session, config: RadarConfig) -> None:
    """Mirror sources.yaml into the sources table (disabled ones stay for history)."""
    configured = {s["id"]: s for s in config.raw.get("sources", [])}
    for source_id, data in configured.items():
        row = session.get(Source, source_id)
        fields = {
            "name": data.get("name", source_id),
            "type": data.get("type", ""),
            "kind": data.get("kind", "web"),
            "enabled": bool(data.get("enabled", True)),
            "config": data,
        }
        if row is None:
            session.add(Source(id=source_id, **fields))
        else:
            for key, value in fields.items():
                setattr(row, key, value)
    for row in session.scalars(select(Source)):
        if row.id not in configured:
            row.enabled = False
    session.flush()


def store_items(
    session: Session,
    source_id: str,
    collected: list[CollectedItem],
    keywords: KeywordConfig,
    now: datetime | None = None,
    max_age_days: int = 0,
    priorities: list[PriorityTopic] | None = None,
    official_settings: dict | None = None,
) -> IngestStats:
    now = now or utcnow()
    stats = IngestStats()
    source = session.get(Source, source_id)
    source_config = (source.config or {}) if source else {}
    # keyword_filter: false lets every item of a source through to Claude (useful for
    # YouTube, where the title alone says little until the video has been listened to).
    use_keywords = bool(source_config.get("keyword_filter", True))
    # drop_undated: true skips items without a publish date (search results that
    # could be years old), only when a max age is set.
    drop_undated = bool(source_config.get("drop_undated", False)) and max_age_days > 0
    cutoff = now - timedelta(days=max_age_days) if max_age_days > 0 else None
    unique: dict[str, CollectedItem] = {}
    for item in collected:
        if item.url and item.title:
            unique.setdefault(item.url[:1000], item)
    if not unique:
        return stats
    existing = {
        row.url: row
        for row in session.scalars(select(Item).where(Item.source_id == source_id, Item.url.in_(list(unique))))
    }
    for url, data in unique.items():
        text = f"{data.title}\n{data.content}"
        row = existing.get(url)
        if row is None:
            if cutoff is not None and (
                (data.published_at is not None and _aware(data.published_at) < cutoff)
                or (data.published_at is None and drop_undated)
            ):
                stats.too_old += 1
                continue
            keys = hashed(item_keys(url, data.extra, data.title, data.content, source_config))
            official = is_official(url, {**source_config, "kind": source.kind if source else ""}, official_settings)
            owner_id = session.scalar(select(ItemKey.item_id).where(ItemKey.key.in_(keys)).limit(1))
            owner = session.get(Item, owner_id) if owner_id is not None else None
            # The official version of a story always wins: it replaces a copy stored earlier from elsewhere.
            replaces = owner if owner is not None and official and not owner.official else None
            if replaces is not None:
                owner = None
            if owner is not None:
                attach_duplicate(session, owner, source_id, source.name if source else source_id, data, keys, now)
                stats.merged += 1
                continue
            if owner_id is not None and replaces is None:  # key left behind by a deleted item
                session.execute(delete(ItemKey).where(ItemKey.item_id == owner_id))
            priority = priority_value(priorities or [], text)
            if keywords.is_blocked(text) and not priority:
                stats.blocked += 1
                continue
            groups = keywords.match(text)
            row = Item(
                source_id=source_id,
                url=url,
                external_id=data.external_id[:200],
                title=data.title[:2000],
                content=data.content,
                author=data.author[:200],
                media_type=data.media_type,
                published_at=data.published_at,
                first_seen=now,
                last_seen=now,
                metrics=data.metrics,
                extra=data.extra,
                keyword_groups=groups,
                keyword_matched=bool(groups) or bool(priority) or keywords.empty or not use_keywords,
                priority=priority,
                official=official,
            )
            session.add(row)
            session.flush()
            if replaces is not None:
                take_over(session, row, replaces, now)
                stats.merged += 1
            add_keys(session, row.id, keys)
            stats.new += 1
        else:
            row.last_seen = now
            row.seen_count += 1
            if data.metrics:
                row.metrics = {**(row.metrics or {}), **data.metrics}
            if data.content and not row.content:
                row.content = data.content
            if data.published_at and not row.published_at:
                row.published_at = data.published_at
            posted_by = (data.extra or {}).get("posted_by")
            if posted_by:
                merged = list(dict.fromkeys([*(row.extra or {}).get("posted_by", []), *posted_by]))
                row.extra = {**(row.extra or {}), "posted_by": merged}
            stats.seen += 1
        if data.metrics:
            session.add(ItemMetricsHistory(item_id=row.id, captured_at=now, metrics=data.metrics))
    session.flush()
    return stats


def add_keys(session: Session, item_id: int, keys: list[str]) -> None:
    taken = set(session.scalars(select(ItemKey.key).where(ItemKey.key.in_(keys))))
    for key in keys:
        if key not in taken:
            session.add(ItemKey(key=key, item_id=item_id))
    session.flush()


def attach_duplicate(session: Session, target: Item, source_id: str, source_name: str, data: CollectedItem, keys: list[str], now: datetime) -> None:
    """Record that `data` repeats `target` (another account, another source) without storing it again."""
    also = list((target.extra or {}).get("also", []))
    if not any(a.get("url") == data.url for a in also) and data.url != target.url:
        also.append(
            {
                "source": source_id,
                "source_name": source_name,
                "url": data.url,
                "author": data.author,
                "posted_by": (data.extra or {}).get("posted_by", []),
            }
        )
    extra = {**(target.extra or {}), "also": also[-20:]}
    if data.extra.get("posted_by") and target.source_id == source_id:
        extra["posted_by"] = list(dict.fromkeys([*extra.get("posted_by", []), *data.extra["posted_by"]]))
    target.extra = extra
    target.last_seen = now
    add_keys(session, target.id, keys)


def take_over(session: Session, official: Item, copy: Item, now: datetime) -> None:
    """`official` replaces `copy` (same story found earlier elsewhere): the copy becomes an
    "also on" entry of the official item, its keys move over, and the copy row goes."""
    source = session.get(Source, copy.source_id)
    also = [a for a in (copy.extra or {}).get("also", []) if a.get("url") != official.url]
    also.append(
        {
            "source": copy.source_id,
            "source_name": source.name if source else copy.source_id,
            "url": copy.url,
            "author": copy.author,
            "posted_by": (copy.extra or {}).get("posted_by", []),
        }
    )
    official.extra = {**(official.extra or {}), "also": also[-20:]}
    official.last_seen = now
    session.execute(update(ItemKey).where(ItemKey.item_id == copy.id).values(item_id=official.id).execution_options(synchronize_session=False))
    copy_id = copy.id
    session.flush()
    delete_items(session, [copy_id])


def ensure_url_keys(session: Session) -> int:
    """Give items stored before item_keys existed their URL key (once)."""
    keyed = select(ItemKey.item_id)
    rows = session.execute(select(Item.id, Item.url, Item.extra).where(Item.id.not_in(keyed))).all()
    taken = set(session.scalars(select(ItemKey.key)))
    added = 0
    for item_id, url, extra in rows:
        for key in hashed(item_keys(url, {"dedupe_keys": (extra or {}).get("dedupe_keys", [])})):
            if key not in taken:
                session.add(ItemKey(key=key, item_id=item_id))
                taken.add(key)
                added += 1
    session.flush()
    return added


def collect_all(
    session: Session,
    config: RadarConfig,
    only: list[str] | None = None,
    http: Http | None = None,
) -> CrawlRun:
    sync_sources(session, config)
    ensure_url_keys(session)
    run = CrawlRun(started_at=utcnow())
    session.add(run)
    session.flush()
    http = http or Http()
    for source in official_first(config.sources):  # Shopify's own sources first
        if only and source["id"] not in only:
            continue
        started = time.monotonic()
        max_age = config.max_age_days(source)
        source = with_priority_queries({**source, "max_age_days": max_age}, config.priorities)
        collector = make_collector(source, http)
        result = collector.collect()
        if isinstance(collector, WebSearchCollector):
            for item in result.items:
                collector.enrich(item)
        for item in result.items:
            item.media_type = item.media_type or source.get("media_type", "post")
        stats = store_items(
            session, source["id"], result.items, config.keywords, max_age_days=max_age, priorities=config.priorities, official_settings=config.official
        )
        run.items_new += stats.new
        run.items_seen += stats.seen
        message = result.message
        if result.status != "error":
            message = (
                f"{stats.new} mới, {stats.seen} đã có"
                + (f", {stats.blocked} bị loại" if stats.blocked else "")
                + (f", {stats.too_old} quá {max_age} ngày nên bỏ qua" if stats.too_old else "")
                + (f", {stats.merged} trùng nên gộp vào bài đã có" if stats.merged else "")
                + (f". {message}" if message else "")
            )
        session.add(
            SourceStatus(
                crawl_run_id=run.id,
                source_id=source["id"],
                status=result.status,
                backend=result.backend,
                message=message[:2000],
                items_count=len(result.items),
                duration_ms=int((time.monotonic() - started) * 1000),
            )
        )
        session.commit()
        log.info("Source %s: %s via %s (%d items)", source["id"], result.status, result.backend or "-", len(result.items))
    run.finished_at = utcnow()
    session.commit()
    return run


def with_priority_queries(source: dict, priorities: list[PriorityTopic]) -> dict:
    """Search priority topics too on sources that take queries (priority_search: false opts out)."""
    if not priorities or "queries" not in source or not source.get("priority_search", True):
        return source
    queries = list(source.get("queries") or [])
    known = {q.strip().strip('"').lower() for q in queries}
    extra = [t.query for t in priorities if t.query.lower() not in known]
    return {**source, "queries": queries + extra} if extra else source


def prune_stale(session: Session, config: RadarConfig, now: datetime | None = None) -> int:
    """Remove items published before their source's max age (or undated, where the
    source drops undated items) that nobody has picked up. Cleans what older runs
    stored before the age filter existed."""
    now = now or utcnow()
    handled = select(ItemStatus.item_id).where(ItemStatus.status.in_(["doing", "done"]))
    removed = 0
    for source in config.sources:
        days = config.max_age_days(source)
        if days <= 0:
            continue
        stale = Item.published_at < now - timedelta(days=days)
        if source.get("drop_undated"):
            stale = or_(stale, Item.published_at.is_(None))
        ids = list(session.scalars(select(Item.id).where(Item.source_id == source["id"], stale, Item.id.not_in(handled))))
        if ids:
            delete_items(session, ids)
            removed += len(ids)
    return removed


def delete_items(session: Session, ids: list[int]) -> None:
    """Delete items and their child rows explicitly: SQLite does not enforce ON DELETE CASCADE."""
    for model in (ItemKey, ItemMetricsHistory, AIResult, AIAnalyzed, ItemStatus, ItemTranscript):
        session.execute(delete(model).where(model.item_id.in_(ids)).execution_options(synchronize_session=False))
    session.execute(delete(Item).where(Item.id.in_(ids)).execution_options(synchronize_session=False))
    session.expire_all()


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def prune_old(session: Session, retention_days: int) -> int:
    if retention_days <= 0:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    ids = list(session.scalars(select(Item.id).where(Item.last_seen < cutoff)))
    if ids:
        delete_items(session, ids)
    session.execute(delete(SourceStatus).where(SourceStatus.created_at < cutoff).execution_options(synchronize_session=False))
    return len(ids)
