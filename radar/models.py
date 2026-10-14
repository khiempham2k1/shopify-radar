"""SQLAlchemy models. Table layout follows docs/PLAN.md, Giai đoạn 1."""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

JSONType = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    type: Mapped[str] = mapped_column(String(40))
    # platform = Shopify changes; social = Reddit/X/YouTube/Community; web = search, HN
    kind: Mapped[str] = mapped_column(String(20))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    config: Mapped[dict] = mapped_column(JSONType, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Item(Base):
    __tablename__ = "items"
    __table_args__ = (
        UniqueConstraint("source_id", "url", name="uq_items_source_url"),
        Index("ix_items_first_seen", "first_seen"),
        Index("ix_items_last_seen", "last_seen"),
        Index("ix_items_score", "score"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), index=True)
    external_id: Mapped[str] = mapped_column(String(200), default="")
    url: Mapped[str] = mapped_column(String(1000))
    title: Mapped[str] = mapped_column(Text)
    # Raw text from the source (post body, changelog entry). For videos this is
    # replaced by the transcript summary once the video has been listened to.
    content: Mapped[str] = mapped_column(Text, default="")
    # Short Vietnamese summary written by Claude during classification.
    summary: Mapped[str] = mapped_column(Text, default="")
    author: Mapped[str] = mapped_column(String(200), default="")
    media_type: Mapped[str] = mapped_column(String(20), default="post")  # post|video|change|article|release
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    seen_count: Mapped[int] = mapped_column(Integer, default=1)
    metrics: Mapped[dict] = mapped_column(JSONType, default=dict)
    extra: Mapped[dict] = mapped_column(JSONType, default=dict)
    keyword_groups: Mapped[list] = mapped_column(JSONType, default=list)
    keyword_matched: Mapped[bool] = mapped_column(Boolean, default=False)
    score: Mapped[float] = mapped_column(Float, default=0.0)

    source: Mapped[Source] = relationship()
    results: Mapped[list[AIResult]] = relationship(back_populates="item", cascade="all, delete-orphan")
    status: Mapped[ItemStatus | None] = relationship(back_populates="item", uselist=False, cascade="all, delete-orphan")
    transcript: Mapped[ItemTranscript | None] = relationship(back_populates="item", uselist=False, cascade="all, delete-orphan")


class ItemMetricsHistory(Base):
    __tablename__ = "item_metrics_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), index=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    metrics: Mapped[dict] = mapped_column(JSONType, default=dict)


class CrawlRun(Base):
    __tablename__ = "crawl_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    items_new: Mapped[int] = mapped_column(Integer, default=0)
    items_seen: Mapped[int] = mapped_column(Integer, default=0)


class SourceStatus(Base):
    __tablename__ = "source_status"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    crawl_run_id: Mapped[int | None] = mapped_column(ForeignKey("crawl_runs.id", ondelete="CASCADE"), nullable=True, index=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), index=True)
    status: Mapped[str] = mapped_column(String(10))  # ok|warn|error
    backend: Mapped[str] = mapped_column(String(80), default="")
    message: Mapped[str] = mapped_column(Text, default="")
    items_count: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class AITag(Base):
    __tablename__ = "ai_tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tag: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    priority: Mapped[int] = mapped_column(Integer, default=9999)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)  # active|deprecated
    version: Mapped[int] = mapped_column(Integer, default=1)
    prompt_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    deprecated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AIResult(Base):
    __tablename__ = "ai_results"
    __table_args__ = (UniqueConstraint("item_id", "tag_id", name="uq_ai_results_item_tag"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), index=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("ai_tags.id"), index=True)
    score: Mapped[float] = mapped_column(Float, default=0.0)  # relevance 0..1
    sentiment: Mapped[str] = mapped_column(String(10), default="neu")  # neg|neu|pos
    impact: Mapped[str | None] = mapped_column(String(10), nullable=True)  # high|med|low
    deadline: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    item: Mapped[Item] = relationship(back_populates="results")
    tag: Mapped[AITag] = relationship()


class AIAnalyzed(Base):
    """Every item sent to the classifier, matched or not, so it is never sent twice."""

    __tablename__ = "ai_analyzed"

    item_id: Mapped[int] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), primary_key=True)
    prompt_hash: Mapped[str] = mapped_column(String(64))
    method: Mapped[str] = mapped_column(String(10), default="ai")  # ai|keyword
    matched: Mapped[bool] = mapped_column(Boolean, default=False)
    analyzed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ItemStatus(Base):
    __tablename__ = "item_status"

    item_id: Mapped[int] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), primary_key=True)
    status: Mapped[str] = mapped_column(String(20), default="new")  # new|doing|done|dismissed
    owner: Mapped[str] = mapped_column(String(200), default="")
    updated_by: Mapped[str] = mapped_column(String(200), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    item: Mapped[Item] = relationship(back_populates="status")


class ItemTranscript(Base):
    __tablename__ = "item_transcripts"

    item_id: Mapped[int] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), primary_key=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)  # pending|processing|done|error|skipped
    via: Mapped[str] = mapped_column(String(20), default="")  # subtitle|groq
    language: Mapped[str] = mapped_column(String(20), default="")
    text: Mapped[str] = mapped_column(Text, default="")
    segments: Mapped[list] = mapped_column(JSONType, default=list)  # [{start, end, text}]
    points: Mapped[list] = mapped_column(JSONType, default=list)  # [{t, text}]
    duration_s: Mapped[int] = mapped_column(Integer, default=0)
    audio_seconds: Mapped[int] = mapped_column(Integer, default=0)  # seconds sent to Groq
    model: Mapped[str] = mapped_column(String(80), default="")
    error: Mapped[str] = mapped_column(Text, default="")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    item: Mapped[Item] = relationship(back_populates="transcript")


class AIUsage(Base):
    __tablename__ = "ai_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    task: Mapped[str] = mapped_column(String(40))  # tags|classify|summarize|report
    model: Mapped[str] = mapped_column(String(80))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, default=0)
    batch: Mapped[bool] = mapped_column(Boolean, default=False)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    request_id: Mapped[str] = mapped_column(String(120), default="")


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), default="weekly")
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    content: Mapped[dict] = mapped_column(JSONType, default=dict)
    items_considered: Mapped[int] = mapped_column(Integer, default=0)
    model: Mapped[str] = mapped_column(String(80), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Setting(Base):
    """Phase 2: team-edited config (keywords, interests, sources) stored in the DB.

    When a key is present here it overrides the file of the same name in config/.
    """

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_by: Mapped[str] = mapped_column(String(200), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
