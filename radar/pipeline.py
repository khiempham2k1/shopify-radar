"""One radar run: collect → classify → listen to videos → classify again → score."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from radar.ai.classifier import ClassifyStats, classify
from radar.ai.client import ClaudeClient
from radar.ai.insights import build_report
from radar.config_loader import RadarConfig, load_config
from radar.doctor import login_checks, save_login_status
from radar.ingest import collect_all, prune_old, prune_stale
from radar.models import Report
from radar.scoring import rescore
from radar.transcribe.queue import VideoStats, process_videos

log = logging.getLogger(__name__)


@dataclass
class RunSummary:
    items_new: int = 0
    items_seen: int = 0
    classify: ClassifyStats | None = None
    videos: VideoStats | None = None
    reclassify: ClassifyStats | None = None
    scored: int = 0
    pruned: int = 0
    stale_removed: int = 0
    errors: list[str] = field(default_factory=list)


def make_claude(session: Session, config: RadarConfig, client: Any | None = None) -> ClaudeClient:
    return ClaudeClient(
        session,
        model=config.model,
        pricing=config.ai.get("pricing") or {},
        fallbacks=bool(config.ai.get("fallbacks", True)),
        client=client,
    )


def run_once(session: Session, only: list[str] | None = None, claude_client: Any | None = None, skip_collect: bool = False) -> RunSummary:
    config = load_config(session)
    summary = RunSummary()
    if not skip_collect:
        save_login_status(session, login_checks(config))
        run = collect_all(session, config, only=only)
        summary.items_new, summary.items_seen = run.items_new, run.items_seen
    # Drop stale items before they cost a Claude call or a Groq transcription.
    summary.stale_removed = prune_stale(session, config)
    session.commit()

    claude = make_claude(session, config, claude_client)
    try:
        summary.classify = classify(session, config, claude)
        summary.videos = process_videos(session, config, claude)
        if summary.videos.done:
            summary.reclassify = classify(session, config, claude)
    except Exception as exc:  # noqa: BLE001 - scoring must still run on what we have
        log.exception("AI step failed")
        summary.errors.append(f"AI: {exc}")
        session.rollback()

    summary.scored = rescore(session, config)
    summary.pruned = prune_old(session, int(config.schedule.get("retention_days", 0)))
    session.commit()
    return summary


def weekly_report(session: Session, claude_client: Any | None = None) -> Report:
    config = load_config(session)
    report = build_report(session, config, make_claude(session, config, claude_client))
    session.commit()
    return report
