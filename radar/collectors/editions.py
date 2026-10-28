"""Shopify Editions: find the newest Edition and split it into one item per feature."""

from __future__ import annotations

import re
from urllib.parse import urljoin

from radar.collectors.base import CollectedItem, CollectError, Collector

EDITION_LINK = re.compile(r"https?://www\.shopify\.com/editions/(winter|spring|summer|fall)(\d{4})\b[^)\s\"]*|/editions/(winter|spring|summer|fall)(\d{4})\b")


SEASON_ORDER = {"winter": 1, "spring": 2, "summer": 3, "fall": 4}


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:80]


def edition_name(season: str, year: str) -> str:
    return f"{season.capitalize()} '{year[-2:]}"


def find_editions(markdown: str) -> list[tuple[str, str]]:
    """Return [(name, url)] newest first, deduplicated."""
    seen: dict[str, tuple[int, str]] = {}
    for match in EDITION_LINK.finditer(markdown):
        season = match.group(1) or match.group(3)
        year = match.group(2) or match.group(4)
        url = f"https://www.shopify.com/editions/{season}{year}"
        # Within one year label: Winter (Dec) < Spring < Summer < Fall. Shopify renamed Summer to
        # Spring/Fall in 2026, so all four seasons must be recognised or the newest Edition is missed.
        order = int(year) * 10 + SEASON_ORDER[season]
        seen.setdefault(url, (order, edition_name(season, year)))
    ranked = sorted(seen.items(), key=lambda kv: kv[1][0], reverse=True)
    return [(name, url) for url, (_, name) in ranked]


def split_features(markdown: str, edition: str, edition_url: str, max_items: int = 200) -> list[CollectedItem]:
    """Every ##/### heading with some body text becomes one feature item."""
    items: list[CollectedItem] = []
    parts = re.split(r"^(#{2,4})\s+(.+?)\s*#*\s*$", markdown, flags=re.M)
    # parts = [preamble, hashes, heading, body, hashes, heading, body, ...]
    section = ""
    for i in range(1, len(parts) - 2, 3):
        level, heading, body = len(parts[i]), parts[i + 1].strip(), parts[i + 2].strip()
        heading = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", heading).strip(" *_")
        body = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", body).strip()
        if level == 2:
            section = heading
        if not heading or len(body) < 40:
            continue
        items.append(
            CollectedItem(
                url=f"{edition_url}#{slugify(heading)}",
                title=f"{edition}: {heading}",
                content=body[:3000],
                media_type="change",
                external_id=f"{edition}:{slugify(heading)}",
                extra={"edition": edition, "section": section},
            )
        )
        if len(items) >= max_items:
            break
    return items


class EditionsCollector(Collector):
    type = "editions"
    default_backends = ["jina"]

    def fetch_jina(self) -> list[CollectedItem]:
        index_url = self.source.get("url", "https://www.shopify.com/editions")
        _, index_md = self.http.read_page(index_url)
        editions = find_editions(index_md)
        if not editions:
            raise CollectError("Không tìm thấy Edition nào trên trang Editions")
        name, url = editions[0]
        self.http.pause(1.0)
        _, edition_md = self.http.read_page(urljoin(index_url, url))
        items = split_features(edition_md, name, url)
        if not items:
            raise CollectError(f"Không tách được tính năng nào từ {name}")
        return items
