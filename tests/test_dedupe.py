from datetime import timedelta

from sqlalchemy import func, select

from radar.collectors.base import CollectedItem
from radar.collectors.social import XAccountsCollector, tweet_to_item
from radar.dedupe import normalize_url
from radar.ingest import delete_items, ensure_url_keys, store_items
from radar.models import Item, ItemKey, Source, utcnow


def test_normalize_url():
    assert normalize_url("https://www.Shopify.dev/changelog/foo/?utm_source=x&utm_medium=social") == "https://shopify.dev/changelog/foo"
    assert normalize_url("https://shopify.dev/changelog/foo?page=2") == "https://shopify.dev/changelog/foo?page=2"
    assert normalize_url("https://www.shopify.com/editions/summer2026#theme-blocks") == "https://shopify.com/editions/summer2026#theme-blocks"
    assert normalize_url("https://twitter.com/Shopify/status/123?s=20") == "x:123"
    assert normalize_url("https://x.com/i/web/status/123") == "x:123" == normalize_url("https://x.com/ShopifyDevs/status/123")


def tweet(id, text, handle, minutes_ago, urls=(), retweeted_by=None):
    now = utcnow()
    return {
        "id": id,
        "text": text,
        "author": {"screenName": handle},
        "metrics": {"likes": 1},
        "createdAt": (now - timedelta(minutes=minutes_ago)).isoformat(),
        "urls": list(urls),
        "retweetedBy": retweeted_by,
    }


CHANGELOG = "https://shopify.dev/changelog/theme-blocks-are-generally-available"
ANNOUNCE = "Theme blocks are now generally available for every theme on the Theme Store, with nesting and presets."


def fake_timelines(monkeypatch):
    timelines = {
        "ShopifyDevs": [tweet("100", ANNOUNCE + " https://t.co/a", "ShopifyDevs", 50, [CHANGELOG + "?utm_source=twitter"])],
        # @ShopifyEng retweets @ShopifyDevs: same tweet id and author, retweetedBy set
        "ShopifyEng": [tweet("100", ANNOUNCE, "ShopifyDevs", 50, [CHANGELOG], retweeted_by="ShopifyEng")],
        # @Shopify posts the same text as a new tweet, and a different post
        "Shopify": [
            tweet("101", ANNOUNCE, "Shopify", 40),
            tweet("102", "Meet the merchants who grew their business with Shopify this year and the stories behind them.", "Shopify", 30),
        ],
    }

    def run_cli(args, timeout=120):
        assert args[:2] == ["twitter", "user-posts"]
        return timelines[args[2]]

    monkeypatch.setattr("radar.collectors.social.run_cli", run_cli)


def official_source(config):
    return next(s for s in config.raw["sources"] if s["id"] == "x-official")


def test_official_accounts_merge_retweets(monkeypatch, config):
    fake_timelines(monkeypatch)
    collector = XAccountsCollector(official_source(config))
    collector.http.pause = lambda *_: None
    items = {i.external_id: i for i in collector.fetch_twitter_cli()}
    assert set(items) == {"100", "101", "102"}
    assert items["100"].extra["posted_by"] == ["ShopifyDevs", "ShopifyEng"]


def test_reposts_and_links_attach_to_existing_items(monkeypatch, session, config):
    # The changelog entry is collected first (platform sources run first).
    store_items(session, "shopify-dev-changelog", [CollectedItem(url=CHANGELOG, title="Theme blocks are generally available", media_type="change")], config.keywords)
    fake_timelines(monkeypatch)
    collector = XAccountsCollector(official_source(config))
    collector.http.pause = lambda *_: None
    stats = store_items(session, "x-official", collector.fetch_twitter_cli(), config.keywords, max_age_days=30)

    # 100 points at the changelog entry -> attached to it; 101 repeats 100's text -> attached too.
    assert (stats.new, stats.merged) == (1, 2)
    changelog = session.scalar(select(Item).where(Item.source_id == "shopify-dev-changelog"))
    also = changelog.extra["also"]
    assert [a["url"] for a in also] == ["https://x.com/ShopifyDevs/status/100", "https://x.com/Shopify/status/101"]
    assert also[0]["posted_by"] == ["ShopifyDevs", "ShopifyEng"] and also[0]["source_name"] == "Shopify trên X"
    assert session.scalar(select(func.count()).select_from(Item).where(Item.source_id == "x-official")) == 1

    # Next run: nothing new, nothing duplicated.
    again = store_items(session, "x-official", collector.fetch_twitter_cli(), config.keywords, max_age_days=30)
    assert again.new == 0 and len(session.get(Item, changelog.id).extra["also"]) == 2

    # X search finds the same official tweet: attached, not stored twice.
    found = tweet_to_item(tweet("102", "Meet the merchants who grew their business with Shopify this year and the stories behind them.", "Shopify", 30))
    search = store_items(session, "twitter", [found], config.keywords, max_age_days=30)
    assert (search.new, search.merged) == (0, 1)


def test_discussions_linking_to_a_change_stay_separate(session, config):
    store_items(session, "shopify-dev-changelog", [CollectedItem(url=CHANGELOG, title="Theme blocks GA", media_type="change")], config.keywords)
    post = CollectedItem(url="https://www.reddit.com/r/shopifydev/1", title="Theme blocks GA broke my shopify theme sections", extra={"links": [CHANGELOG]})
    assert store_items(session, "reddit", [post], config.keywords).new == 1  # reddit does not opt in to link keys


def test_keys_backfilled_and_removed_with_items(session, config):
    session.add(Item(source_id="reddit", url="https://www.reddit.com/r/shopify/old", title="old", first_seen=utcnow(), last_seen=utcnow()))
    session.flush()
    assert ensure_url_keys(session) == 1 and ensure_url_keys(session) == 0
    item_id = session.scalar(select(Item.id))
    delete_items(session, [item_id])
    assert session.scalar(select(func.count()).select_from(ItemKey)) == 0
    assert session.get(Source, "x-official").kind == "platform"


def test_generic_links_do_not_merge_posts():
    from radar.dedupe import item_keys

    config = {"dedupe_links": True}
    assert item_keys("https://x.com/Shopify/status/1", {"links": ["https://www.shopify.com/", "https://shopify.dev/docs"]}, source_config=config) == ["x:1"]
    keys = item_keys("https://x.com/Shopify/status/1", {"links": ["https://youtube.com/watch?v=abc", CHANGELOG]}, source_config=config)
    assert keys == ["x:1", "https://youtube.com/watch?v=abc", CHANGELOG]
