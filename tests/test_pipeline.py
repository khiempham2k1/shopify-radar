from datetime import timedelta

import pytest
from sqlalchemy import func, select

from radar.ai.classifier import PENDING_BATCH_KEY, classify, pending_items
from radar.ai.client import AIRefusal, CallSpec, ClaudeClient
from radar.ai.insights import build_report, last_full_week
from radar.ai.tags import active_tags, sync_tags
from radar.collectors.base import CollectedItem, CollectResult
from radar.ingest import collect_all, store_items
from radar.models import (
    AIAnalyzed,
    AIResult,
    AITag,
    AIUsage,
    Item,
    ItemMetricsHistory,
    ItemStatus,
    ItemTranscript,
    Setting,
    SourceStatus,
    utcnow,
)
from radar.pipeline import make_claude, run_once
from radar.scoring import compute_score, engagement, rescore
from radar.transcribe import media
from radar.transcribe.queue import process_videos
from tests.conftest import FakeAnthropic, make_message


def add_items(session, config, source_id, titles, **extra):
    items = [CollectedItem(url=f"https://example.com/{source_id}/{i}", title=t, **extra) for i, t in enumerate(titles)]
    return store_items(session, source_id, items, config.keywords)


# ── ingest ──────────────────────────────────────────────────────────


def test_store_items_dedupes_and_tracks_metrics(session, config):
    first = store_items(
        session,
        "reddit",
        [CollectedItem(url="https://r/1", title="Looking for a Shopify theme with quick add", metrics={"upvotes": 3})],
        config.keywords,
    )
    assert (first.new, first.seen) == (1, 0)
    again = store_items(session, "reddit", [CollectedItem(url="https://r/1", title="same", metrics={"upvotes": 9})], config.keywords)
    assert (again.new, again.seen) == (0, 1)
    item = session.scalar(select(Item))
    assert item.seen_count == 2 and item.metrics["upvotes"] == 9
    assert item.keyword_matched and "Nhu cầu merchant" in item.keyword_groups
    assert session.scalar(select(func.count()).select_from(ItemMetricsHistory)) == 2


def test_global_filter_drops_new_items(session, config):
    stats = add_items(session, config, "reddit", ["We are hiring Shopify theme devs"])
    assert stats.blocked == 1 and session.scalar(select(func.count()).select_from(Item)) == 0


def test_collect_all_records_source_status(session, config, monkeypatch):
    class Fake:
        def __init__(self, source, http=None):
            self.source = source

        def collect(self):
            if self.source["id"] == "reddit":
                return CollectResult(items=[CollectedItem(url="https://r/2", title="Best Shopify theme for fashion")], status="warn", backend="exa", message="rdt-cli: cookie")
            return CollectResult(items=[], status="error", backend="", message="offline")

    monkeypatch.setattr("radar.ingest.make_collector", lambda source, http: Fake(source))
    run = collect_all(session, config, only=["reddit", "hackernews"])
    statuses = {s.source_id: s for s in session.scalars(select(SourceStatus))}
    assert run.items_new == 1
    assert statuses["reddit"].status == "warn" and statuses["reddit"].backend == "exa"
    assert "1 mới" in statuses["reddit"].message
    assert statuses["hackernews"].status == "error"


# ── Claude client ───────────────────────────────────────────────────


