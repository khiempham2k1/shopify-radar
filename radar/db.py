"""Database engine and session helpers."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from radar.settings import get_settings


@lru_cache(maxsize=4)
def get_engine(url: str | None = None) -> Engine:
    url = url or get_settings().database_url
    if url.startswith("sqlite:///"):
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
        return create_engine(url, connect_args={"check_same_thread": False})
    return create_engine(url, pool_pre_ping=True)


def session_factory(url: str | None = None) -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(url), expire_on_commit=False)


@contextmanager
def session_scope(url: str | None = None) -> Iterator[Session]:
    session = session_factory(url)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db(url: str | None = None) -> None:
    """Create tables directly (tests and local SQLite). Production uses Alembic."""
    from radar.models import Base

    Base.metadata.create_all(get_engine(url))


def describe_url(url: str | None = None) -> str:
    """Database URL with the password hidden, for logs."""
    from sqlalchemy.engine import make_url

    return make_url(url or get_settings().database_url).render_as_string(hide_password=True)


def has_schema(url: str | None = None) -> bool:
    from sqlalchemy import inspect

    return inspect(get_engine(url)).has_table("settings")


def migrate() -> None:
    """Apply Alembic migrations to DATABASE_URL (same as `radar migrate`)."""
    from alembic import command
    from alembic.config import Config

    from radar.settings import ROOT

    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    command.upgrade(cfg, "head")


def ensure_schema(url: str | None = None) -> None:
    """Make sure the tables exist before a command touches them.

    Runs the Alembic migrations when the schema is missing. If the tables are
    still absent afterwards (for example a SQLite file whose alembic_version
    says "done" but whose tables were removed), create them directly and
    record the head revision so later migrations apply normally.
    """
    import logging

    log = logging.getLogger(__name__)
    if has_schema(url):
        return
    log.warning("DB %s chưa có bảng, đang chạy migration…", describe_url(url))
    migrate()
    if has_schema(url):
        return
    from alembic import command
    from alembic.config import Config

    from radar.models import Base
    from radar.settings import ROOT

    log.warning("Migration không tạo được bảng, tạo trực tiếp từ models")
    Base.metadata.create_all(get_engine(url))
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    command.stamp(cfg, "head")
