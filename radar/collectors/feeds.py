"""RSS/Atom based collectors: changelogs, GitHub releases, Google Alerts, Community."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urljoin, urlparse

import feedparser

from radar.collectors.base import (
    CollectedItem,
    CollectError,
    Collector,
    domain_ok,
    strip_html,
    to_datetime,
)


def unwrap_google_redirect(url: str) -> str:
    """Google Alerts wraps links as https://www.google.com/url?...&url=<real>."""
    parsed = urlparse(url)
    if parsed.hostname and parsed.hostname.endswith("google.com") and parsed.path == "/url":
        target = parse_qs(parsed.query).get("url")
        if target:
            return target[0]
    return url


def parse_feed(text: str, *, media_type: str, expected_domain: str = "", max_items: int = 50) -> list[CollectedItem]:
    feed = feedparser.parse(text)
    if feed.bozo and not feed.entries:
        raise CollectError(f"Không đọc được feed: {feed.bozo_exception.__class__.__name__}")
    items: list[CollectedItem] = []
    for entry in feed.entries[:max_items]:
        link = unwrap_google_redirect(entry.get("link", ""))
        title = strip_html(entry.get("title", "")).strip()
        if not link or not title:
            continue
        if expected_domain and not domain_ok(link, expected_domain):
            # Same check as TrendRadar's expected_domain: drop links that point elsewhere.
            continue
        content = ""
        if entry.get("content"):
            content = strip_html(entry["content"][0].get("value", ""))
        content = content or strip_html(entry.get("summary", ""))
        items.append(
            CollectedItem(
                url=link,
                title=title,
                content=content[:5000],
                author=entry.get("author", "") or "",
                published_at=to_datetime(entry.get("published_parsed") or entry.get("updated_parsed")),
                external_id=entry.get("id", "") or link,
                media_type=media_type,
            )
        )
    return items


def links_from_markdown(markdown: str, base_url: str, link_pattern: str, expected_domain: str = "") -> list[tuple[str, str]]:
    """Find [text](url) links whose path contains link_pattern. Returns unique (title, url)."""
    found: dict[str, str] = {}
    for text, href in re.findall(r"\[([^\]]{6,300})\]\((https?://[^)\s]+|/[^)\s]+)\)", markdown):
        url = urljoin(base_url, href.split(" ")[0])
        if link_pattern and link_pattern not in urlparse(url).path:
            continue
        if expected_domain and not domain_ok(url, expected_domain):
            continue
        title = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text).strip(" *_#")
        if title and url not in found:
            found[url] = title
    return [(title, url) for url, title in found.items()]


class RSSCollector(Collector):
    type = "rss"
    default_backends = ["rss"]

    @property
    def backends(self) -> list[str]:
        configured = self.source.get("backends")
        if configured:
            return list(configured)
        return ["rss", "page"] if self.source.get("page_fallback") else ["rss"]

    def _feeds(self) -> list[str]:
        return list(self.source.get("urls") or ([self.source["url"]] if self.source.get("url") else []))

    def fetch_rss(self) -> list[CollectedItem]:
        urls = self._feeds()
        if not urls:
            raise CollectError("Chưa cấu hình URL RSS")
        errors = []
        items: list[CollectedItem] = []
        for url in urls:
            try:
                text = self.http.get(url).text
                items.extend(
                    parse_feed(
                        text,
                        media_type=self.source.get("media_type", "article"),
                        expected_domain=self.source.get("expected_domain", ""),
                        max_items=self.limit if "limit" in self.source else 50,
                    )
                )
            except CollectError as exc:
                errors.append(f"{url}: {exc}")
        if not items and errors:
            raise CollectError("; ".join(errors))
        return items

    def fetch_page(self) -> list[CollectedItem]:
        page_url = self.source.get("page_fallback") or self.source.get("page_url")
        if not page_url:
            raise CollectError("Chưa cấu hình trang dự phòng")
        _, markdown = self.http.read_page(page_url)
        links = links_from_markdown(
            markdown,
            page_url,
            self.source.get("link_pattern", "/posts/"),
            self.source.get("expected_domain", ""),
        )
        if not links:
            raise CollectError("Không tìm thấy bài nào trên trang")
        return [
            CollectedItem(url=url, title=title, media_type=self.source.get("media_type", "article"))
            for title, url in links[: self.limit if "limit" in self.source else 40]
        ]

    # Community uses the same two paths under different names.
    fetch_jina = fetch_page


class CommunityCollector(RSSCollector):
    type = "community"
    default_backends = ["rss", "jina"]

    @property
    def backends(self) -> list[str]:
        return list(self.source.get("backends") or self.default_backends)

    def fetch_jina(self) -> list[CollectedItem]:
        if "link_pattern" not in self.source:
            self.source = {**self.source, "link_pattern": "/t/"}
        return self.fetch_page()


class GitHubReleasesCollector(Collector):
    type = "github_releases"
    default_backends = ["atom"]

    def fetch_atom(self) -> list[CollectedItem]:
        repos = self.source.get("repos") or []
        if not repos:
            raise CollectError("Chưa cấu hình repo")
        items: list[CollectedItem] = []
        errors = []
        for repo in repos:
            try:
                text = self.http.get(f"https://github.com/{repo}/releases.atom").text
            except CollectError as exc:
                errors.append(f"{repo}: {exc}")
                continue
            for item in parse_feed(text, media_type="release", expected_domain="github.com", max_items=10):
                item.title = f"{repo} {item.title}"
                item.extra["repo"] = repo
                items.append(item)
            self.http.pause(0.5)
        if not items and errors:
            raise CollectError("; ".join(errors))
        return items

