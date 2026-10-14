import json
import os
import stat

import pytest

from radar.collectors import exa
from radar.collectors.base import (
    CollectedItem,
    CollectError,
    Collector,
    domain_ok,
    run_cli,
    strip_html,
    to_datetime,
)
from radar.collectors.editions import find_editions, split_features
from radar.collectors.feeds import (
    RSSCollector,
    links_from_markdown,
    parse_feed,
    unwrap_google_redirect,
)
from radar.collectors.social import (
    reddit_post_to_item,
    tweet_to_item,
    video_entry_to_item,
)

RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>Changelog</title>
<item><title>Theme Store performance requirement update</title>
<link>https://shopify.dev/changelog/theme-store-performance</link>
<description><![CDATA[<p>Themes must score <b>60</b>+ on mobile.</p>]]></description>
<pubDate>Mon, 12 Oct 2026 10:00:00 GMT</pubDate><guid>tsp-1</guid></item>
<item><title>Off-site link</title><link>https://evil.example.com/x</link></item>
</channel></rss>"""


def test_parse_feed_strips_html_and_checks_domain():
    items = parse_feed(RSS, media_type="change", expected_domain="shopify.dev")
    assert len(items) == 1
    item = items[0]
    assert item.title == "Theme Store performance requirement update"
    assert "60" in item.content and "<b>" not in item.content
    assert item.published_at.year == 2026 and item.external_id == "tsp-1"


def test_domain_ok_rejects_userinfo_and_http():
    assert domain_ok("https://shopify.dev/a", "shopify.dev")
    assert domain_ok("https://community.shopify.com/t/1", "shopify.com")
    assert not domain_ok("http://shopify.dev/a", "shopify.dev")
    assert not domain_ok("https://shopify.dev@evil.com/a", "shopify.dev")
    assert not domain_ok("https://notshopify.dev/a", "shopify.dev")


def test_google_alert_links_are_unwrapped():
    wrapped = "https://www.google.com/url?rct=j&sa=t&url=https://blog.example.com/post&ct=ga"
    assert unwrap_google_redirect(wrapped) == "https://blog.example.com/post"


def test_strip_html_and_dates():
    assert strip_html("<p>a&amp;b</p><script>x()</script>") == "a&b"
    assert to_datetime(1760000000).year == 2025
    assert to_datetime("20261001").month == 10
    assert to_datetime("2026-10-01T10:00:00Z").tzinfo is not None
    assert to_datetime("Mon, 12 Oct 2026 10:00:00 GMT").day == 12
    assert to_datetime("garbage") is None


def test_links_from_markdown_filters_by_path_and_domain():
    md = "[Nav](https://changelog.shopify.com/about) [New checkout extension targets](https://changelog.shopify.com/posts/new-targets) [Elsewhere post](https://x.com/posts/a)"
    assert links_from_markdown(md, "https://changelog.shopify.com/", "/posts/", "shopify.com") == [
        ("New checkout extension targets", "https://changelog.shopify.com/posts/new-targets")
    ]


EDITIONS_INDEX = """
[Winter '26 Edition](https://www.shopify.com/editions/winter2026) and [Summer '26](https://www.shopify.com/editions/summer2026)
[Older](https://www.shopify.com/editions/summer2025)
"""

EDITION_PAGE = """
Intro text
## Online Store
### Theme blocks everywhere
Merchants can now add theme blocks inside any section, with settings per block and color schemes.
### Tiny
too short
## Checkout
### Thank you page extensions
Checkout UI extensions now target the thank you page, replacing additional scripts for post-purchase content.
"""


def test_editions_newest_first_and_features_split():
    editions = find_editions(EDITIONS_INDEX)
    assert editions[0] == ("Summer '26", "https://www.shopify.com/editions/summer2026")
    assert editions[1][0] == "Winter '26"
    items = split_features(EDITION_PAGE, "Summer '26", "https://www.shopify.com/editions/summer2026")
    assert [i.title for i in items] == ["Summer '26: Theme blocks everywhere", "Summer '26: Thank you page extensions"]
    assert items[0].url.endswith("#theme-blocks-everywhere")
    assert items[1].extra == {"edition": "Summer '26", "section": "Checkout"}


def test_reddit_tweet_and_video_mapping():
    post = {"id": "abc", "title": "Theme help", "permalink": "/r/shopify/comments/abc/x/", "score": 12, "num_comments": 4, "created_utc": 1760000000, "subreddit": "shopify", "selftext": "body"}
    item = reddit_post_to_item(post)
    assert item.url == "https://www.reddit.com/r/shopify/comments/abc/x/"
    assert item.metrics == {"upvotes": 12, "comments": 4}
    assert reddit_post_to_item({**post, "over_18": True}) is None

    tweet = {"id": "99", "text": "Need a theme\nwith mega menu", "author": {"screenName": "shopdev"}, "metrics": {"likes": 3, "retweets": 1, "replies": 2, "views": 50}, "createdAt": "2026-10-01T10:00:00Z"}
    t = tweet_to_item(tweet)
    assert t.url == "https://x.com/shopdev/status/99" and t.title == "Need a theme" and t.metrics["comments"] == 2

    v = video_entry_to_item({"id": "vid1", "title": "Theme review", "channel": "Chan", "duration": 600, "view_count": 1000})
    assert v.url == "https://www.youtube.com/watch?v=vid1" and v.media_type == "video" and v.extra["duration"] == 600


def test_exa_parser_handles_json_and_text():
    as_json = json.dumps({"results": [{"title": "A", "url": "https://a.com", "text": "body", "publishedDate": "2026-10-01"}]})
    assert exa.parse_exa_text(as_json)[0].url == "https://a.com"
    as_text = "Title: First\nURL: https://one.com\nPublished Date: 2026-10-01\nText: hello world\n\nTitle: Second\nURL: https://two.com\nText: bye"
    hits = exa.parse_exa_text(as_text)
    assert [h.url for h in hits] == ["https://one.com", "https://two.com"]
    assert hits[0].text.startswith("hello")


class TwoBackends(Collector):
    type = "test"
    default_backends = ["first", "second"]

    def fetch_first(self):
        raise CollectError("cookie expired")

    def fetch_second(self):
        return [CollectedItem(url="https://x.com/1", title="t")]


def test_collector_falls_back_and_warns():
    result = TwoBackends({"id": "t"}).collect()
    assert result.status == "warn" and result.backend == "second"
    assert "cookie expired" in result.message


def test_collector_all_fail_is_error():
    class Broken(TwoBackends):
        def fetch_second(self):
            raise RuntimeError("boom")

    result = Broken({"id": "t"}).collect()
    assert result.status == "error" and result.items == []
    assert "boom" in result.message


def _fake_cli(tmp_path, name, payload, monkeypatch):
    script = tmp_path / name
    script.write_text("#!/bin/sh\ncat <<'EOF'\n" + json.dumps(payload) + "\nEOF\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")


def test_run_cli_reads_envelope(tmp_path, monkeypatch):
    _fake_cli(tmp_path, "rdt", {"ok": True, "schema_version": "1", "data": [{"id": "1"}]}, monkeypatch)
    assert run_cli(["rdt", "search", "x"]) == [{"id": "1"}]


def test_run_cli_reports_error_code(tmp_path, monkeypatch):
    _fake_cli(tmp_path, "twitter", {"ok": False, "error": {"code": "not_authenticated", "message": "need login"}}, monkeypatch)
    with pytest.raises(CollectError, match="not_authenticated"):
        run_cli(["twitter", "search", "x"])


def test_run_cli_missing_binary():
    with pytest.raises(CollectError, match="Chưa cài"):
        run_cli(["definitely-not-installed-cli"])


class FakeHttp:
    def __init__(self, pages):
        self.pages = pages

    def get(self, url, **kwargs):
        if url not in self.pages:
            raise CollectError("HTTP 404")
        return type("R", (), {"text": self.pages[url]})()

    def read_page(self, url):
        return "", self.pages[url]

    def pause(self, seconds=1.0):
        pass


def test_rss_collector_uses_page_fallback():
    source = {
        "id": "shopify-changelog",
        "type": "rss",
        "urls": ["https://changelog.shopify.com/feed.xml"],
        "page_fallback": "https://changelog.shopify.com/",
        "expected_domain": "shopify.com",
        "media_type": "change",
    }
    http = FakeHttp({"https://changelog.shopify.com/": "[Bundles in checkout are here](https://changelog.shopify.com/posts/bundles)"})
    result = RSSCollector(source, http).collect()
    assert result.status == "warn" and result.backend == "page"
    assert result.items[0].url == "https://changelog.shopify.com/posts/bundles"
    assert result.items[0].media_type == "change"


def test_login_check_warns_on_old_cookie(tmp_path, monkeypatch):
    from radar.doctor import check_login

    cred = tmp_path / "credential.json"
    cred.write_text("{}")
    old = cred.stat().st_mtime - 6.5 * 86400
    os.utime(cred, (old, old))
    _fake_cli(tmp_path, "rdt", {"ok": True, "data": {"authenticated": True, "credential_file": str(cred)}}, monkeypatch)
    check = check_login("rdt-cli (Reddit)", ["rdt", "status", "--json"], "Làm mới cookie")
    assert check.status == "warn" and "6 ngày" in check.message

    os.utime(cred, None)
    assert check_login("rdt-cli (Reddit)", ["rdt", "status", "--json"], "x").status == "ok"
    _fake_cli(tmp_path, "rdt", {"ok": False, "error": {"code": "not_authenticated"}}, monkeypatch)
    assert check_login("rdt-cli (Reddit)", ["rdt", "status", "--json"], "x").status == "warn"


def test_youtube_search_target():
    from radar.collectors.social import youtube_search_target

    assert youtube_search_target("shopify theme", 5) == "https://www.youtube.com/results?search_query=shopify+theme&sp=CAI%253D"
    assert youtube_search_target("shopify theme", 5, "relevance") == "ytsearch5:shopify theme"
