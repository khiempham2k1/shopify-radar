"""Collector building blocks.

Each source lists its backends in order of preference (the Agent Reach model):
the collector tries them one by one and reports which one actually served the
run. Using a fallback backend marks the run as `warn` so the Source health page
shows it.
"""

from __future__ import annotations

import json
import logging
import random
import re
import shutil
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import requests

from radar.settings import get_settings

log = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (compatible; ShopifyRadar/0.1; internal use)"


class CollectError(RuntimeError):
    """A backend could not produce items. The message is shown on the health page."""


@dataclass
class CollectedItem:
    url: str
    title: str
    content: str = ""
    author: str = ""
    published_at: datetime | None = None
    external_id: str = ""
    media_type: str = "post"
    metrics: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class CollectResult:
    items: list[CollectedItem]
    status: str  # ok|warn|error
    backend: str
    message: str = ""


def strip_html(text: str) -> str:
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text or "", flags=re.S | re.I)
    text = re.sub(r"<br\s*/?>|</p>|</li>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
    )
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n\n", text)).strip()


def domain_ok(url: str, expected_domain: str) -> bool:
    """HTTPS and host equal to or under expected_domain (hostname parsed, so user@host tricks fail)."""
    if not expected_domain:
        return True
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    expected = expected_domain.lower().strip()
    return parsed.scheme == "https" and (host == expected or host.endswith("." + expected))


def to_datetime(value: Any) -> datetime | None:
    if value in (None, "", 0):
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        if isinstance(value, time.struct_time):
            return datetime(*value[:6], tzinfo=timezone.utc)
        text = str(value).strip()
        if re.fullmatch(r"\d{8}", text):  # yt-dlp upload_date
            return datetime.strptime(text, "%Y%m%d").replace(tzinfo=timezone.utc)
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, OverflowError, TypeError):
        pass
    try:
        from email.utils import parsedate_to_datetime

        return parsedate_to_datetime(str(value))
    except (TypeError, ValueError):
        return None


class Http:
    """requests wrapper with retries, jittered backoff and Jina Reader access."""

    def __init__(self, retries: int = 3, base_delay: float = 1.5, sleep: Callable[[float], None] = time.sleep) -> None:
        settings = get_settings()
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        if settings.http_proxy:
            self.session.proxies = {"http": settings.http_proxy, "https": settings.http_proxy}
        self.timeout = settings.request_timeout
        self.retries = retries
        self.base_delay = base_delay
        self.sleep = sleep
        self.jina_base = settings.jina_reader_base

    def get(self, url: str, **kwargs: Any) -> requests.Response:
        last: Exception | None = None
        timeout = kwargs.pop("timeout", self.timeout)
        for attempt in range(self.retries):
            try:
                response = self.session.get(url, timeout=timeout, **kwargs)
                if response.status_code in (429, 500, 502, 503, 504):
                    last = CollectError(f"HTTP {response.status_code} từ {urlparse(url).hostname}")
                else:
                    if response.status_code >= 400:
                        raise CollectError(f"HTTP {response.status_code} từ {urlparse(url).hostname}")
                    return response
            except requests.RequestException as exc:
                last = CollectError(f"Không kết nối được {urlparse(url).hostname}: {exc.__class__.__name__}")
            if attempt < self.retries - 1:
                self.sleep(self.base_delay * (2**attempt) + random.uniform(0, 1))
        raise last or CollectError(f"Không tải được {url}")

    def get_json(self, url: str, **kwargs: Any) -> Any:
        return self.get(url, **kwargs).json()

    def read_page(self, url: str) -> tuple[str, str]:
        """Read a page as markdown through Jina Reader. Returns (title, markdown)."""
        body = self.get(self.jina_base + url, headers={"Accept": "text/plain"}, timeout=60).text
        sample = body[:4096].lower()
        if "requiring captcha" in sample or "title: just a moment..." in sample:
            raise CollectError("Jina Reader trả về trang chống bot, không có nội dung")
        title_match = re.search(r"^Title:\s*(.+)$", body, flags=re.M)
        marker = body.find("Markdown Content:")
        content = body[marker + len("Markdown Content:") :].strip() if marker >= 0 else body
        return (title_match.group(1).strip() if title_match else ""), content

    def pause(self, seconds: float = 1.0) -> None:
        self.sleep(seconds + random.uniform(0, seconds))


def run_cli(args: list[str], timeout: int = 120) -> Any:
    """Run an Agent Reach-style CLI that prints the {ok, data, error} JSON envelope."""
    if not shutil.which(args[0]):
        raise CollectError(f"Chưa cài {args[0]}")
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise CollectError(f"{args[0]} chạy quá {timeout}s") from exc
    output = proc.stdout.strip()
    try:
        payload = json.loads(output) if output else {}
    except json.JSONDecodeError as exc:
        detail = (proc.stderr or output)[-300:]
        raise CollectError(f"{args[0]} trả về dữ liệu không đọc được: {detail}") from exc
    if isinstance(payload, dict) and payload.get("ok") is False:
        error = payload.get("error") or {}
        raise CollectError(f"{args[0]}: {error.get('code', 'error')} – {error.get('message', '')}".strip())
    if proc.returncode != 0 and not payload:
        raise CollectError(f"{args[0]} lỗi (mã {proc.returncode}): {(proc.stderr or '')[-300:]}")
    return payload.get("data", payload) if isinstance(payload, dict) else payload


class Collector:
    """Base class. Subclasses implement fetch_<backend> methods."""

    type = ""
    default_backends: list[str] = []

    def __init__(self, source: dict[str, Any], http: Http | None = None) -> None:
        self.source = source
        self.http = http or Http()

    @property
    def backends(self) -> list[str]:
        return list(self.source.get("backends") or self.default_backends)

    @property
    def limit(self) -> int:
        return int(self.source.get("limit", 25))

    def collect(self) -> CollectResult:
        errors: list[str] = []
        for index, backend in enumerate(self.backends):
            fetch = getattr(self, "fetch_" + backend.replace("-", "_"), None)
            if fetch is None:
                errors.append(f"{backend}: không hỗ trợ")
                continue
            try:
                items = fetch()
            except CollectError as exc:
                errors.append(f"{backend}: {exc}")
                continue
            except Exception as exc:  # noqa: BLE001 - a broken backend must not stop the run
                log.exception("Collector %s backend %s failed", self.source.get("id"), backend)
                errors.append(f"{backend}: {exc.__class__.__name__}: {exc}")
                continue
            status = "ok" if index == 0 else "warn"
            message = "; ".join(errors) if errors else ""
            if index > 0:
                message = f"Đang dùng dự phòng {backend}. " + message
            return CollectResult(items=items, status=status, backend=backend, message=message)
        return CollectResult(items=[], status="error", backend="", message="; ".join(errors) or "Không có backend nào")
