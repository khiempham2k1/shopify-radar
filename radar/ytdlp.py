"""Shared yt-dlp options: the radar's YouTube cookies and proxy.

From a datacenter IP (a VPS) YouTube often answers "Sign in to confirm you're
not a bot". Two ways around it, both optional:

- YOUTUBE_COOKIES: a cookies.txt (Netscape format) exported from a YouTube
  session of the radar's own Google account (default secrets/youtube/cookies.txt);
- RADAR_HTTP_PROXY: a proxy (residential) for every request, yt-dlp included.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from radar.settings import get_settings

BASE = {"quiet": True, "no_warnings": True, "no_color": True, "js_runtimes": {"deno": {}, "node": {}}}


def cookie_file() -> Path | None:
    path = get_settings().youtube_cookies
    return path if path.is_file() and path.stat().st_size > 0 else None


def options(**extra: Any) -> dict[str, Any]:
    opts: dict[str, Any] = {**BASE, **extra}
    cookies = cookie_file()
    if cookies:
        opts["cookiefile"] = str(cookies)  # yt-dlp also writes refreshed cookies back here
    proxy = get_settings().http_proxy
    if proxy:
        opts["proxy"] = proxy
    return opts


BOT_CHECK = "confirm you’re not a bot", "confirm you're not a bot"


def explain(message: str) -> str:
    """Add what to do when YouTube refuses the server's IP."""
    if any(m in message for m in BOT_CHECK):
        if cookie_file():
            return message + " — cookie YouTube có thể đã hết hạn: xuất lại cookies.txt của tài khoản radar"
        return message + " — YouTube chặn IP server: thêm cookie YouTube (secrets/youtube/cookies.txt) hoặc đặt RADAR_HTTP_PROXY"
    return message
