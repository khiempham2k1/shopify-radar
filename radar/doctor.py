"""`radar doctor`: check every tool and key the radar depends on.

Follows `agent-reach doctor`: really run each tool (a binary on PATH is not
proof it works) and say how to fix what is broken.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import requests

from radar import ytdlp
from radar.config_loader import RadarConfig
from radar.settings import get_settings


@dataclass
class Check:
    name: str
    status: str  # ok|warn|error|off
    message: str


def _run(args: list[str], timeout: int = 20) -> tuple[int, str]:
    if not shutil.which(args[0]):
        return 127, ""
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return 124, "timeout"
    return proc.returncode, (proc.stdout or proc.stderr).strip()


def check_command(name: str, args: list[str], install: str) -> Check:
    code, output = _run(args)
    if code == 127:
        return Check(name, "error", f"Chưa cài. Cài: {install}")
    if code != 0:
        return Check(name, "error", f"Có cài nhưng chạy lỗi ({code}): {output[-200:]}")
    return Check(name, "ok", output.splitlines()[0][:120] if output else "ok")


def check_login(name: str, args: list[str], login_hint: str) -> Check:
    code, output = _run(args)
    if code == 127:
        return Check(name, "error", "Chưa cài")
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        return Check(name, "warn", f"Không đọc được trạng thái đăng nhập: {output[-200:]}")
    data = payload.get("data") or {}
    if not data.get("authenticated"):
        return Check(name, "warn", f"Chưa đăng nhập hoặc cookie hết hạn. {login_hint}")
    age = credential_age_days(data.get("credential_file"))
    if age is not None and age >= COOKIE_WARN_DAYS:
        return Check(name, "warn", f"Cookie đã dùng {age} ngày, sắp hết hạn. {login_hint}")
    return Check(name, "ok", "Đã đăng nhập" + (f" (cookie {age} ngày)" if age is not None else ""))


COOKIE_WARN_DAYS = 6  # rdt-cli treats saved cookies older than 7 days as stale


def credential_age_days(path: str | None) -> int | None:
    if not path:
        return None
    try:
        return int((time.time() - Path(path).expanduser().stat().st_mtime) // 86400)
    except OSError:
        return None


def login_checks(config: RadarConfig) -> list[Check]:
    """Cookie-based logins the collectors depend on; run on every pipeline run."""
    backends = {b for s in config.sources for b in (s.get("backends") or [])}
    checks = []
    if "rdt-cli" in backends:
        checks.append(check_login("rdt-cli (Reddit)", ["rdt", "status", "--json"], "Chạy `rdt login` hoặc chép credential.json mới của tài khoản radar"))
    if "twitter-cli" in backends:
        checks.append(check_login("twitter-cli (X)", ["twitter", "status", "--json"], "Cập nhật TWITTER_AUTH_TOKEN và TWITTER_CT0 của tài khoản radar"))
    if "discord-cli" in backends:
        checks.append(check_login("discord-cli (Discord)", ["discord", "status", "--json"], "Cập nhật DISCORD_TOKEN của tài khoản Discord riêng cho radar"))
    return checks


def check_http(name: str, url: str, headers: dict[str, str] | None = None) -> Check:
    try:
        response = requests.get(url, headers=headers or {}, timeout=15)
    except requests.RequestException as exc:
        return Check(name, "error", f"Không kết nối được: {exc.__class__.__name__}")
    if response.status_code >= 400:
        return Check(name, "warn", f"HTTP {response.status_code}")
    return Check(name, "ok", f"HTTP {response.status_code}")


def run_doctor(config: RadarConfig, network: bool = False) -> list[Check]:
    settings = get_settings()
    types = {s["type"] for s in config.sources}
    checks: list[Check] = []

    checks.append(Check("Anthropic API key", "ok" if settings.anthropic_api_key else "error", "Đã cấu hình" if settings.anthropic_api_key else "Thiếu ANTHROPIC_API_KEY"))
    if "youtube" in types:
        count = len(settings.groq_api_keys)
        checks.append(
            Check(
                "Groq API key",
                "ok" if count else "warn",
                f"{count} key, dùng xoay vòng" if count else "Thiếu GROQ_API_KEYS: video không có phụ đề sẽ không được nghe",
            )
        )
        checks.append(check_command("yt-dlp", ["yt-dlp", "--version"], 'pip install -U "yt-dlp[default]"'))
        js = shutil.which("deno") or shutil.which("node")
        checks.append(Check("JS runtime cho yt-dlp", "ok" if js else "warn", js or "Cần Node.js hoặc Deno để yt-dlp đọc YouTube"))
        checks.append(check_command("ffmpeg", ["ffmpeg", "-version"], "apt install ffmpeg"))
        cookies = ytdlp.cookie_file()
        checks.append(
            Check(
                "Cookie YouTube",
                "ok",
                f"Có ({cookies}, {credential_age_days(str(cookies))} ngày)"
                if cookies
                else "Chưa có (không bắt buộc; cần khi YouTube đòi xác minh 'not a bot' trên VPS)",
            )
        )
    checks += login_checks(config)

    if network:
        checks.append(check_http("Jina Reader", settings.jina_reader_base + "https://example.com"))
        checks.append(check_http("Hacker News API", "https://hn.algolia.com/api/v1/search?query=shopify&hitsPerPage=1"))
        checks.append(_check_exa())
        for i, key in enumerate(settings.groq_api_keys, start=1):
            checks.append(check_http(f"Groq API key {i} (…{key[-4:]})", "https://api.groq.com/openai/v1/models", {"Authorization": f"Bearer {key}"}))
    return checks


def _check_exa() -> Check:
    from radar.collectors.base import CollectError
    from radar.collectors.exa import exa_search

    try:
        hits = exa_search("shopify theme", num_results=1, timeout=30)
    except CollectError as exc:
        return Check("Exa MCP", "error", str(exc))
    return Check("Exa MCP", "ok" if hits else "warn", f"{len(hits)} kết quả")


LOGIN_STATUS_KEY = "_login_status"


def save_login_status(session, checks: list[Check]) -> None:
    """Store the latest login checks so the Source health page can show them."""
    from radar.models import Setting, utcnow

    value = json.dumps({"checked_at": utcnow().isoformat(), "checks": [asdict(c) for c in checks]}, ensure_ascii=False)
    row = session.get(Setting, LOGIN_STATUS_KEY)
    if row is None:
        session.add(Setting(key=LOGIN_STATUS_KEY, value=value, updated_by="worker"))
    else:
        row.value = value
