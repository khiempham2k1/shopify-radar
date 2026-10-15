"""Keys that say "this is the same post" across accounts, runs and sources.

Every stored item gets at least one key: its own URL, normalized. Sources that
mostly repost announcements (the official Shopify accounts on X) also opt in to
keys for the links they share and for their text, so a tweet that only points
at a changelog entry the radar already has is attached to that entry instead
of becoming a second row. Keys are stored hashed in item_keys.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

TRACKING = re.compile(r"^(utm_\w+|ref|ref_src|ref_url|source|s|t|si|fbclid|gclid|mc_cid|mc_eid)$", re.I)
TWEET = re.compile(r"^/(?:[\w]+|i(?:/web)?)/status(?:es)?/(\d+)")
X_HOSTS = {"x.com", "twitter.com", "mobile.twitter.com", "mobile.x.com"}


def normalize_url(url: str) -> str:
    """Same page, same string: lower-case host without www, no tracking parameters,
    no trailing slash. Fragments stay (Editions features differ only by #anchor).
    Tweets become x:<id> whichever account or host the link uses."""
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return url.strip()
    host = (parsed.hostname or "").lower().removeprefix("www.")
    if host in X_HOSTS:
        match = TWEET.match(parsed.path)
        if match:
            return f"x:{match.group(1)}"
    query = urlencode([(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if not TRACKING.match(k)])
    path = parsed.path.rstrip("/") or "/"
    return urlunparse(("https", host, path, "", query, parsed.fragment))


def normalize_text(text: str) -> str:
    text = re.sub(r"https?://\S+", " ", text or "")
    text = re.sub(r"^(rt\s+)?@\w+:?\s*", " ", text.strip(), flags=re.I)
    return " ".join(re.findall(r"\w+", text.lower()))


def specific(key: str) -> bool:
    """A shared link identifies one post only when it points at a specific page: a tweet,
    a path with two or more parts (shopify.dev/changelog/<entry>) or a page with a query
    (youtube.com/watch?v=…). Home pages and sections (shopify.com, shopify.dev/docs) are
    linked by many unrelated posts and must not merge them."""
    if key.startswith("x:"):
        return True
    parsed = urlparse(key)
    parts = [p for p in parsed.path.split("/") if p]
    return len(parts) >= 2 or (len(parts) >= 1 and bool(parsed.query))


def item_keys(url: str, extra: dict[str, Any] | None, title: str = "", content: str = "", source_config: dict[str, Any] | None = None) -> list[str]:
    """Readable keys for one item, most specific first."""
    extra = extra or {}
    config = source_config or {}
    keys = [normalize_url(url)]
    keys += [str(k) for k in extra.get("dedupe_keys") or []]
    if config.get("dedupe_links"):
        keys += [k for k in (normalize_url(link) for link in extra.get("links") or [] if link) if specific(k)]
    if config.get("dedupe_text"):
        text = normalize_text(extra.get("text") or content or title)  # the post's own words, without appended links
        if len(text) >= 40:  # short texts ("Big news!") are too generic to merge on
            keys.append("text:" + text[:300])
    return list(dict.fromkeys(k for k in keys if k))


def hashed(keys: Iterable[str]) -> list[str]:
    return [hashlib.sha1(k.encode("utf-8")).hexdigest() for k in dict.fromkeys(keys)]
