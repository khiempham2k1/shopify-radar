from datetime import timedelta

import pytest
from sqlalchemy import func, select

from radar.collectors.base import CollectedItem
from radar.config_loader import validate_text
from radar.ingest import prune_stale, store_items, with_priority_queries
from radar.models import AIAnalyzed, Item, ItemStatus, utcnow
from radar.priority import match_priorities, parse_priorities
from radar.scoring import recency, rescore


def test_parse_priorities_names_aliases_and_regex():
    topics = parse_priorities("# c\n\nShopify Canvas | Canvas editor | /canvas\\s+api/\nCheckout Blocks\n")
    assert [t.name for t in topics] == ["Shopify Canvas", "Checkout Blocks"]
    assert match_priorities(topics, "New shopify  canvas release") == ["Shopify Canvas"]
    assert match_priorities(topics, "Docs for the Canvas API") == ["Shopify Canvas"]
    assert match_priorities(topics, "canvassing merchants") == []
    with pytest.raises(ValueError):
        validate_text("priorities.txt", "/only regex/")


def test_old_items_are_skipped_and_undated_videos_too(session, config):
    now = utcnow()
    items = [
        CollectedItem(url="https://y/old", title="Shopify theme review", published_at=now - timedelta(days=3 * 365)),
        CollectedItem(url="https://y/new", title="Shopify theme review 2", published_at=now - timedelta(days=2)),
        CollectedItem(url="https://y/undated", title="Shopify theme review 3"),
    ]
    # youtube has drop_undated: true in sources.yaml
    stats = store_items(session, "youtube", items, config.keywords, max_age_days=30)
    assert (stats.new, stats.too_old) == (1, 2)
    assert set(session.scalars(select(Item.url))) == {"https://y/new"}
    # Reddit keeps undated posts; only the dated old one is dropped.
    stats = store_items(session, "reddit", [CollectedItem(url=i.url.replace("y/", "r/"), title=i.title, published_at=i.published_at) for i in items], config.keywords, max_age_days=30)
    assert (stats.new, stats.too_old) == (2, 1)


def test_drop_undated_follows_source_config(session, config):
    from radar.models import Source

    session.get(Source, "youtube").config = {**session.get(Source, "youtube").config, "drop_undated": True}
    stats = store_items(session, "youtube", [CollectedItem(url="https://y/u", title="Shopify theme")], config.keywords, max_age_days=30)
    assert (stats.new, stats.too_old) == (0, 1)
    stats = store_items(session, "youtube", [CollectedItem(url="https://y/u", title="Shopify theme")], config.keywords, max_age_days=0)
    assert stats.new == 1


def test_priority_item_passes_keyword_filter(session, config):
    stats = store_items(
        session, "reddit", [CollectedItem(url="https://r/c", title="First look at Shopify Canvas")], config.keywords, priorities=config.priorities
    )
    item = session.scalar(select(Item))
    assert stats.new == 1 and item.priority == "Shopify Canvas" and item.keyword_matched


def test_priority_queries_added_once():
    topics = parse_priorities("Shopify Canvas\n")
    source = {"id": "x", "queries": ["shopify theme", '"shopify canvas"']}
    assert with_priority_queries(source, topics)["queries"] == source["queries"]
    assert with_priority_queries({"id": "x", "queries": ["a"]}, topics)["queries"] == ["a", "Shopify Canvas"]
    assert with_priority_queries({"id": "rss"}, topics) == {"id": "rss"}
    assert with_priority_queries({"id": "x", "queries": ["a"], "priority_search": False}, topics)["queries"] == ["a"]


def test_prune_stale_keeps_items_someone_is_working_on(session, config):
    now = utcnow()
    old = now - timedelta(days=400)
    for i in range(3):
        session.add(Item(source_id="youtube", url=f"https://y/{i}", title=f"v{i}", published_at=old if i < 2 else now, first_seen=now, last_seen=now))
    session.flush()
    first = session.scalar(select(Item).where(Item.url == "https://y/0"))
    session.add(ItemStatus(item_id=first.id, status="doing", owner="lead"))
    session.add(AIAnalyzed(item_id=session.scalar(select(Item.id).where(Item.url == "https://y/1")), prompt_hash="x", matched=False))
    session.flush()
    assert prune_stale(session, config) == 1
    assert set(session.scalars(select(Item.url))) == {"https://y/0", "https://y/2"}
    assert session.scalar(select(func.count()).select_from(AIAnalyzed)) == 0


def test_recency_uses_publish_date_and_priority_boost(session, config):
    now = utcnow()
    assert recency(now, now, 48, published_at=now - timedelta(days=365)) < 0.001
    assert recency(now, now, 48) == 1.0
    a = Item(source_id="reddit", url="https://r/a", title="Notes on Shopify Canvas", first_seen=now, last_seen=now, keyword_matched=True)
    b = Item(source_id="reddit", url="https://r/b", title="Notes on something else", first_seen=now, last_seen=now, keyword_matched=True)
    session.add_all([a, b])
    session.flush()
    rescore(session, config, now=now)
    assert a.priority == "Shopify Canvas" and b.priority is None
    assert a.score == pytest.approx(min(10.0, b.score + float(config.scoring["priority_boost"])))