def test_call_json_records_usage_and_uses_fallbacks(session, fake_anthropic):
    claude = ClaudeClient(session, "claude-opus-5-5", pricing={"claude-opus-5-5": {"input": 4, "output": 20, "cache_read": 0.2}}, client=fake_anthropic)
    data = claude.call_json(CallSpec("tags", "sys", "interests", {"type": "object", "properties": {"tags": {}}}))
    assert data["tags"]
    call = fake_anthropic.messages.calls[0]
    assert call["fallbacks"] == "default" and call["betas"] == ["server-side-fallback-2026-07-01"]
    assert call["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert call["output_config"]["effort"] == "low"
    usage = session.scalar(select(AIUsage))
    assert usage.task == "tags"
    assert usage.cost_usd == pytest.approx((1000 * 4 + 100 * 20 + 500 * 0.2) / 1_000_000)


def test_refusal_is_an_error(session):
    claude = ClaudeClient(session, "claude-opus-5-5", client=FakeAnthropic(lambda kw: make_message("", stop_reason="refusal")), fallbacks=False)
    with pytest.raises(AIRefusal):
        claude.call_json(CallSpec("classify", "s", "u", {"type": "object", "properties": {"results": {}}}))


# ── tags & classification ───────────────────────────────────────────


def test_tags_created_once_then_updated_when_interests_change(session, config, fake_anthropic):
    claude = make_claude(session, config, fake_anthropic)
    first = sync_tags(session, config, claude)
    assert first.changed and [t.tag for t in first.tags] == ["Thay đổi nền tảng", "Nhu cầu merchant"]
    assert not sync_tags(session, config, claude).changed

    config.interests += "\n9. Chủ đề mới"
    update = sync_tags(session, config, claude)
    assert update.changed and not update.full_reclassify
    names = [t.tag for t in active_tags(session)]
    assert names == ["Chủ đề mới"]  # keep_ids was empty in the fake reply
    assert session.scalar(select(func.count()).select_from(AITag).where(AITag.status == "deprecated")) == 2


def test_classify_matches_and_never_resends(session, config, fake_anthropic):
    add_items(session, config, "reddit", ["Looking for a Shopify theme with bundles", "Random cat picture"])
    add_items(session, config, "shopify-dev-changelog", ["Admin API 2027-01 removes fields"], media_type="change")
    session.commit()
    claude = make_claude(session, config, fake_anthropic)
    stats = classify(session, config, claude)
    # The cat post failed the keyword filter, so only 2 items went to Claude.
    assert stats.sent == 2 and stats.matched == 2
    result = session.scalar(select(AIResult).join(Item).where(Item.source_id == "shopify-dev-changelog"))
    assert result.impact == "high" and str(result.deadline) == "2027-01-01"
    assert session.scalar(select(Item).where(Item.source_id == "reddit", Item.title.like("Looking%"))).summary.startswith("Tóm tắt")
    calls = len(fake_anthropic.messages.calls)
    assert classify(session, config, claude).sent == 0
    assert len(fake_anthropic.messages.calls) == calls  # tags unchanged, nothing pending


def test_failed_batch_keeps_keyword_fallback(session, config):
    add_items(session, config, "reddit", ["Looking for a Shopify theme"])
    session.commit()

    def responder(kw):
        if "results" in kw["output_config"]["format"]["schema"]["properties"]:
            return make_message("not json")
        from tests.conftest import default_responder

        return default_responder(kw)

    stats = classify(session, config, make_claude(session, config, FakeAnthropic(responder)))
    assert stats.failed_batches == 1 and stats.errors
    assert session.scalar(select(func.count()).select_from(AIAnalyzed)) == 0  # retried next run
    assert len(pending_items(session, config)) == 1


def test_dismissed_items_are_not_sent(session, config, fake_anthropic):
    add_items(session, config, "reddit", ["Looking for a Shopify theme"])
    item = session.scalar(select(Item))
    session.add(ItemStatus(item_id=item.id, status="dismissed"))
    session.commit()
    assert pending_items(session, config) == []


def test_batch_api_submits_then_collects(session, config, fake_anthropic):
    config.ai["use_batch_api"] = True
    add_items(session, config, "reddit", ["Looking for a Shopify theme", "Best Shopify theme for shoes"])
    session.commit()
    claude = make_claude(session, config, fake_anthropic)
    fake_anthropic.messages.batches.ended = False
    first = classify(session, config, claude)
    assert first.pending_batch == "batch_1" and session.get(Setting, PENDING_BATCH_KEY)
    assert classify(session, config, claude).pending_batch == "batch_1"  # still running: no resubmit
    fake_anthropic.messages.batches.ended = True
    done = classify(session, config, claude)
    assert done.matched == 2 and session.get(Setting, PENDING_BATCH_KEY) is None
    assert session.scalar(select(func.count()).select_from(AIUsage).where(AIUsage.batch.is_(True))) == 1


# ── videos ──────────────────────────────────────────────────────────

VTT = """WEBVTT
Kind: captions

00:00:00.000 --> 00:00:02.000
<c>hello</c><00:00:01.000><c> everyone</c>

00:00:02.000 --> 00:00:04.000
hello everyone
today we test themes

00:00:04.000 --> 00:00:06.000
today we test themes
with quick add
"""


def test_parse_vtt_removes_rolling_duplicates():
    segments = media.parse_vtt(VTT)
    assert [s["text"] for s in segments] == ["hello everyone", "today we test themes", "with quick add"]
    assert segments[1]["start"] == 2.0


def test_video_queue_uses_subtitles_then_groq_and_reclassifies(session, config, fake_anthropic, tmp_path):
    add_items(session, config, "youtube", ["Shopify theme review A", "Shopify theme review B"], media_type="video", extra={"duration": 600})
    session.commit()
    claude = make_claude(session, config, fake_anthropic)
    classify(session, config, claude)

    def subtitles(url, work_dir, langs):
        if url.endswith("/0"):
            return media.Transcript(via="subtitle", segments=[{"start": 0, "end": 5, "text": "hi"}], duration_s=600)
        return None

    def groq(url, work_dir, key, model, terms, chunk_seconds, max_seconds):
        assert "Liquid" in terms
        return media.Transcript(via="groq", segments=[{"start": 0, "end": 5, "text": "yo"}], audio_seconds=600, model=model)

    stats = process_videos(session, config, claude, fetch_subtitles=subtitles, transcribe_groq=groq, get_duration=lambda u: 600)
    assert (stats.done, stats.via_subtitle, stats.via_groq) == (2, 1, 1)
    rows = list(session.scalars(select(ItemTranscript)))
    assert all(r.status == "done" and r.points for r in rows)
    item = session.scalar(select(Item).where(Item.url.endswith("/0")))
    assert item.summary == "Video nói về tốc độ theme." and "01:05 Ý chính một" in item.content
    assert session.get(AIAnalyzed, item.id) is None  # back in the classifier queue
    assert item.id in {i.id for i in pending_items(session, config)}
    assert process_videos(session, config, claude, fetch_subtitles=subtitles, transcribe_groq=groq, get_duration=lambda u: 600).done == 0


def test_long_videos_are_skipped(session, config, fake_anthropic):
    add_items(session, config, "youtube", ["Shopify theme review long"], media_type="video", extra={"duration": 4 * 3600})
    session.commit()
    claude = make_claude(session, config, fake_anthropic)
    classify(session, config, claude)
    stats = process_videos(session, config, claude, fetch_subtitles=lambda *a: None, transcribe_groq=lambda *a, **k: None, get_duration=lambda u: 0)
    assert stats.skipped == 1
    assert session.scalar(select(ItemTranscript)).status == "skipped"


def test_groq_offsets_chunks(monkeypatch, tmp_path):
    chunks = [tmp_path / "chunk_000.m4a", tmp_path / "chunk_001.m4a"]
    for c in chunks:
        c.write_bytes(b"x")
    monkeypatch.setattr(media, "download_audio", lambda url, work_dir: tmp_path / "source.webm")
    monkeypatch.setattr(media, "compress_and_chunk", lambda *a: chunks)
    replies = iter([
        {"language": "english", "duration": 600.0, "segments": [{"start": 1, "end": 2, "text": " first "}]},
        {"duration": 120.0, "segments": [{"start": 3, "end": 4, "text": "second"}]},
    ])
    monkeypatch.setattr(media, "groq_transcribe_chunk", lambda *a, **k: next(replies))
    t = media.transcribe_with_groq("https://youtube.com/watch?v=1", tmp_path, "key", "whisper-large-v3-turbo", "terms")
    assert [s["start"] for s in t.segments] == [1, 603]
    assert t.audio_seconds == 720 and t.language == "english" and t.text == "first second"


def test_groq_requires_key(tmp_path):
    with pytest.raises(media.TranscriptError, match="GROQ_API_KEY"):
        media.transcribe_with_groq("u", tmp_path, "", "m", "t")


# ── scoring ─────────────────────────────────────────────────────────


def test_score_components():
    assert engagement({}) == 0
    assert engagement({"upvotes": 1000}) == 1.0
    weights = {"relevance": 0.5, "engagement": 0.2, "cross_source": 0.15, "recency": 0.15}
    assert compute_score(1, 1, 1, 1, weights) == 10.0
    assert compute_score(0, 0, 0, 0, weights) == 0.0


def test_rescore_rewards_relevance_and_cross_source(session, config, fake_anthropic):
    add_items(session, config, "reddit", ["Theme editor slow with many sections in Shopify"], metrics={"upvotes": 100})
    add_items(session, config, "twitter", ["Theme editor slow with many sections"])
    add_items(session, config, "hackernews", ["Unrelated Shopify theme store news today"])
    session.commit()
    classify(session, config, make_claude(session, config, fake_anthropic))
    rescore(session, config)
    reddit = session.scalar(select(Item).where(Item.source_id == "reddit"))
    assert 0 < reddit.score <= 10
    assert reddit.score > session.scalar(select(Item).where(Item.source_id == "hackernews")).score - 1


# ── weekly report & full run ────────────────────────────────────────


def test_last_full_week():
    from datetime import date

    assert last_full_week(date(2026, 10, 14)) == (date(2026, 10, 5), date(2026, 10, 11))


def test_weekly_report_filters_unknown_ids(session, config, fake_anthropic):

    add_items(session, config, "reddit", ["Looking for a Shopify theme"])
    item = session.scalar(select(Item))
    item.first_seen = utcnow() - timedelta(days=9)
    session.commit()
    claude = make_claude(session, config, fake_anthropic)
    classify(session, config, claude)
    today = (item.first_seen + timedelta(days=7)).date()
    report = build_report(session, config, claude, today=today)
    assert report.content["risks"][0]["item_ids"] in ([], [item.id])
    assert 999 not in report.content["risks"][0]["item_ids"]
    assert report.items_considered >= 1 and report.content["tag_counts"]


def test_run_once_end_to_end(session, monkeypatch, fake_anthropic):
    class Fake:
        def __init__(self, source, http=None):
            self.source = source

        def collect(self):
            if self.source["id"] == "reddit":
                return CollectResult(items=[CollectedItem(url="https://r/9", title="Looking for a Shopify theme with mega menu", metrics={"upvotes": 40})], status="ok", backend="rdt-cli")
            return CollectResult(items=[], status="ok", backend="x")

    monkeypatch.setattr("radar.ingest.make_collector", lambda source, http: Fake(source))
    summary = run_once(session, claude_client=fake_anthropic)
    assert summary.items_new == 1 and summary.classify.matched == 1 and not summary.errors
    assert session.scalar(select(Item)).score > 0
