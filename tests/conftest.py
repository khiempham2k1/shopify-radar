from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest

from radar.config_loader import load_config
from radar.db import init_db, session_factory
from radar.ingest import sync_sources


@pytest.fixture()
def db_url(tmp_path, monkeypatch) -> str:
    """SQLite per test by default. Set TEST_DATABASE_URL to run the suite on Postgres
    (the schema is dropped and recreated for every test)."""
    url = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{tmp_path / 'radar.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    from radar.db import get_engine

    get_engine.cache_clear()  # the API resolves DATABASE_URL through this cache; each test has its own DB
    monkeypatch.setenv("RADAR_WORK_DIR", str(tmp_path / "work"))
    monkeypatch.delenv("RADAR_API_TOKEN", raising=False)
    if os.environ.get("TEST_DATABASE_URL"):
        from radar.db import get_engine
        from radar.models import Base

        Base.metadata.drop_all(get_engine(url))
    init_db(url)
    return url


@pytest.fixture()
def session(db_url):
    s = session_factory(db_url)()
    yield s
    s.close()


@pytest.fixture()
def config(session):
    cfg = load_config(session)
    sync_sources(session, cfg)
    session.commit()
    return cfg


def make_message(payload: Any, stop_reason: str = "end_turn", model: str = "claude-opus-5-5", input_tokens: int = 1000, output_tokens: int = 100):
    return SimpleNamespace(
        id="msg_test",
        model=model,
        stop_reason=stop_reason,
        stop_details=SimpleNamespace(category="cyber") if stop_reason == "refusal" else None,
        content=[SimpleNamespace(type="text", text=payload if isinstance(payload, str) else json.dumps(payload))],
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens, cache_read_input_tokens=500, cache_creation_input_tokens=0),
    )


def default_responder(kwargs: dict[str, Any]):
    schema = kwargs["output_config"]["format"]["schema"]
    props = schema["properties"]
    user = kwargs["messages"][0]["content"]
    if "keep_ids" in props:
        return make_message({"keep_ids": [], "add": [{"tag": "Chủ đề mới", "description": "mới"}], "change_ratio": 0.2})
    if "tags" in props:
        return make_message(
            {
                "tags": [
                    {"tag": "Thay đổi nền tảng", "description": "API, deprecation"},
                    {"tag": "Nhu cầu merchant", "description": "Tính năng merchant cần"},
                ]
            }
        )
    if "results" in props:
        ids = [int(i) for i in re.findall(r"\[id=(\d+)\]", user)]
        tag_ids = [int(i) for i in re.findall(r"^(\d+)\. ", kwargs["system"][0]["text"], re.M)]
        return make_message(
            {
                "results": [
                    {"id": i, "tag_id": tag_ids[0], "score": 0.9, "sentiment": "neg", "impact": "high", "affects": ["theme", "merchant"], "area": "cart_checkout", "reason": "Giỏ hàng do theme thao tác", "deadline": "2027-01-01", "summary": f"Tóm tắt {i}"}
                    for i in ids
                ]
            }
        )
    if "overview" in props:
        ids = [int(i) for i in re.findall(r"^\[(\d+)\]", user, re.M)]
        return make_message(
            {
                "overview": "Cộng đồng bàn nhiều về theme editor chậm.",
                "topics": [{"title": "Theme editor chậm", "summary": "Nhiều người báo editor chậm.", "kind": "problem", "sources": ["Discord #general"], "item_ids": ids[:3] + [99999], "mentions": 2, "people": 2}],
                "open_questions": [{"text": "Có cách nào tăng tốc editor?", "item_ids": ids[:1]}],
            }
        )
    if "headline" in props:
        ids = [int(i) for i in re.findall(r"^\[(\d+)\]", user, re.M)]
        return make_message(
            {
                "headline": "Shopify đổi cách giỏ hàng phát webhook.",
                "summary": "Tuần này có thay đổi giỏ hàng và cộng đồng hỏi nhiều về theme editor.",
                "highlights": [{"text": "Giỏ hàng không đổi thì không còn phát carts/update.", "item_ids": ids[:2] + [99999]}],
                "must_read": [{"item_id": i, "why": f"Đọc bài {i}"} for i in [*ids, 99999]],
                "discussions": [{"item_id": i, "why": f"Thảo luận {i}"} for i in [*ids, 99999]],
            }
        )
    if set(props) == {"note"}:
        return make_message({"note": "Ảnh chụp thông báo lỗi trong theme editor."})
    if "translations" in props:
        ids = [int(i) for i in re.findall(r"\[id=(\d+)\]", user)]
        return make_message({"translations": [{"id": i, "vi": f"Bản dịch {i}"} for i in ids]})
    if set(props) == {"items"}:
        ids = [int(i) for i in re.findall(r"\[id=(\d+)\]", user)]
        return make_message({"items": [{"id": i, "summary": f"Tóm tắt chủ đề {i}"} for i in ids]})
    if "points" in props:
        return make_message({"summary": "Video nói về tốc độ theme.", "points": [{"t": 65, "text": "Ý chính một"}, {"t": 130, "text": "Ý chính hai"}]})
    if "risks" in props:
        return make_message(
            {
                "summary": "Tuần nhiều thay đổi.",
                "risks": [{"text": "Rủi ro", "item_ids": [1, 999]}],
                "opportunities": [{"text": "Cơ hội", "item_ids": []}],
                "actions": [{"text": "Làm việc A", "owner": "Tech lead"}],
            }
        )
    raise AssertionError(f"Unexpected schema {list(props)}")


class FakeMessages:
    def __init__(self, responder: Callable[[dict[str, Any]], Any]) -> None:
        self.responder = responder
        self.calls: list[dict[str, Any]] = []
        self.batches = FakeBatches(self)

    def create(self, **kwargs: Any):
        self.calls.append(kwargs)
        return self.responder(kwargs)


class FakeBatches:
    def __init__(self, messages: FakeMessages) -> None:
        self.messages = messages
        self.submitted: dict[str, list] = {}
        self.ended = True

    def create(self, requests):
        batch_id = f"batch_{len(self.submitted) + 1}"
        self.submitted[batch_id] = requests
        return SimpleNamespace(id=batch_id, processing_status="in_progress")

    def retrieve(self, batch_id):
        return SimpleNamespace(id=batch_id, processing_status="ended" if self.ended else "in_progress")

    def results(self, batch_id):
        for request in self.submitted[batch_id]:
            params = dict(request["params"])
            message = self.messages.responder(params)
            yield SimpleNamespace(custom_id=request["custom_id"], result=SimpleNamespace(type="succeeded", message=message))


class FakeAnthropic:
    def __init__(self, responder: Callable[[dict[str, Any]], Any] = default_responder) -> None:
        self.messages = FakeMessages(responder)
        self.beta = SimpleNamespace(messages=self.messages)


@pytest.fixture()
def fake_anthropic() -> FakeAnthropic:
    return FakeAnthropic()
