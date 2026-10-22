"""Weekly report (Giai đoạn 2): risks, opportunities and actions written by Claude.

Claude reads the week's classified items, the community digests of the week and
how complete the data is: which sources failed or brought nothing, how many
items are still unclassified, how many items it is shown out of how many. Facts
the page shows as tables (tag counts, coverage per source, deadlines) are built
from the database, not written by Claude. Items the team dismissed are left out.
"""

from __future__ import annotations

from collections import Counter
from typing import Any
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from radar.ai.client import CallSpec, ClaudeClient
from radar.config_loader import RadarConfig, load_prompt
from radar.models import AIAnalyzed, AIResult, Item, ItemStatus, Report, Source, SourceStatus
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


def dismissed_ids():
    return select(ItemStatus.item_id).where(ItemStatus.status == "dismissed")


def _matched_items(session: Session, start: datetime, end: datetime, min_score: float) -> list[Item]:
    matched = select(AIResult.item_id).where(AIResult.status == "active", AIResult.score >= min_score)
    stmt = (
        select(Item)
        # Priority-topic items go in even when Claude scored them low.
        .where(
            Item.first_seen >= start,
            Item.first_seen < end,
            or_(Item.id.in_(matched), Item.priority.is_not(None)),
            Item.id.not_in(dismissed_ids()),
        )
        .options(selectinload(Item.results).selectinload(AIResult.tag))
        .order_by(Item.official.desc(), Item.score.desc())
        .distinct()
    )
    return list(session.scalars(stmt).unique())


def unclassified_count(session: Session, start: datetime, end: datetime) -> int:
    """Items of the week that would be classified (keyword match or platform) but Claude has not seen."""
    return int(
        session.scalar(
            select(func.count(Item.id))
            .join(Source, Source.id == Item.source_id)
            .where(
                Item.first_seen >= start,
                Item.first_seen < end,
                Source.kind != "community",
                Item.id.not_in(select(AIAnalyzed.item_id)),
                Item.id.not_in(dismissed_ids()),
                or_(Item.keyword_matched.is_(True), Source.kind == "platform"),
            )
        )
        or 0
    )


def coverage(session: Session, start: datetime, end: datetime) -> list[dict[str, Any]]:
    """Per enabled source: collection runs of the week, how many failed or warned, new items stored."""
    runs: dict[str, Counter[str]] = {}
    for source_id, status, count in session.execute(
        select(SourceStatus.source_id, SourceStatus.status, func.count())
        .where(SourceStatus.created_at >= start, SourceStatus.created_at < end)
        .group_by(SourceStatus.source_id, SourceStatus.status)
    ):
        runs.setdefault(source_id, Counter())[status] += count
    new = dict(
        session.execute(
            select(Item.source_id, func.count()).where(Item.first_seen >= start, Item.first_seen < end).group_by(Item.source_id)
        ).all()
    )
    out = []
    for source in session.scalars(select(Source).where(Source.enabled.is_(True)).order_by(Source.kind, Source.name)):
        counts = runs.get(source.id, Counter())
        out.append(
            {
                "source": source.id,
                "name": source.name,
                "kind": source.kind,
                "runs": sum(counts.values()),
                "errors": counts.get("error", 0),
                "warnings": counts.get("warn", 0),
                "new_items": int(new.get(source.id, 0)),
            }
        )
    return out


def coverage_lines(rows: list[dict[str, Any]]) -> str:
    """Sources whose data for the week is missing or partial, as Claude reads them."""
    lines = []
    for row in rows:
        if row["runs"] == 0:
            lines.append(f"- {row['name']}: không chạy lần nào trong tuần")
        elif row["errors"]:
            lines.append(f"- {row['name']}: lỗi {row['errors']}/{row['runs']} lần chạy, {row['new_items']} item mới")
        elif row["new_items"] == 0:
            lines.append(f"- {row['name']}: chạy {row['runs']} lần nhưng không có item mới")
    return "\n".join(lines) or "(mọi nguồn đều chạy bình thường)"


def upcoming_deadlines(session: Session, since: date, min_score: float, limit: int = 30) -> list[dict[str, Any]]:
    """Deadlines stored by classification for platform changes, from the start of the week on."""
    rows = session.execute(
        select(Item, AIResult)
        .join(AIResult, AIResult.item_id == Item.id)
        .join(Source, Source.id == Item.source_id)
        .where(
            AIResult.status == "active",
            AIResult.score >= min_score,
            AIResult.deadline.is_not(None),
            AIResult.deadline >= since,
            Source.kind == "platform",
            Item.id.not_in(dismissed_ids()),
        )
        .order_by(AIResult.deadline, Item.id)
        .limit(limit)
    ).all()
    out, seen = [], set()
    for item, result in rows:
        if item.id in seen:
            continue
        seen.add(item.id)
        out.append(
            {
                "item_id": item.id,
                "title": item.title,
                "url": item.url,
                "deadline": result.deadline.isoformat(),
                "impact": result.impact,
                "area": result.area,
                "affects": result.affects,
            }
        )
    return out


