"""Batch classification with Claude (TrendRadar's two-stage AI filter, step 2).

Candidates are items not yet analyzed, seen in the last `reclassify_days`,
that passed the keyword filter (platform sources always pass). Each Claude
call classifies `batch_size` items and returns tag, relevance, sentiment,
impact, who it affects (theme code, theme partners, merchants), deadline and a
Vietnamese summary. Items are recorded in ai_analyzed
whether or not they matched, so they are never sent twice. A failed batch is
left unrecorded: those items stay visible through their keyword match
(the keyword fallback) and are retried on the next run.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from radar.ai.client import AIError, CallSpec, ClaudeClient
from radar.ai.tags import sync_tags
from radar.config_loader import RadarConfig, load_prompt
from radar.models import (
    AIAnalyzed,
    AIResult,
    AITag,
    Item,
    ItemStatus,
    ItemTranscript,
    Setting,
    Source,
    utcnow,
)

log = logging.getLogger(__name__)

PENDING_BATCH_KEY = "_pending_batch_classify"

NULLABLE_IMPACT = {"anyOf": [{"type": "string", "enum": ["high", "med", "low"]}, {"type": "null"}]}
NULLABLE_DATE = {"anyOf": [{"type": "string"}, {"type": "null"}]}
# theme: theme code must change or can use it; partner: theme sellers on the Theme Store
# (review, listing, policy, revenue); merchant: stores using the theme (editor, features).
AUDIENCES = ("theme", "partner", "merchant")

CLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "tag_id": {"type": "integer"},
                    "score": {"type": "number"},
                    "sentiment": {"type": "string", "enum": ["neg", "neu", "pos"]},
                    "impact": NULLABLE_IMPACT,
                    "affects": {"type": "array", "items": {"type": "string", "enum": list(AUDIENCES)}},
                    "deadline": NULLABLE_DATE,
                    "summary": {"type": "string"},
                },
                "required": ["id", "tag_id", "score", "sentiment", "impact", "affects", "deadline", "summary"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["results"],
    "additionalProperties": False,
}


@dataclass
class ClassifyStats:
    sent: int = 0
    matched: int = 0
    failed_batches: int = 0
    errors: list[str] = field(default_factory=list)
    pending_batch: str = ""


def pending_items(session: Session, config: RadarConfig) -> list[Item]:
    days = int(config.ai.get("reclassify_days", 14))
    limit = int(config.ai.get("max_items_per_run", 400))
    since = utcnow() - timedelta(days=days)
    analyzed = select(AIAnalyzed.item_id)
    dismissed = select(ItemStatus.item_id).where(ItemStatus.status == "dismissed")
    transcribed = select(ItemTranscript.item_id).where(ItemTranscript.status == "done")
    stmt = (
        select(Item)
        .join(Source, Source.id == Item.source_id)
        .where(
            Item.first_seen >= since,
            Item.id.not_in(analyzed),
            Item.id.not_in(dismissed),
            or_(Item.keyword_matched.is_(True), Source.kind == "platform", Item.id.in_(transcribed)),
        )
        .order_by(Item.official.desc(), Item.priority.is_(None), Item.first_seen.desc())
        .limit(limit)
    )
    return list(session.scalars(stmt))


def render_items(items: list[Item], source_names: dict[str, tuple[str, str]], chars: int) -> str:
    blocks = []
    for item in items:
        name, kind = source_names.get(item.source_id, (item.source_id, ""))
        content = " ".join((item.content or "").split())[:chars]
        flag = " · CHÍNH THỨC" if item.official else ""
        lines = [f"[id={item.id}] nguồn: {name} ({kind}){flag} · loại: {item.media_type}", f"Tiêu đề: {item.title}"]
        if content:
            lines.append(f"Nội dung: {content}")
        if item.extra.get("edition"):
            lines.append(f"Edition: {item.extra['edition']}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def render_tags(tags: list[AITag]) -> str:
    return "\n".join(f"{t.id}. {t.tag} — {t.description}" for t in tags)


def dismissed_examples(session: Session, limit: int = 20) -> str:
    rows = session.scalars(
        select(Item.title)
        .join(ItemStatus, ItemStatus.item_id == Item.id)
        .where(ItemStatus.status == "dismissed")
        .order_by(ItemStatus.updated_at.desc())
        .limit(limit)
    ).all()
    return "\n".join(f"- {title}" for title in rows) or "(chưa có)"


def build_spec(session: Session, config: RadarConfig, tags: list[AITag], items: list[Item]) -> CallSpec:
    names = {s.id: (s.name, s.kind) for s in session.scalars(select(Source))}
    prompt = load_prompt(
        "classify",
        interests=config.interests,
        tags=render_tags(tags),
        dismissed=dismissed_examples(session),
        count=len(items),
        items=render_items(items, names, int(config.ai.get("content_chars", 500))),
    )
    return CallSpec(
        "classify",
        prompt.system,
        prompt.user,
        CLASSIFY_SCHEMA,
        effort=config.ai.get("classify_effort", "low"),
        max_tokens=16000,
    )


def _parse_deadline(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def affects_value(value: Any) -> str | None:
    chosen = set(value) if isinstance(value, list) else set()
    return ",".join(a for a in AUDIENCES if a in chosen) or None


def apply_results(
    session: Session,
    config: RadarConfig,
    items: list[Item],
    tags: list[AITag],
    data: dict[str, Any],
) -> int:
    tag_ids = {t.id for t in tags}
    min_score = float(config.ai.get("min_score", 0.5))
    by_id = {item.id: item for item in items}
    best: dict[int, dict[str, Any]] = {}
    for row in data.get("results", []):
        item_id, tag_id = row.get("id"), row.get("tag_id")
        if item_id not in by_id or tag_id not in tag_ids:
            continue
        score = max(0.0, min(1.0, float(row.get("score") or 0)))
        if item_id not in best or score > best[item_id]["score"]:
            best[item_id] = {**row, "score": score}

    prompt_hash = config.interests_hash
    matched = 0
    for item in items:
        result = best.get(item.id)
        for old in list(item.results):
            if old.status == "active":
                item.results.remove(old)  # delete-orphan removes the row
        session.flush()
        is_match = bool(result and result["score"] >= min_score)
        if result:
            impact = result.get("impact") if result.get("impact") in ("high", "med", "low") else None
            item.results.append(
                AIResult(
                    tag_id=result["tag_id"],
                    score=result["score"],
                    sentiment=result.get("sentiment") if result.get("sentiment") in ("neg", "neu", "pos") else "neu",
                    impact=impact,
                    affects=affects_value(result.get("affects")),
                    deadline=_parse_deadline(result.get("deadline")),
                )
            )
            if result.get("summary"):
                item.summary = result["summary"].strip()
        matched += int(is_match)
        existing = session.get(AIAnalyzed, item.id)
        if existing is None:
            session.add(AIAnalyzed(item_id=item.id, prompt_hash=prompt_hash, method="ai", matched=is_match))
        else:
            existing.prompt_hash, existing.method, existing.matched, existing.analyzed_at = prompt_hash, "ai", is_match, utcnow()
    session.flush()
    return matched


def _chunks(items: list[Item], size: int) -> list[list[Item]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def classify(session: Session, config: RadarConfig, claude: ClaudeClient) -> ClassifyStats:
    stats = ClassifyStats()
    sync = sync_tags(session, config, claude)
    session.commit()
    if not sync.tags:
        stats.errors.append("Không có tag nào")
        return stats

    if config.ai.get("use_batch_api"):
        return _classify_with_batches(session, config, claude, sync.tags, stats)

    items = pending_items(session, config)
    for chunk in _chunks(items, int(config.ai.get("batch_size", 50))):
        stats.sent += len(chunk)
        try:
            data = claude.call_json(build_spec(session, config, sync.tags, chunk))
        except AIError as exc:
            stats.failed_batches += 1
            stats.errors.append(str(exc))
            log.warning("Classification batch failed, keeping keyword fallback: %s", exc)
            session.commit()  # keep the usage row even when parsing failed
            continue
        stats.matched += apply_results(session, config, chunk, sync.tags, data)
        session.commit()
    return stats


def _classify_with_batches(
    session: Session, config: RadarConfig, claude: ClaudeClient, tags: list[AITag], stats: ClassifyStats
) -> ClassifyStats:
    """Message Batches API: submit now, collect on this or a later run."""
    pending = session.get(Setting, PENDING_BATCH_KEY)
    if pending is not None:
        info = json.loads(pending.value)
        if not claude.batch_ended(info["batch_id"]):
            stats.pending_batch = info["batch_id"]
            return stats
        results = claude.batch_results(info["batch_id"], "classify")
        for custom_id, item_ids in info["chunks"].items():
            outcome = results.get(custom_id)
            items = list(session.scalars(select(Item).where(Item.id.in_(item_ids))))
            if isinstance(outcome, dict):
                stats.matched += apply_results(session, config, items, tags, outcome)
            else:
                stats.failed_batches += 1
                stats.errors.append(str(outcome))
        session.delete(pending)
        session.commit()

    items = pending_items(session, config)
    if not items:
        return stats
    chunks = {f"classify-{i}": chunk for i, chunk in enumerate(_chunks(items, int(config.ai.get("batch_size", 50))))}
    batch_id = claude.submit_batch({cid: build_spec(session, config, tags, chunk) for cid, chunk in chunks.items()})
    session.add(
        Setting(
            key=PENDING_BATCH_KEY,
            value=json.dumps({"batch_id": batch_id, "chunks": {cid: [i.id for i in c] for cid, c in chunks.items()}}),
            updated_by="worker",
        )
    )
    session.commit()
    stats.sent = len(items)
    stats.pending_batch = batch_id
    return stats
