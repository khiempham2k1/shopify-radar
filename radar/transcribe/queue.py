"""Video queue: pick relevant YouTube items, get their words, summarize with Claude.

The summary replaces the item's content and the item is sent back to the
classifier, so its tag and score come from what the video says rather than
from its title.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from radar.ai.client import AIError, CallSpec, ClaudeClient
from radar.config_loader import RadarConfig, load_prompt
from radar.models import AIAnalyzed, AIResult, Item, ItemTranscript
from radar.settings import get_settings
from radar.transcribe import media

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 3

SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "points": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"t": {"type": "integer"}, "text": {"type": "string"}},
                "required": ["t", "text"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["summary", "points"],
    "additionalProperties": False,
}


@dataclass
class VideoStats:
    done: int = 0
    via_subtitle: int = 0
    via_groq: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


def candidates(session: Session, config: RadarConfig) -> list[Item]:
    min_score = float(config.video.get("min_score", 0.5))
    limit = int(config.video.get("max_per_run", 10))
    best_score = (
        select(func.max(AIResult.score))
        .where(AIResult.item_id == Item.id, AIResult.status == "active")
        .correlate(Item)
        .scalar_subquery()
    )
    analyzed = select(AIAnalyzed.item_id).where(AIAnalyzed.item_id == Item.id).correlate(Item).exists()
    retry_ok = or_(
        ItemTranscript.item_id.is_(None),
        ItemTranscript.status == "pending",
        (ItemTranscript.status == "error") & (ItemTranscript.attempts < MAX_ATTEMPTS),
    )
    stmt = (
        select(Item)
        .outerjoin(ItemTranscript, ItemTranscript.item_id == Item.id)
        .where(
            Item.media_type == "video",
            retry_ok,
            or_(best_score >= min_score, (~analyzed) & Item.keyword_matched.is_(True), Item.priority.is_not(None)),
        )
        # Priority-topic videos first, then the newest.
        .order_by(Item.priority.is_(None), Item.first_seen.desc())
        .limit(limit)
    )
    return list(session.scalars(stmt))


def transcript_for_prompt(segments: list[dict], max_chars: int = 60000) -> str:
    lines, total = [], 0
    for seg in segments:
        line = f"[{int(seg['start'])}] {seg['text']}"
        total += len(line) + 1
        if total > max_chars:
            break
        lines.append(line)
    return "\n".join(lines)


def summarize(item: Item, transcript: media.Transcript, config: RadarConfig, claude: ClaudeClient) -> dict:
    prompt = load_prompt(
        "summarize_video",
        title=item.title,
        author=item.author or "",
        transcript=transcript_for_prompt(transcript.segments),
    )
    return claude.call_json(
        CallSpec("summarize", prompt.system, prompt.user, SUMMARY_SCHEMA, effort=config.ai.get("summarize_effort", "medium"), max_tokens=8000)
    )


def format_ts(seconds: int) -> str:
    seconds = max(0, int(seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def process_videos(
    session: Session,
    config: RadarConfig,
    claude: ClaudeClient,
    fetch_subtitles: Callable[..., media.Transcript | None] = media.fetch_subtitles,
    transcribe_groq: Callable[..., media.Transcript] = media.transcribe_with_groq,
    get_duration: Callable[[str], int] = media.video_duration,
) -> VideoStats:
    stats = VideoStats()
    settings = get_settings()
    max_seconds = int(config.video.get("max_minutes", 60)) * 60
    langs = list(config.video.get("subtitle_langs", ["en", "vi"]))
    for item in candidates(session, config):
        row = item.transcript or ItemTranscript(item_id=item.id)
        if item.transcript is None:
            session.add(row)
        row.status, row.attempts = "processing", (row.attempts or 0) + 1
        session.commit()
        work_dir = Path(settings.work_dir) / f"video-{item.id}"
        try:
            duration = int(item.extra.get("duration") or 0) or get_duration(item.url)
            if duration > max_seconds:
                row.status, row.error, row.duration_s = "skipped", f"Video dài {duration // 60} phút, vượt giới hạn", duration
                stats.skipped += 1
                session.commit()
                continue
            try:
                transcript = fetch_subtitles(item.url, work_dir, langs)
            except media.SubtitleRateLimited:
                if not settings.groq_api_key:
                    raise
                transcript = None  # captions are rate limited: listen to the audio instead
            if transcript is None:
                transcript = transcribe_groq(
                    item.url,
                    work_dir,
                    settings.groq_api_key,
                    config.video.get("groq_model", "whisper-large-v3-turbo"),
                    config.terms,
                    chunk_seconds=int(config.video.get("chunk_seconds", 600)),
                    max_seconds=max_seconds,
                )
            if not transcript.segments:
                raise media.TranscriptError("Transcript rỗng")
            summary = summarize(item, transcript, config, claude)
        except (media.TranscriptError, AIError) as exc:
            row.status, row.error = "error", str(exc)[:2000]
            stats.failed += 1
            stats.errors.append(f"{item.url}: {exc}")
            session.commit()
            continue
        finally:
            media.cleanup(work_dir)

        points = [{"t": int(p.get("t", 0)), "text": p.get("text", "").strip()} for p in summary.get("points", []) if p.get("text")]
        row.status, row.error = "done", ""
        row.via, row.language, row.model = transcript.via, transcript.language, transcript.model
        row.text, row.segments, row.points = transcript.text, transcript.segments, points
        row.duration_s = transcript.duration_s or int(item.extra.get("duration") or 0)
        row.audio_seconds = transcript.audio_seconds
        item.summary = summary.get("summary", "").strip()
        item.content = item.summary + "\n" + "\n".join(f"{format_ts(p['t'])} {p['text']}" for p in points)
        # Classify again from what the video says.
        session.execute(delete(AIAnalyzed).where(AIAnalyzed.item_id == item.id))
        stats.done += 1
        stats.via_subtitle += int(transcript.via == "subtitle")
        stats.via_groq += int(transcript.via == "groq")
        session.commit()
    return stats
