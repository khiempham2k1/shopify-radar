"""Run collectors and store what they return.

Items are unique by (source, url). Seeing an item again bumps last_seen and
seen_count and appends its metrics to item_metrics_history (TrendRadar's
rank_history idea). Each source run writes one source_status row.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from radar.collectors import CollectedItem, Http, make_collector
from radar.collectors.web import WebSearchCollector
from radar.config_loader import RadarConfig
from radar.filter.keywords import KeywordConfig
from radar.models import (
    CrawlRun,
    Item,
    ItemMetricsHistory,
    Source,
    SourceStatus,
    utcnow,
)

log = logging.getLogger(__name__)


@dataclass
class IngestStats:
    new: int = 0
    seen: int = 0
    blocked: int = 0


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
) -> IngestStats:
    now = now or utcnow()
    stats = IngestStats()
    source = session.get(Source, source_id)
    # keyword_filter: false lets every item of a source through to Claude (useful for
    # YouTube, where the title alone says little until the video has been listened to).
    use_keywords = bool((source.config or {}).get("keyword_filter", True)) if source else True
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
            if keywords.is_blocked(text):
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
                keyword_matched=bool(groups) or keywords.empty or not use_keywords,
            )
            session.add(row)
            session.flush()
            stats.new += 1
        else:
            row.last_seen = now
            row.seen_count += 1
            if data.metrics:
                row.metrics = {**(row.metrics or {}), **data.metrics}
            if data.content and not row.content:
                row.content = data.content
            stats.seen += 1
        if data.metrics:
            session.add(ItemMetricsHistory(item_id=row.id, captured_at=now, metrics=data.metrics))
    session.flush()
    return stats


def collect_all(
    session: Session,
    config: RadarConfig,
    only: list[str] | None = None,
    http: Http | None = None,
) -> CrawlRun:
    sync_sources(session, config)
    run = CrawlRun(started_at=utcnow())
    session.add(run)
    session.flush()
    http = http or Http()
    for source in config.sources:
        if only and source["id"] not in only:
            continue
        started = time.monotonic()
        collector = make_collector(source, http)
        result = collector.collect()
        if isinstance(collector, WebSearchCollector):
            for item in result.items:
                collector.enrich(item)
        for item in result.items:
            item.media_type = item.media_type or source.get("media_type", "post")
        stats = store_items(session, source["id"], result.items, config.keywords)
        run.items_new += stats.new
        run.items_seen += stats.seen
        message = result.message
        if result.status != "error":
            message = (f"{stats.new} mới, {stats.seen} đã có" + (f", {stats.blocked} bị loại" if stats.blocked else "") + (f". {message}" if message else ""))
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


def prune_old(session: Session, retention_days: int) -> int:
    if retention_days <= 0:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    result = session.execute(delete(Item).where(Item.last_seen < cutoff).execution_options(synchronize_session=False))
    session.execute(delete(SourceStatus).where(SourceStatus.created_at < cutoff).execution_options(synchronize_session=False))
    return result.rowcount or 0
