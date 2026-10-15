"""Runtime settings read from environment variables.

Everything that differs between machines (database, keys, paths) lives here.
Everything the team edits (sources, keywords, interests, prompts) lives in config/.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_dotenv(path: Path) -> None:
    """Read KEY=VALUE lines from `path` into os.environ for keys not already set.

    Lets `radar ...` and `uvicorn api.main:app` run locally with the same .env
    docker compose uses. Real environment variables always win.
    """
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.removeprefix("export ").split("=", 1)
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


load_dotenv(Path(os.environ.get("RADAR_ENV_FILE", str(ROOT / ".env"))))


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_int(name: str, default: int) -> int:
    value = _env(name)
    return int(value) if value else default


def _groq_keys() -> tuple[str, ...]:
    raw = _env("GROQ_API_KEYS").replace("\n", ",").split(",") + [_env("GROQ_API_KEY")]
    return tuple(dict.fromkeys(k.strip() for k in raw if k.strip()))


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=lambda: _env("DATABASE_URL", f"sqlite:///{ROOT / '.data' / 'radar.db'}"))
    config_dir: Path = field(default_factory=lambda: Path(_env("RADAR_CONFIG_DIR", str(ROOT / "config"))))
    work_dir: Path = field(default_factory=lambda: Path(_env("RADAR_WORK_DIR", str(ROOT / ".data" / "work"))))
    timezone: str = field(default_factory=lambda: _env("RADAR_TIMEZONE", "Asia/Ho_Chi_Minh"))

    # API auth: the Next.js server calls the API with this bearer token and
    # forwards the signed-in user's email in X-Radar-User.
    api_token: str = field(default_factory=lambda: _env("RADAR_API_TOKEN"))

    anthropic_api_key: str = field(default_factory=lambda: _env("ANTHROPIC_API_KEY"))
    # Groq keys for speech-to-text, used as a pool: GROQ_API_KEYS (comma or newline
    # separated) plus the single GROQ_API_KEY. A rate-limited key rests while the next one works.
    groq_api_keys: tuple[str, ...] = field(default_factory=lambda: _groq_keys())

    # Free collection endpoints (see docs/PLAN.md, "Dùng Agent Reach").
    jina_reader_base: str = field(default_factory=lambda: _env("JINA_READER_BASE", "https://r.jina.ai/"))
    exa_mcp_url: str = field(default_factory=lambda: _env("EXA_MCP_URL", "https://mcp.exa.ai/mcp"))
    http_proxy: str = field(default_factory=lambda: _env("RADAR_HTTP_PROXY"))

    request_timeout: int = field(default_factory=lambda: _env_int("RADAR_REQUEST_TIMEOUT", 30))

    @property
    def groq_api_key(self) -> str:
        """First key of the pool, for callers that need just one (doctor, checks)."""
        return self.groq_api_keys[0] if self.groq_api_keys else ""


def get_settings() -> Settings:
    return Settings()
