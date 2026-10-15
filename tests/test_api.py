import pytest
from fastapi.testclient import TestClient

from radar.db import session_factory
from radar.demo import seed


@pytest.fixture()
def client(db_url, monkeypatch):
    session = session_factory(db_url)()
    seed(session)
    session.commit()
    session.close()
    from api.main import app

    return TestClient(app)


def test_token_required_when_configured(client, monkeypatch):
    monkeypatch.setenv("RADAR_API_TOKEN", "secret")
    assert client.get("/api/overview").status_code == 401
    ok = client.get("/api/me", headers={"Authorization": "Bearer secret", "X-Radar-User": "lead@company.com"})
    assert ok.status_code == 200 and ok.json() == {"user": "lead@company.com"}
    assert client.get("/api/health").status_code == 200


def test_overview(client):
    data = client.get("/api/overview").json()
    assert data["kpis"]["todo"] >= 2
    assert len(data["daily"]) == 14
    assert data["topics"] and data["todo"][0]["impact"] == "high"


def test_feed_filters_and_order(client):
    feed = client.get("/api/items", params={"view": "feed", "mode": "all"}).json()
    hot = [i["hot"] for i in feed["items"]]
    assert hot == sorted(hot, reverse=True) and feed["total"] == len(feed["items"])  # Feed: hottest first
    by_score = [i["score"] for i in client.get("/api/items", params={"view": "feed", "sort": "score"}).json()["items"]]
    assert by_score == sorted(by_score, reverse=True)
    assert all(i["source"]["kind"] != "platform" for i in feed["items"])
    neg = client.get("/api/items", params={"view": "feed", "sentiment": "neg"}).json()["items"]
    assert neg and all(i["sentiment"] == "neg" for i in neg)
    found = client.get("/api/items", params={"view": "feed", "q": "mega menu"}).json()["items"]
    assert len(found) == 1
    videos = [i for i in feed["items"] if i["media_type"] == "video"]
    assert videos and videos[0]["transcript"]["status"] == "done" and videos[0]["transcript"]["points"]


def test_platform_view_and_status_flow(client):
    items = client.get("/api/items", params={"view": "platform"}).json()["items"]
    target = next(i for i in items if i["deadline"])
    assert target["days_left"] is not None
    updated = client.patch(f"/api/items/{target['id']}", json={"status": "doing", "owner": "lead@company.com"}, headers={"X-Radar-User": "lead@company.com"}).json()
    assert updated["status"] == "doing" and updated["owner"] == "lead@company.com"
    client.patch(f"/api/items/{target['id']}", json={"status": "dismissed"})
    ids = [i["id"] for i in client.get("/api/items", params={"view": "platform"}).json()["items"]]
    assert target["id"] not in ids
    dismissed = client.get("/api/items", params={"view": "platform", "status": "dismissed"}).json()["items"]
    assert [i["id"] for i in dismissed] == [target["id"]]
    assert client.patch("/api/items/99999", json={"status": "done"}).status_code == 404


def test_item_detail_includes_segments(client):
    feed = client.get("/api/items", params={"view": "feed"}).json()["items"]
    video = next(i for i in feed if i["media_type"] == "video")
    detail = client.get(f"/api/items/{video['id']}").json()
    assert detail["transcript"]["segments"]


def test_editions_and_health(client):
    editions = client.get("/api/editions").json()
    assert editions[0]["edition"] == "Summer '26" and editions[0]["total"] == 6
    health = client.get("/api/health/sources").json()
    by_id = {s["id"]: s for s in health["sources"]}
    assert by_id["reddit"]["status"] == "warn" and by_id["reddit"]["backend"] == "exa"
    assert by_id["reddit"]["configured_backends"] == ["rdt-cli", "exa"]
    assert health["videos"]["groq_24h"] + health["videos"]["subtitle_24h"] >= 1
    assert health["logins"]["checks"][0]["status"] == "warn"


def test_reports(client):
    reports = client.get("/api/reports").json()
    detail = client.get(f"/api/reports/{reports[0]['id']}").json()
    assert detail["content"]["actions"][0]["owner"] == "Tech lead"
    assert client.get("/api/reports/999").status_code == 404


def test_settings_validation_save_and_reset(client):
    files = {f["name"]: f for f in client.get("/api/settings").json()}
    assert set(files) == {"sources.yaml", "keywords.txt", "priorities.txt", "interests.txt", "terms.txt"}
    assert files["keywords.txt"]["origin"] == "file"
    bad = client.put("/api/settings/keywords.txt", json={"value": "[G]\n/(bad/\n"})
    assert bad.status_code == 400 and "Regex" in bad.json()["detail"]
    dup = client.put("/api/settings/sources.yaml", json={"value": "sources:\n  - id: a\n  - id: a\n"})
    assert dup.status_code == 400
    saved = client.put("/api/settings/interests.txt", json={"value": "Chỉ quan tâm checkout"}, headers={"X-Radar-User": "pm@company.com"}).json()
    assert saved["origin"] == "db" and saved["updated_by"] == "pm@company.com"
    assert client.delete("/api/settings/interests.txt").json()["origin"] == "file"
    assert client.put("/api/settings/other.txt", json={"value": "x"}).status_code == 404


