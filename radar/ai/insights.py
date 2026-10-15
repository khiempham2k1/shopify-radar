"""Weekly report (Giai đoạn 2): risks, opportunities and actions written by Claude."""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from radar.ai.client import CallSpec, ClaudeClient
from radar.config_loader import RadarConfig, load_prompt
from radar.models import AIResult, Item, Report, Source
from radar.settings import get_settings

POINT = {
    "type": "object",
    "properties": {"text": {"type": "string"}, "item_ids": {"type": "array", "items": {"type": "integer"}}},
    "required": ["text", "item_ids"],
    "additionalProperties": False,
}

REPORT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "risks": {"type": "array", "items": POINT},
        "opportunities": {"type": "array", "items": POINT},
        "actions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"text": {"type": "string"}, "owner": {"type": "string"}},
                "required": ["text", "owner"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["summary", "risks", "opportunities", "actions"],
    "additionalProperties": False,
}


def last_full_week(today: date) -> tuple[date, date]:
    """Monday..Sunday of the week before `today`."""
    start = today - timedelta(days=today.weekday() + 7)
    return start, start + timedelta(days=6)


def _bounds(start: date, end: date) -> tuple[datetime, datetime]:
    tz = ZoneInfo(get_settings().timezone)
    return (
        datetime.combine(start, time.min, tz).astimezone(timezone.utc),
        datetime.combine(end + timedelta(days=1), time.min, tz).astimezone(timezone.utc),
    )


def _matched_items(session: Session, start: datetime, end: datetime, min_score: float) -> list[Item]:
    matched = select(AIResult.item_id).where(AIResult.status == "active", AIResult.score >= min_score)
    stmt = (
        select(Item)
        # Priority-topic items go in even when Claude scored them low.
        .where(Item.first_seen >= start, Item.first_seen < end, or_(Item.id.in_(matched), Item.priority.is_not(None)))
        .options(selectinload(Item.results).selectinload(AIResult.tag))
        .order_by(Item.score.desc())
        .distinct()
    )
    return list(session.scalars(stmt).unique())


def _tag_counts(items: list[Item]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for item in items:
        for result in item.results:
            if result.status == "active":
                counts[result.tag.tag] += 1
    return counts


def build_report(session: Session, config: RadarConfig, claude: ClaudeClient, today: date | None = None) -> Report:
    today = today or datetime.now(ZoneInfo(get_settings().timezone)).date()
    period_start, period_end = last_full_week(today)
    start, end = _bounds(period_start, period_end)
    prev_start, prev_end = _bounds(period_start - timedelta(days=7), period_end - timedelta(days=7))
    min_score = float(config.ai.get("min_score", 0.5))
    limit = int(config.ai.get("report_max_items", 150))

    items = _matched_items(session, start, end, min_score)
    previous = _matched_items(session, prev_start, prev_end, min_score)
    kinds = {s.id: s.kind for s in session.scalars(select(Source))}
    names = {s.id: s.name for s in session.scalars(select(Source))}

    now_counts, prev_counts = _tag_counts(items), _tag_counts(previous)
    tag_lines = "\n".join(f"- {tag}: {n} / {prev_counts.get(tag, 0)}" for tag, n in now_counts.most_common()) or "(không có)"

    def line(item: Item) -> str:
        result = max((r for r in item.results if r.status == "active"), key=lambda r: r.score, default=None)
        parts = [f"[{item.id}] {item.title}", f"nguồn: {names.get(item.source_id, item.source_id)}", f"điểm: {item.score:.1f}"]
        if item.priority:
            parts.append(f"ưu tiên: {item.priority}")
        if result is not None:
            parts.append(f"tag: {result.tag.tag}")
            if result.affects:
                parts.append(f"ảnh hưởng tới: {result.affects}")
            if result.impact:
                parts.append(f"mức ảnh hưởng: {result.impact}")
            if result.deadline:
                parts.append(f"hạn: {result.deadline.isoformat()}")
            parts.append(f"cảm xúc: {result.sentiment}")
        text = " | ".join(parts)
        if item.summary:
            text += f"\n    {item.summary}"
        return text

    platform = [i for i in items if kinds.get(i.source_id) == "platform"][: limit // 3]
    feed = [i for i in items if kinds.get(i.source_id) != "platform"][: limit - len(platform)]
    prompt = load_prompt(
        "weekly_report",
        interests=config.interests,
        period_start=period_start.strftime("%d/%m/%Y"),
        period_end=period_end.strftime("%d/%m/%Y"),
        total=len(items),
        tag_counts=tag_lines,
        platform="\n".join(line(i) for i in platform) or "(không có)",
        feed="\n".join(line(i) for i in feed) or "(không có)",
    )
    data = claude.call_json(
        CallSpec("report", prompt.system, prompt.user, REPORT_SCHEMA, effort=config.ai.get("report_effort", "high"), max_tokens=16000)
    )
    known = {i.id for i in platform + feed}
    for section in ("risks", "opportunities"):
        for point in data.get(section, []):
            point["item_ids"] = [i for i in point.get("item_ids", []) if i in known]
    data["tag_counts"] = [{"tag": tag, "count": n, "previous": prev_counts.get(tag, 0)} for tag, n in now_counts.most_common()]

    report = session.scalar(
        select(Report).where(Report.kind == "weekly", Report.period_start == period_start, Report.period_end == period_end)
    )
    if report is None:
        report = Report(kind="weekly", period_start=period_start, period_end=period_end)
        session.add(report)
    report.content, report.items_considered, report.model = data, len(items), claude.model
    session.flush()
    return report