def week_digests(session: Session, start: datetime, end: datetime) -> list[Report]:
    return list(
        session.scalars(select(Report).where(Report.kind == "community", Report.created_at >= start, Report.created_at < end).order_by(Report.created_at))
    )


def community_lines(digests: list[Report]) -> str:
    """Topics and open questions of the week's community digests (Discord, Shopify Community)."""
    lines = []
    for digest in digests:
        content = digest.content or {}
        for topic in content.get("topics", []):
            size = f" ({topic['mentions']} tin, {topic['people']} người)" if topic.get("mentions") else ""
            lines.append(f"- {topic.get('title')}{size}: {topic.get('summary')}")
        for question in content.get("open_questions", []):
            lines.append(f"- Câu hỏi chưa ai trả lời: {question.get('text')}")
    return "\n".join(lines) or "(không có)"


def _tag_counts(items: list[Item]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for item in items:
        for result in item.results:
            if result.status == "active":
                counts[result.tag.tag] += 1
    return counts


def item_line(item: Item, names: dict[str, str]) -> str:
    """One item as Claude reads it in reports: id, title, source, score and what classification found."""
    result = max((r for r in item.results if r.status == "active"), key=lambda r: r.score, default=None)
    source = names.get(item.source_id, item.source_id) + (" · CHÍNH THỨC" if item.official else "")
    parts = [f"[{item.id}] {item.title}", f"nguồn: {source}", f"điểm: {item.score:.1f}"]
    if item.priority:
        parts.append(f"ưu tiên: {item.priority}")
    if result is not None:
        parts.append(f"tag: {result.tag.tag}")
        if result.area:
            parts.append(f"mảng: {result.area}")
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

    unclassified = unclassified_count(session, start, end)
    sources = coverage(session, start, end)
    digests = week_digests(session, start, end)

    now_counts, prev_counts = _tag_counts(items), _tag_counts(previous)
    tag_lines = "\n".join(f"- {tag}: {n} / {prev_counts.get(tag, 0)}" for tag, n in now_counts.most_common()) or "(không có)"

    platform = [i for i in items if kinds.get(i.source_id) == "platform"][: limit // 3]
    feed = [i for i in items if kinds.get(i.source_id) != "platform"][: limit - len(platform)]
    prompt = load_prompt(
        "weekly_report",
        interests=config.interests,
        period_start=period_start.strftime("%d/%m/%Y"),
        period_end=period_end.strftime("%d/%m/%Y"),
        total=len(items),
        shown=len(platform) + len(feed),
        unclassified=unclassified,
        coverage=coverage_lines(sources),
        community="\n".join(community_lines(digests).splitlines()[:60]) or "(không có)",
        tag_counts=tag_lines,
        platform="\n".join(item_line(i, names) for i in platform) or "(không có)",
        feed="\n".join(item_line(i, names) for i in feed) or "(không có)",
    )
    data = claude.call_json(
        CallSpec("report", prompt.system, prompt.user, REPORT_SCHEMA, effort=config.ai.get("report_effort", "high"), max_tokens=16000)
    )
    known = {i.id for i in platform + feed}
    for section in ("risks", "opportunities"):
        for point in data.get(section, []):
            point["item_ids"] = [i for i in point.get("item_ids", []) if i in known]
    data["tag_counts"] = [{"tag": tag, "count": n, "previous": prev_counts.get(tag, 0)} for tag, n in now_counts.most_common()]
    data.update(
        items_total=len(items),
        items_shown=len(platform) + len(feed),
        unclassified=unclassified,
        coverage=sources,
        deadlines=upcoming_deadlines(session, period_start, min_score),
        community_digests=len(digests),
    )

    report = session.scalar(
        select(Report).where(Report.kind == "weekly", Report.period_start == period_start, Report.period_end == period_end)
    )
    if report is None:
        report = Report(kind="weekly", period_start=period_start, period_end=period_end)
        session.add(report)
    report.content, report.items_considered, report.model = data, len(items), claude.model
    session.flush()
    return report
