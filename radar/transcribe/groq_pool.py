"""A pool of Groq API keys for speech-to-text.

Groq's free tier limits audio per key (per minute, hour and day). With several
keys the radar uses them in turn; a key that answers 429 rests for as long as
Groq says (retry-after, or "try again in 7m12s" in the message), one that
answers 401/403 rests for a day, and the chunk is sent again with the next key.
When every key is resting the video goes back to the queue for a later run.

The resting state is kept in the settings table under _groq_pool, keyed by a
hash of each key, so the next run does not hammer a key that is still limited.
Keys themselves are never stored.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

STATE_KEY = "_groq_pool"
DEFAULT_REST = timedelta(seconds=60)
INVALID_REST = timedelta(hours=24)


class GroqKeysExhausted(RuntimeError):
    """Every key is resting. `until` is when the first one is free again."""

    def __init__(self, until: datetime) -> None:
        super().__init__(f"Mọi Groq key đang bị giới hạn tới {until.astimezone(timezone.utc):%H:%M} UTC")
        self.until = until


def fingerprint(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def rest_from_response(headers: Any, body: str) -> timedelta:
    """How long Groq asks us to wait: the retry-after header, or the longer wait in the
    message ("Please try again in 1h2m7.5s" for daily audio limits)."""
    waits = [DEFAULT_REST]
    try:
        retry_after = float(str((headers or {}).get("retry-after", "")).rstrip("s") or "nan")
        if retry_after == retry_after:  # not NaN
            waits.append(timedelta(seconds=retry_after))
    except ValueError:
        pass
    match = re.search(r"try again in\s+((?:\d+h)?(?:\d+m)?(?:[\d.]+s)?)", body or "", re.I)
    if match and match.group(1):
        parts = {unit: float(value) for value, unit in re.findall(r"([\d.]+)([hms])", match.group(1))}
        waits.append(timedelta(hours=parts.get("h", 0), minutes=parts.get("m", 0), seconds=parts.get("s", 0)))
    return max(waits)


@dataclass
class GroqKeyPool:
    keys: list[str]
    session: Session | None = None
    now: Any = field(default=lambda: datetime.now(timezone.utc))
    state: dict[str, dict[str, Any]] = field(default_factory=dict)
    cursor: int = 0

    def __post_init__(self) -> None:
        self.keys = list(dict.fromkeys(k for k in self.keys if k))
        if self.session is not None:
            from radar.models import Setting

            row = self.session.get(Setting, STATE_KEY)
            if row is not None:
                data = json.loads(row.value or "{}")
                self.state = data.get("keys", {})
                self.cursor = int(data.get("cursor", 0))

    def __bool__(self) -> bool:
        return bool(self.keys)

    def _resting_until(self, key: str) -> datetime | None:
        entry = self.state.get(fingerprint(key)) or {}
        until = entry.get("until")
        if not until:
            return None
        moment = datetime.fromisoformat(until)
        return moment if moment > self.now() else None

    def acquire(self) -> str:
        """Next free key, round robin so the load spreads across keys."""
        if not self.keys:
            raise GroqKeysExhausted(self.now())
        for step in range(len(self.keys)):
            index = (self.cursor + step) % len(self.keys)
            key = self.keys[index]
            if self._resting_until(key) is None:
                self.cursor = (index + 1) % len(self.keys)
                return key
        raise GroqKeysExhausted(min(self._resting_until(k) or self.now() for k in self.keys))

    def rest(self, key: str, duration: timedelta, reason: str) -> None:
        self.state[fingerprint(key)] = {"until": (self.now() + duration).isoformat(), "reason": reason[:200]}
        self.save()

    def ok(self, key: str) -> None:
        if self.state.pop(fingerprint(key), None) is not None:
            self.save()

    def status(self) -> list[dict[str, Any]]:
        """For the admin health view: which keys work and which rest (keys shown by their last 4 chars)."""
        out = []
        for i, key in enumerate(self.keys, start=1):
            until = self._resting_until(key)
            entry = self.state.get(fingerprint(key)) or {}
            out.append(
                {
                    "name": f"Key {i} · …{key[-4:]}",
                    "status": "resting" if until else "ok",
                    "until": until.isoformat() if until else None,
                    "reason": entry.get("reason", "") if until else "",
                }
            )
        return out

    def save(self) -> None:
        if self.session is None:
            return
        from radar.models import Setting

        known = {fingerprint(k) for k in self.keys}
        value = json.dumps({"cursor": self.cursor, "keys": {f: v for f, v in self.state.items() if f in known}})
        row = self.session.get(Setting, STATE_KEY)
        if row is None:
            self.session.add(Setting(key=STATE_KEY, value=value, updated_by="radar"))
        else:
            row.value = value
        self.session.flush()
