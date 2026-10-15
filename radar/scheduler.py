"""Worker loop: run the pipeline and the weekly report on the cron in sources.yaml."""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from radar.config_loader import load_config
from radar.db import session_scope
from radar.pipeline import run_once, weekly_report
from radar.settings import get_settings

log = logging.getLogger(__name__)


def _run_job() -> None:
    try:
        with session_scope() as session:
            summary = run_once(session)
        log.info("Run finished: %d new, %d seen, errors=%s", summary.items_new, summary.items_seen, summary.errors)
    except Exception:  # noqa: BLE001 - keep the scheduler alive
        log.exception("Run failed")


def _report_job() -> None:
    try:
        with session_scope() as session:
            report = weekly_report(session)
        log.info("Weekly report %s written", report.id)
    except Exception:  # noqa: BLE001
        log.exception("Weekly report failed")


def run_scheduler() -> None:
    with session_scope() as session:
        schedule = load_config(session).schedule
    tz = get_settings().timezone
    scheduler = BlockingScheduler(timezone=tz)
    # First run right away instead of waiting for the next cron slot (up to 2 hours).
    scheduler.add_job(
        _run_job,
        CronTrigger.from_crontab(schedule.get("collect", "7 */2 * * *"), timezone=tz),
        id="run",
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(ZoneInfo(tz)),
    )
    scheduler.add_job(_report_job, CronTrigger.from_crontab(schedule.get("weekly_report", "52 7 * * 1"), timezone=tz), id="report", max_instances=1, coalesce=True)
    log.info("Scheduler started (%s): run=%s report=%s", tz, schedule.get("collect"), schedule.get("weekly_report"))
    scheduler.start()
