from sqlalchemy import func, select

from radar.collectors.base import CollectedItem
from radar.collectors.social import tweet_to_item
from radar.ingest import store_items
from radar.models import Item, ItemKey
from radar.official import is_official, official_first
from radar.scoring import rescore


def test_what_counts_as_official(config):
    web = next(s for s in config.raw["sources"] if s["id"] == "web-search")
    settings = config.official
    assert is_official("https://shopify.dev/docs/storefronts/themes/architecture", web, settings)
    assert is_official("https://help.shopify.com/en/manual/online-store/themes", web, settings)
    assert is_official("https://github.com/Shopify/dawn/releases/tag/v15", web, settings)
    assert not is_official("https://github.com/someone/shopify-theme", web, settings)
    assert not is_official("https://community.shopify.com/t/theme-editor-slow/123", web, settings)
    assert not is_official("https://www.reddit.com/r/shopify/comments/1", web, settings)
    assert not is_official("https://shopify.dev.evil.example/x", web, settings)
    assert is_official("https://x.com/ShopifyDevs/status/1", {"kind": "platform"}, settings)
    assert not is_official("https://shopify.dev/x", {"kind": "web", "official": False}, settings)


def test_official_sources_are_collected_first(config):
    order = [s["id"] for s in official_first(config.sources)]
    first_social = min(order.index(s) for s in ("reddit", "twitter", "youtube", "web-search"))
    assert all(order.index(s) < first_social for s in ("shopify-dev-changelog", "shopify-editions", "x-official"))


def tweet(id, handle, text):
    return {"id": id, "text": text, "author": {"screenName": handle}, "metrics": {"likes": 3}, "createdAt": "2026-10-15T01:00:00+00:00", "urls": []}


def test_official_copy_replaces_one_found_earlier_elsewhere(session, config):
    text = "Theme blocks now support nesting and presets across every Theme Store theme from today."
    # X search finds the @ShopifyDevs tweet before the official-accounts source runs.
    found = store_items(session, "twitter", [tweet_to_item(tweet("555", "ShopifyDevs", text))], config.keywords, official_settings=config.official)
    assert found.new == 1
    copy = session.scalar(select(Item))
    assert not copy.official

    official = store_items(session, "x-official", [tweet_to_item(tweet("555", "ShopifyDevs", text))], config.keywords, official_settings=config.official)
    items = list(session.scalars(select(Item)))
    assert (official.new, official.merged) == (1, 1) and len(items) == 1
    kept = items[0]
    assert kept.source_id == "x-official" and kept.official
    assert [a["source"] for a in kept.extra["also"]] == ["twitter"]
    assert set(session.scalars(select(ItemKey.item_id))) == {kept.id}

    # Found again by search later: attached to the official item, not stored.
    again = store_items(session, "twitter", [tweet_to_item(tweet("555", "ShopifyDevs", text))], config.keywords, official_settings=config.official)
    assert (again.new, again.merged) == (0, 1) and session.scalar(select(func.count()).select_from(Item)) == 1


def test_official_pages_from_web_search_rank_first(session, config):
    store_items(
        session,
        "web-search",
        [
            CollectedItem(url="https://blog.example.com/best-shopify-theme", title="Best Shopify theme for fashion stores", metrics={}),
            CollectedItem(url="https://shopify.dev/docs/storefronts/themes/store/requirements", title="Theme Store requirements for Shopify theme developers"),
        ],
        config.keywords,
        official_settings=config.official,
    )
    rescore(session, config)
    rows = {i.url: i for i in session.scalars(select(Item))}
    official = rows["https://shopify.dev/docs/storefronts/themes/store/requirements"]
    other = rows["https://blog.example.com/best-shopify-theme"]
    assert official.official and not other.official
    assert official.score >= other.score + float(config.scoring["official_boost"]) - 0.01
