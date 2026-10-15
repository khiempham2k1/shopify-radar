"""Command line: `radar <command>`.

    radar migrate            apply database migrations (Alembic)
    radar run [--source ID]  one full run: collect, classify, videos, score
    radar collect            collect only
    radar classify [--reset] classify pending items only (--reset: start over with new tags)
    radar videos             process the video queue only
    radar score              recompute scores
    radar status             which database is used and how many items it holds
    radar report             write last week's report now
    radar digest             sum up the last 24 h of community talk now (Discord, Shopify Community)
    radar doctor [--network] check tools, logins and keys
    radar scheduler          run forever on the cron in sources.yaml
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict, is_dataclass

from radar.db import session_scope


def _print(obj) -> None:
    if is_dataclass(obj):
        obj = asdict(obj)
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def cmd_migrate(_: argparse.Namespace) -> None:
    from radar.db import describe_url, has_schema, migrate

    migrate()
    print(f"DB: {describe_url()} · {'đã có bảng' if has_schema() else 'CHƯA có bảng'}")


def cmd_run(args: argparse.Namespace) -> None:
    from radar.pipeline import run_once

    with session_scope() as session:
        _print(run_once(session, only=args.source or None))


def cmd_collect(args: argparse.Namespace) -> None:
    from radar.config_loader import load_config
    from radar.ingest import collect_all

    with session_scope() as session:
        run = collect_all(session, load_config(session), only=args.source or None)
        _print({"crawl_run": run.id, "new": run.items_new, "seen": run.items_seen})


def cmd_classify(args: argparse.Namespace) -> None:
    from radar.ai.classifier import classify
    from radar.ai.tags import reset_classification
    from radar.config_loader import load_config
    from radar.pipeline import make_claude
    from radar.scoring import rescore

    with session_scope() as session:
        config = load_config(session)
        if args.reset:
            print(f"Đã bỏ {reset_classification(session)} kết quả phân loại cũ, phân loại lại theo interests.txt hiện tại…")
            session.commit()
        stats = classify(session, config, make_claude(session, config))
        rescore(session, config)
        _print(stats)


def cmd_videos(_: argparse.Namespace) -> None:
    from radar.config_loader import load_config
    from radar.pipeline import make_claude
    from radar.transcribe.queue import process_videos

    with session_scope() as session:
        config = load_config(session)
        _print(process_videos(session, config, make_claude(session, config)))


def cmd_status(_: argparse.Namespace) -> None:
    from radar.db import db_status

    _print(db_status())


def cmd_score(_: argparse.Namespace) -> None:
    from radar.config_loader import load_config
    from radar.scoring import rescore

    with session_scope() as session:
        _print({"scored": rescore(session, load_config(session))})


def cmd_report(_: argparse.Namespace) -> None:
    from radar.pipeline import weekly_report

    with session_scope() as session:
        report = weekly_report(session)
        _print({"report": report.id, "period": [report.period_start, report.period_end], "items": report.items_considered})


def cmd_digest(_: argparse.Namespace) -> None:
    from radar.ai import community
    from radar.config_loader import load_config
    from radar.pipeline import make_claude

    with session_scope() as session:
        config = load_config(session)
        _print(community.refresh(session, config, make_claude(session, config), force=True))


def cmd_doctor(args: argparse.Namespace) -> None:
    from sqlalchemy.exc import SQLAlchemyError

    from radar.config_loader import load_config
    from radar.doctor import run_doctor

    try:
        with session_scope() as session:
            config = load_config(session)
    except SQLAlchemyError:
        print("⚠️  Chưa kết nối được DB hoặc chưa migrate: dùng cấu hình trong config/")
        config = load_config(None)
    checks = run_doctor(config, network=args.network)
    icons = {"ok": "✅", "warn": "⚠️ ", "error": "❌", "off": "⏸ "}
    for check in checks:
        print(f"{icons.get(check.status, '?')} {check.name}: {check.message}")
    if any(c.status == "error" for c in checks):
        sys.exit(1)


def cmd_scheduler(_: argparse.Namespace) -> None:
    from radar.scheduler import run_scheduler

    run_scheduler()


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(prog="radar", description="Shopify Radar worker")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate").set_defaults(func=cmd_migrate)
    for name, func in (("run", cmd_run), ("collect", cmd_collect)):
        p = sub.add_parser(name)
        p.add_argument("--source", action="append", help="chỉ chạy nguồn này (lặp lại được)")
        p.set_defaults(func=func)
    classify_p = sub.add_parser("classify")
    classify_p.add_argument("--reset", action="store_true", help="bỏ tag và kết quả cũ, phân loại lại item gần đây theo interests.txt")
    classify_p.set_defaults(func=cmd_classify)
    sub.add_parser("videos").set_defaults(func=cmd_videos)
    sub.add_parser("score").set_defaults(func=cmd_score)
    sub.add_parser("status").set_defaults(func=cmd_status)
    sub.add_parser("report").set_defaults(func=cmd_report)
    sub.add_parser("digest").set_defaults(func=cmd_digest)
    doctor = sub.add_parser("doctor")
    doctor.add_argument("--network", action="store_true", help="kiểm tra cả kết nối tới Jina, Exa, Groq")
    doctor.set_defaults(func=cmd_doctor)
    sub.add_parser("scheduler").set_defaults(func=cmd_scheduler)
    args = parser.parse_args(argv)
    if args.command not in ("migrate", "doctor"):
        from radar.db import ensure_schema

        ensure_schema()
    args.func(args)


if __name__ == "__main__":
    main()
