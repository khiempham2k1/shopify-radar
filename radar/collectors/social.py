"""Reddit (rdt-cli → Exa), X (twitter-cli) and YouTube (yt-dlp) collectors."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote_plus

from radar.collectors import exa
from radar.collectors.base import (
    CollectedItem,
    CollectError,
    Collector,
    run_cli,
    to_datetime,
)


def reddit_post_to_item(post: dict[str, Any]) -> CollectedItem | None:
    permalink = post.get("permalink") or ""
    url = f"https://www.reddit.com{permalink}" if permalink.startswith("/") else (permalink or post.get("url", ""))
    title = (post.get("title") or "").strip()
    if not url or not title or post.get("over_18") or post.get("stickied"):
        return None
    return CollectedItem(
        url=url,
        title=title,
        content=(post.get("selftext") or "")[:5000],
        author=post.get("author") or "",
        published_at=to_datetime(post.get("created_utc")),
        external_id=post.get("id") or post.get("name") or "",
        media_type="post",
        metrics={"upvotes": int(post.get("score") or 0), "comments": int(post.get("num_comments") or 0)},
        extra={"subreddit": post.get("subreddit", "")},
    )


class RedditCollector(Collector):
    type = "reddit"
    default_backends = ["rdt-cli", "exa"]

    def fetch_rdt_cli(self) -> list[CollectedItem]:
        posts: list[dict[str, Any]] = []
        for sub in self.source.get("subreddits", []):
            data = run_cli(["rdt", "sub", sub, "-s", "new", "-n", str(self.limit), "--compact", "--json"])
            posts.extend(data if isinstance(data, list) else [])
            self.http.pause(1.0)
        for query in self.source.get("queries", []):
            data = run_cli(["rdt", "search", query, "-s", "new", "-t", "week", "-n", str(self.limit), "--compact", "--json"])
            posts.extend(data if isinstance(data, list) else [])
            self.http.pause(1.0)
        items = [i for i in (reddit_post_to_item(p) for p in posts if isinstance(p, dict)) if i]
        if not items and (self.source.get("subreddits") or self.source.get("queries")):
            raise CollectError("rdt-cli không trả về bài nào")
        return items

    def fetch_exa(self) -> list[CollectedItem]:
        """Fallback when the cookie expired: search Reddit through Exa (no metrics)."""
        items: list[CollectedItem] = []
        queries = list(self.source.get("queries", []))
        targets = [f"site:reddit.com/r/{sub} shopify" for sub in self.source.get("subreddits", [])]
        targets += [f"site:reddit.com {q}" for q in queries]
        for query in targets:
            for hit in exa.exa_search(query, num_results=min(self.limit, 10)):
                if "reddit.com" not in hit.url:
                    continue
                items.append(
                    CollectedItem(
                        url=hit.url,
                        title=hit.title,
                        content=hit.text[:5000],
                        author=hit.author,
                        published_at=to_datetime(hit.published),
                        media_type="post",
                        extra={"via": "exa"},
                    )
                )
            self.http.pause(1.0)
        return items


def tweet_to_item(tweet: dict[str, Any]) -> CollectedItem | None:
    author = tweet.get("author") or {}
    handle = author.get("screenName") or ""
    tweet_id = str(tweet.get("id") or "")
    text = (tweet.get("text") or "").strip()
    if not tweet_id or not text:
        return None
    metrics = tweet.get("metrics") or {}
    first_line = text.splitlines()[0]
    return CollectedItem(
        url=f"https://x.com/{handle or 'i'}/status/{tweet_id}",
        title=first_line[:200],
        content=text[:5000],
        author=f"@{handle}" if handle else "",
        published_at=to_datetime(tweet.get("createdAt")),
        external_id=tweet_id,
        media_type="post",
        metrics={
            "likes": int(metrics.get("likes") or 0),
            "retweets": int(metrics.get("retweets") or 0),
            "comments": int(metrics.get("replies") or 0),
            "views": int(metrics.get("views") or 0),
        },
    )


class TwitterCollector(Collector):
    type = "twitter"
    default_backends = ["twitter-cli"]

    def fetch_twitter_cli(self) -> list[CollectedItem]:
        items: list[CollectedItem] = []
        for query in self.source.get("queries", []):
            data = run_cli(["twitter", "search", query, "-t", "latest", "--max", str(self.limit), "--json"])
            items.extend(i for i in (tweet_to_item(t) for t in (data if isinstance(data, list) else [])) if i)
            self.http.pause(2.0)
        return items


def video_entry_to_item(entry: dict[str, Any]) -> CollectedItem | None:
    video_id = entry.get("id")
    title = (entry.get("title") or "").strip()
    if not video_id or not title:
        return None
    return CollectedItem(
        url=f"https://www.youtube.com/watch?v={video_id}",
        title=title,
        content=(entry.get("description") or "")[:3000],
        author=entry.get("channel") or entry.get("uploader") or "",
        published_at=to_datetime(entry.get("timestamp") or entry.get("upload_date")),
        external_id=video_id,
        media_type="video",
        metrics={"views": int(entry.get("view_count") or 0)},
        extra={"duration": int(entry.get("duration") or 0)},
    )


def youtube_search_target(query: str, limit: int, mode: str = "date") -> str:
    """Newest-first uses the results page sorted by upload date (sp=CAI%3D);
    yt-dlp no longer accepts a `ytsearchdate` prefix."""
    if mode == "date":
        return f"https://www.youtube.com/results?search_query={quote_plus(query)}&sp=CAI%253D"
    return f"ytsearch{limit}:{query}"


class YouTubeCollector(Collector):
    type = "youtube"
    default_backends = ["yt-dlp"]

    def fetch_yt_dlp(self) -> list[CollectedItem]:
        import yt_dlp

        options = {"quiet": True, "no_warnings": True, "js_runtimes": {"deno": {}, "node": {}}, "skip_download": True, "extract_flat": "in_playlist", "playlistend": self.limit}
        items: list[CollectedItem] = []
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                for query in self.source.get("queries", []):
                    info = ydl.extract_info(youtube_search_target(query, self.limit, self.source.get("search_mode", "date")), download=False) or {}
                    items.extend(i for i in (video_entry_to_item(e) for e in info.get("entries") or [] if e) if i)
                    self.http.pause(1.0)
        except (yt_dlp.utils.DownloadError, yt_dlp.networking.exceptions.RequestError) as exc:
            raise CollectError(str(exc)) from exc
        return items
