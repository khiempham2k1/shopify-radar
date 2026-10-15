"""Web search (Exa MCP + Jina Reader) and Hacker News (Algolia API)."""

from __future__ import annotations

import time
from urllib.parse import quote_plus

from radar.collectors import exa
from radar.collectors.base import CollectedItem, CollectError, Collector, to_datetime


class WebSearchCollector(Collector):
    type = "web_search"
    default_backends = ["exa"]

    def fetch_exa(self) -> list[CollectedItem]:
        items: list[CollectedItem] = []
        seen: set[str] = set()
        for query in self.source.get("queries", []):
            for hit in exa.exa_search(query, num_results=self.limit):
                if hit.url in seen:
                    continue
                seen.add(hit.url)
                items.append(
                    CollectedItem(
                        url=hit.url,
                        title=hit.title,
                        content=hit.text[:5000],
                        author=hit.author,
                        published_at=to_datetime(hit.published),
                        media_type="article",
                        extra={"query": query},
                    )
                )
            self.http.pause(1.0)
        return items

    def enrich(self, item: CollectedItem) -> None:
        """Read the full page through Jina Reader when Exa only gave a snippet."""
        if not self.source.get("read_full") or len(item.content) >= 1500:
            return
        try:
            _, markdown = self.http.read_page(item.url)
        except CollectError:
            return
        item.content = markdown[:5000]


class HackerNewsCollector(Collector):
    type = "hackernews"
    default_backends = ["algolia"]

    def fetch_algolia(self) -> list[CollectedItem]:
        items: list[CollectedItem] = []
        since = ""
        if int(self.source.get("max_age_days") or 0) > 0:
            cutoff = int(time.time()) - int(self.source["max_age_days"]) * 86400
            since = f"&numericFilters=created_at_i>{cutoff}"
        for query in self.source.get("queries", ["shopify"]):
            data = self.http.get_json(
                f"https://hn.algolia.com/api/v1/search_by_date?query={quote_plus(query)}&tags=story&hitsPerPage={self.limit}{since}"
            )
            for hit in data.get("hits", []):
                object_id = hit.get("objectID")
                title = (hit.get("title") or "").strip()
                if not object_id or not title:
                    continue
                items.append(
                    CollectedItem(
                        url=f"https://news.ycombinator.com/item?id={object_id}",
                        title=title,
                        content=(hit.get("story_text") or "")[:5000],
                        author=hit.get("author") or "",
                        published_at=to_datetime(hit.get("created_at_i") or hit.get("created_at")),
                        external_id=str(object_id),
                        media_type="post",
                        metrics={"points": int(hit.get("points") or 0), "comments": int(hit.get("num_comments") or 0)},
                        extra={"link": hit.get("url") or ""},
                    )
                )
        return items
