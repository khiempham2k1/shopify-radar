from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from radar.ai.client import ClaudeClient
from radar.collectors.base import CollectedItem
from radar.ingest import store_items
from radar.models import Item, ItemTranscript, Setting
from radar.transcribe import media
from radar.transcribe.groq_pool import STATE_KEY, GroqKeyPool, GroqKeysExhausted, rest_from_response
from radar.transcribe.queue import process_videos


class Clock:
    def __init__(self):
        self.t = datetime(2026, 10, 15, 3, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.t


def test_settings_merge_key_list_and_single_key(monkeypatch):
    from radar.settings import get_settings

    monkeypatch.setenv("GROQ_API_KEYS", "gsk_a, gsk_b\ngsk_c,gsk_a")
    monkeypatch.setenv("GROQ_API_KEY", "gsk_d")
    settings = get_settings()
    assert settings.groq_api_keys == ("gsk_a", "gsk_b", "gsk_c", "gsk_d") and settings.groq_api_key == "gsk_a"


def test_rest_time_from_groq_answer():
    assert rest_from_response({"retry-after": "7"}, "") == timedelta(seconds=60)  # never shorter than a minute
    assert rest_from_response({"retry-after": "300"}, "") == timedelta(seconds=300)
    body = '{"error":{"message":"Rate limit reached for model whisper-large-v3-turbo on audio seconds per day (ASPD). Please try again in 1h2m7.5s."}}'
    assert rest_from_response({}, body) == timedelta(hours=1, minutes=2, seconds=7.5)


def test_round_robin_rest_and_exhaustion():
    clock = Clock()
    pool = GroqKeyPool(["k1", "k2", "k3"], now=clock)
    assert [pool.acquire() for _ in range(4)] == ["k1", "k2", "k3", "k1"]
    pool.rest("k2", timedelta(minutes=5), "429")
    assert [pool.acquire() for _ in range(3)] == ["k3", "k1", "k3"]
    pool.rest("k1", timedelta(minutes=1), "429")
    pool.rest("k3", timedelta(minutes=10), "429")
    with pytest.raises(GroqKeysExhausted) as err:
        pool.acquire()
    assert err.value.until == clock.t + timedelta(minutes=1)
    clock.t += timedelta(minutes=2)
    assert pool.acquire() == "k1"
    # k2 rests 5 minutes and k3 10, so both still rest 2 minutes later.
    assert [s["status"] for s in pool.status()] == ["ok", "resting", "resting"] and pool.status()[0]["name"] == "Key 1 · …k1"


def test_chunk_moves_to_next_key_on_limit(monkeypatch, tmp_path):
    chunk = tmp_path / "c.m4a"
    chunk.write_bytes(b"x")
    used = []

    def post(url, headers, files, data, timeout):
        key = headers["Authorization"].split()[-1]
        used.append(key)
        if key == "k1":
            return SimpleNamespace(status_code=429, headers={"retry-after": "120"}, text="limited")
        if key == "k2":
            return SimpleNamespace(status_code=401, headers={}, text="invalid key")
        return SimpleNamespace(status_code=200, headers={}, text="", json=lambda: {"text": "ok", "segments": []})

    monkeypatch.setattr(media.requests, "post", post)
    clock = Clock()
    pool = GroqKeyPool(["k1", "k2", "k3"], now=clock)
    assert media.groq_transcribe_chunk(chunk, pool, "whisper", "")["text"] == "ok"
    assert used == ["k1", "k2", "k3"]
    states = [s["status"] for s in pool.status()]
    assert states == ["resting", "resting", "ok"]
    # The limited key comes back after its wait; the rejected one rests a day.
    clock.t += timedelta(minutes=3)
    assert [s["status"] for s in pool.status()] == ["ok", "resting", "ok"]


def test_pool_state_survives_runs_without_storing_keys(session):
    clock = Clock()
    pool = GroqKeyPool(["gsk_secret_one", "gsk_secret_two"], session=session, now=clock)
    pool.acquire()
    pool.rest("gsk_secret_one", timedelta(hours=1), "429")
    stored = session.get(Setting, STATE_KEY).value
    assert "gsk_secret" not in stored
    again = GroqKeyPool(["gsk_secret_one", "gsk_secret_two"], session=session, now=clock)
    assert again.acquire() == "gsk_secret_two"


def test_video_waits_when_every_key_rests(session, config, fake_anthropic, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEYS", "k1")
    store_items(session, "youtube", [CollectedItem(url="https://www.youtube.com/watch?v=abc", title="Shopify theme review", media_type="video", extra={"duration": 300})], config.keywords)
    session.commit()

    def groq(url, work_dir, keys, model, terms, chunk_seconds, max_seconds):
        raise GroqKeysExhausted(datetime.now(timezone.utc) + timedelta(minutes=30))

    stats = process_videos(session, config, ClaudeClient(session, model="claude-opus-5-5", client=fake_anthropic), fetch_subtitles=lambda *a: None, transcribe_groq=groq, get_duration=lambda u: 300)
    row = session.scalar(select(ItemTranscript))
    assert stats.waiting_for_keys == 1 and stats.failed == 0
    assert row.status == "pending" and row.attempts == 0  # not counted against the video
    assert session.scalar(select(Item.id)) == row.item_id
