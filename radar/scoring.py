"""Item score (0–10):

    relevance × w1 + engagement × w2 + cross_source × w3 + recency × w4

- relevance: best active AI score (0..1). Items only matched by keywords get 0.4.
- engagement: log-scaled upvotes/likes/comments/views, capped at 1.
- cross_source: how many other sources carried a similar title in the last 72 h (0..1).
- recency: exponential decay with a configurable half-life, counted from the
  publish date when the source gives one (otherwise from when radar first saw it).

Items that mention a priority topic (config/priorities.txt) get
scoring.priority_boost added on top, capped at 10.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
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


def engagement(metrics: dict[str, Any]) -> float:
    weighted = (
        (metrics.get("upvotes") or 0)
        + (metrics.get("points") or 0)
        + (metrics.get("likes") or 0)
        + 2 * (metrics.get("comments") or 0)
        + 3 * (metrics.get("retweets") or 0)
        + (metrics.get("views") or 0) / 100
    )
    return min(1.0, math.log10(1 + weighted) / 3)  # ~1000 weighted interactions → 1.0


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
    session.flush()
    return len(items)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
