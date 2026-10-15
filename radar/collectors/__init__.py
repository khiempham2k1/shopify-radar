"""Collector registry: source `type` in sources.yaml → collector class."""

from __future__ import annotations

from typing import Any

from radar.collectors.base import (
    CollectedItem,
    CollectError,
    Collector,
    CollectResult,
    Http,
)
from radar.collectors.discord import DiscordCollector
from radar.collectors.editions import EditionsCollector
from radar.collectors.feeds import (
    CommunityCollector,
    GitHubReleasesCollector,
    RSSCollector,
)
from radar.collectors.social import RedditCollector, TwitterCollector, XAccountsCollector, YouTubeCollector
from radar.collectors.web import HackerNewsCollector, WebSearchCollector

REGISTRY: dict[str, type[Collector]] = {
    cls.type: cls
    for cls in (
        RSSCollector,
        CommunityCollector,
        DiscordCollector,
        GitHubReleasesCollector,
        EditionsCollector,
        RedditCollector,
        TwitterCollector,
        XAccountsCollector,
        YouTubeCollector,
        WebSearchCollector,
        HackerNewsCollector,
    )
}


def make_collector(source: dict[str, Any], http: Http | None = None) -> Collector:
    try:
        cls = REGISTRY[source["type"]]
    except KeyError as exc:
        raise ValueError(f"Loại nguồn không hỗ trợ: {source.get('type')}") from exc
    return cls(source, http)


__all__ = ["REGISTRY", "make_collector", "Collector", "CollectedItem", "CollectError", "CollectResult", "Http"]
