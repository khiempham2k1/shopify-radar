"""Item score (0–10):

    relevance × w1 + engagement × w2 + cross_source × w3 + recency × w4

- relevance: best active AI score (0..1). Items only matched by keywords get 0.4.
- engagement: log-scaled upvotes/likes/comments/views, capped at 1.
- cross_source: how many other sources carried a similar title in the last 72 h (0..1).
- recency: exponential decay with a configurable half-life, counted from the
  publish date when the source gives one (otherwise from when radar first saw it).

Items that mention a priority topic (config/priorities.txt) get
scoring.priority_boost added on top, capped at 10.

Hot (0–10), what the Feed sorts by: how much interaction an item got compared
with other items from the same source (a percentile, so YouTube views do not
drown Reddit upvotes), plus a bonus when other sources carry the same story,
halved every scoring.hot_half_life_hours since it was published.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from radar.config_loader import RadarConfig
from radar.models import AIAnalyzed, AIResult, Item
from radar.priority import priority_value

STOPWORDS = {
    "the", "a", "an", "and", "or", "for", "to", "of", "in", "on", "with", "is", "are", "how", "what",
    "my", "your", "i", "it", "this", "that", "from", "new", "shopify", "can", "do", "does", "not",
}


def title_tokens(title: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]{3,}", title.lower()) if w not in STOPWORDS}


def similar(a: set[str], b: set[str], threshold: float = 0.5) -> bool:
    if not a or not b:
        return False
    return len(a & b) / len(a | b) >= threshold


def weighted_engagement(metrics: dict[str, Any]) -> float:
    return float(
        (metrics.get("upvotes") or 0)
        + (metrics.get("points") or 0)
        + (metrics.get("likes") or 0)
        + 2 * (metrics.get("comments") or 0)
        + 3 * (metrics.get("retweets") or 0)
        + (metrics.get("views") or 0) / 100
    )


def engagement(metrics: dict[str, Any]) -> float:
    return min(1.0, math.log10(1 + weighted_engagement(metrics)) / 3)  # ~1000 weighted interactions → 1.0


def engagement_percentiles(items: list[Item]) -> dict[int, float]:
    """Per source: 1.0 for the most-interacted item, down to ~0 for the least.
    Items with no interaction get 0.05; a source that reports no metrics at all
    (web pages, RSS) gets a neutral 0.3 so recency still ranks them."""
    by_source: dict[str, list[tuple[float, int]]] = {}
    for item in items:
        by_source.setdefault(item.source_id, []).append((weighted_engagement(item.metrics or {}), item.id))
    out: dict[int, float] = {}
    for rows in by_source.values():
        positive = sorted(r for r in rows if r[0] > 0)
        for rank, (_, item_id) in enumerate(positive, start=1):
            out[item_id] = rank / len(positive)
        empty = 0.05 if positive else 0.3
        for value, item_id in rows:
            if value <= 0:
                out[item_id] = empty
    return out


def hot_score(percentile: float, sources_elsewhere: int, age_start: datetime, now: datetime, half_life_hours: float) -> float:
    heat = min(1.0, percentile + 0.15 * sources_elsewhere)
    age_hours = max(0.0, (now - _aware(age_start)).total_seconds() / 3600)
    return round(10 * heat * 0.5 ** (age_hours / half_life_hours), 2)


def recency(first_seen: datetime, now: datetime, half_life_hours: float, published_at: datetime | None = None) -> float:
    start = _aware(first_seen)
    if published_at is not None:
        start = min(start, _aware(published_at))
    age_hours = max(0.0, (now - start).total_seconds() / 3600)
    return 0.5 ** (age_hours / half_life_hours)


def compute_score(relevance: float, engage: float, cross: float, recent: float, weights: dict[str, float]) -> float:
    total = (
        relevance * weights.get("relevance", 0.5)
        + engage * weights.get("engagement", 0.2)
        + cross * weights.get("cross_source", 0.15)
        + recent * weights.get("recency", 0.15)
    )
    norm = sum(weights.get(k, 0) for k in ("relevance", "engagement", "cross_source", "recency")) or 1.0
    return round(10 * total / norm, 2)


def rescore(session: Session, config: RadarConfig, days: int = 14, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    weights = config.scoring.get("weights") or {}
    half_life = float(config.scoring.get("recency_half_life_hours", 48))
    min_score = float(config.ai.get("min_score", 0.5))
    boost = float(config.scoring.get("priority_boost", 2.0))
    hot_half_life = float(config.scoring.get("hot_half_life_hours", 24))
    since = now - timedelta(days=days)
    items = list(session.scalars(select(Item).where(Item.last_seen >= since)))
    best = dict(
        session.execute(
            select(AIResult.item_id, func.max(AIResult.score)).where(AIResult.status == "active").group_by(AIResult.item_id)
        ).all()
    )
    analyzed = set(session.scalars(select(AIAnalyzed.item_id)))

    tokens = {item.id: title_tokens(item.title) for item in items}
    window = now - timedelta(hours=72)
    recent_items = [i for i in items if _aware(i.first_seen) >= window]
    percentiles = engagement_percentiles(items)

    for item in items:
        # Recomputed every run so edits to priorities.txt apply to recent items too.
        item.priority = priority_value(config.priorities, f"{item.title}\n{item.summary}\n{item.content}")
        if item.priority:
            item.keyword_matched = True  # so Claude classifies it even if no keyword group matched
        if item.id in best:
            relevance = float(best[item.id])
            relevance = relevance if relevance >= min_score else relevance * 0.5
        elif item.id not in analyzed and item.keyword_matched:
            relevance = 0.4  # keyword fallback until Claude has seen it
        else:
            relevance = 0.0
        others = {
            other.source_id
            for other in recent_items
            if other.source_id != item.source_id and similar(tokens[item.id], tokens[other.id])
        }
        cross = min(1.0, len(others) / 3)
        score = compute_score(relevance, engagement(item.metrics or {}), cross, recency(item.first_seen, now, half_life, item.published_at), weights)
        item.score = min(10.0, round(score + boost, 2)) if item.priority else score
        # Same story elsewhere: similar titles in other sources, plus merged duplicates (extra.also).
        elsewhere = others | {a.get("source") for a in (item.extra or {}).get("also", []) if a.get("source") != item.source_id}
        started = min(_aware(item.first_seen), _aware(item.published_at)) if item.published_at else item.first_seen
        item.hot = hot_score(percentiles.get(item.id, 0.0), len(elsewhere - {None}), started, now, hot_half_life)
    # Items outside the window are not rescored; they are no longer hot.
    session.execute(update(Item).where(Item.last_seen < since, Item.hot > 0).values(hot=0.0).execution_options(synchronize_session=False))
    session.flush()
    return len(items)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