def test_usage(client):
    data = client.get("/api/usage", params={"days": 14}).json()
    assert len(data["daily"]) == 14 and data["total_cost"] > 0
    tasks = {t["task"] for t in data["by_task"]}
    assert {"classify", "summarize", "report"} <= tasks
    assert data["groq"]["videos"] == 1


def test_priority_items_on_overview_and_filter(client):
    data = client.get("/api/overview").json()
    assert data["priority"]["topics"] == ["Shopify Canvas"]
    assert [i["priority"] for i in data["priority"]["items"]] == [["Shopify Canvas"]]
    only = client.get("/api/items", params={"view": "feed", "priority": "true"}).json()["items"]
    assert len(only) == 1 and "Shopify Canvas" in only[0]["title"]
    # Low AI score (0.45 < min_score) but still listed, and boosted above plain items with similar relevance.
    assert only[0]["relevance"] < 0.5


def test_filter_by_who_is_affected(client):
    partner = client.get("/api/items", params={"view": "platform", "affects": "partner"}).json()["items"]
    assert partner and all("partner" in i["affects"] for i in partner)
    assert all("Theme Store" in i["title"] for i in partner)
    assert client.get("/api/items", params={"affects": "app"}).status_code == 422


def test_public_health_hides_tools_and_config(client):
    public = {"X-Radar-User": "anonymous"}
    data = client.get("/api/health/sources", headers=public).json()
    assert data["logins"] is None and all(s["backend"] == "" and s["configured_backends"] == [] and s["message"] == "" for s in data["sources"])
    assert client.get("/api/health", headers=public).json() == {"ok": True}
    admin = {"X-Radar-User": "lead@company.com", "X-Radar-Admin": "1"}
    assert client.get("/api/health/sources", headers=admin).json()["logins"] is not None
    assert "db" in client.get("/api/health", headers=admin).json() and "db" in client.get("/api/health").json()


def test_official_items_lead_the_feed(client, db_url):
    from sqlalchemy import select

    from radar.models import Item

    session = session_factory(db_url)()
    coldest = session.scalars(select(Item).join(Item.source).where(Item.source.has(kind="web"))).first()
    coldest.official, coldest.hot = True, 0.0
    session.commit()
    session.close()
    feed = client.get("/api/items", params={"view": "feed"}).json()["items"]
    assert feed[0]["id"] == coldest.id and feed[0]["official"] is True
    newest = client.get("/api/items", params={"view": "feed", "sort": "new"}).json()["items"]
    assert newest[0]["id"] != coldest.id or len(newest) == 1


def test_community_page(client, db_url, fake_anthropic):
    from radar.ai import community
    from radar.ai.client import ClaudeClient
    from radar.config_loader import load_config
    from tests.test_community import seed_talk

    session = session_factory(db_url)()
    config = load_config(session)
    seed_talk(session, config)
    community.refresh(session, config, ClaudeClient(session, model="claude-opus-5-5", client=fake_anthropic), force=True)
    session.commit()
    session.close()

    data = client.get("/api/community").json()
    assert data["digest"]["overview"] and data["digest"]["topics"][0]["items"]
    assert {i["place"] for i in data["digest"]["topics"][0]["items"]} <= {"Discord #general", "Discord #theme-dev", "Shopify Community"}
    assert any(t["title"] == "Editor slow on Dawn" and t["summary"] for t in data["threads"])
    assert {c["name"]: c["count"] for c in data["channels"]}["Discord #general"] == 5
    assert data["digests"][0]["id"] == data["digest"]["id"]
    # Community talk stays out of the Feed.
    feed = client.get("/api/items", params={"view": "feed", "mode": "all"}).json()["items"]
    assert not [i for i in feed if i["source"]["kind"] == "community"]
    # Weekly reports list only weekly reports.
    assert all(r.get("kind", "weekly") == "weekly" for r in client.get("/api/reports").json())


def test_platform_can_show_changes_ai_rejected(client, db_url):
    from radar.ingest import store_items
    from radar.collectors.base import CollectedItem
    from radar.config_loader import load_config
    from radar.models import AIAnalyzed, Item
    from sqlalchemy import select

    session = session_factory(db_url)()
    config = load_config(session)
    store_items(session, "shopify-dev-changelog", [CollectedItem(url="https://shopify.dev/changelog/carts-update", title="Unchanged carts no longer trigger carts/update webhooks", media_type="change")], config.keywords)
    item = session.scalar(select(Item).where(Item.url == "https://shopify.dev/changelog/carts-update"))
    session.add(AIAnalyzed(item_id=item.id, prompt_hash="x", method="ai", matched=False))
    session.commit()
    item_id = item.id
    session.close()
    default = [i["id"] for i in client.get("/api/items", params={"view": "platform"}).json()["items"]]
    everything = [i["id"] for i in client.get("/api/items", params={"view": "platform", "all_changes": "true"}).json()["items"]]
    assert item_id not in default and item_id in everything
