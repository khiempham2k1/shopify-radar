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
    scores = [i["score"] for i in feed["items"]]
    assert scores == sorted(scores, reverse=True) and feed["total"] == len(feed["items"])
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
