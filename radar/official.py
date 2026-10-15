"""Which items come from Shopify itself.

Official means: every platform source (changelogs, Editions, Shopify's GitHub
releases, the official X accounts), plus anything found elsewhere whose page
lives on a Shopify domain (shopify.dev, help.shopify.com, shopify.engineering…),
listed under `official` in sources.yaml. The Community forum is Shopify's site
but merchants write it, so it is excluded.

Official items are collected first, win when the same story is stored twice,
rank first and are the reference Claude reads other sources against.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

DEFAULT_DOMAINS = [
    "shopify.dev",
    "shopify.com",
    "shopify.engineering",
    "shopifystatus.com",
    "github.com/Shopify",
]
DEFAULT_EXCLUDE = ["community.shopify.com", "apps.shopify.com"]


def _matches(url: str, entry: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    domain, _, path = entry.lower().partition("/")
    if host != domain and not host.endswith("." + domain):
        return False
    return not path or parsed.path.lower().strip("/").split("/")[0] == path.lower()


def is_official(url: str, source: dict[str, Any] | None, settings: dict[str, Any] | None = None) -> bool:
    source = source or {}
    if "official" in source:  # a source can say so explicitly either way
        return bool(source["official"])
    if source.get("kind") == "platform":
        return True
    settings = settings or {}
    if any(_matches(url, e) for e in settings.get("exclude", DEFAULT_EXCLUDE)):
        return False
    return any(_matches(url, d) for d in settings.get("domains", DEFAULT_DOMAINS))


def official_first(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collection order: official sources before the rest, otherwise as listed."""
    return sorted(sources, key=lambda s: 0 if is_official("", s) else 1)
