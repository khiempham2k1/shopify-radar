"""Discord channels, read with the radar's own account.

The account joins the public community server like any member, and its token
(DISCORD_TOKEN) reads the channels through Discord's REST API — the same calls
discord-cli (jackwener/discord-cli) makes, done here so the whole message is
kept: attachments (images, files), link previews (embeds), reactions and the
message replied to. discord-cli only keeps the text plus "[attachment: x.png]",
so it stays as the fallback backend. This is user-token automation, which
Discord's terms do not allow and may punish by closing the account, so: a
dedicated account, read only, a few channels, every two hours.

Messages are not classified one by one: the community page sums them up in a
Vietnamese digest (radar/ai/community.py).
"""

from __future__ import annotations

import json
import os
import re
from datetime import timedelta
from typing import Any

from radar.collectors.base import (
    CollectedItem,
    CollectError,
    Collector,
    run_cli,
    to_datetime,
)
from radar.models import utcnow

SYSTEM_TYPES = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 14, 15, 16, 17, 18}  # joins, pins, boosts…
API_BASE = "https://discord.com/api/v10"
DISCORD_EPOCH_MS = 1420070400000
# A browser's headers, as discord-cli sends them: the token belongs to a normal user account.
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
    "sec-ch-ua": '"Chromium";v="133", "Not(A:Brand";v="99", "Google Chrome";v="133"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
}


CHANNEL_LINK = re.compile(r"discord(?:app)?\.com/channels/(\d+|@me)/(\d+)")


def channel_entry(entry: Any) -> dict[str, str]:
    """A channel from sources.yaml: an ID, a channel link copied from Discord
    (https://discord.com/channels/<server>/<channel>), or {id|url, name}."""
    if isinstance(entry, dict):
        raw, name = str(entry.get("url") or entry.get("id") or ""), str(entry.get("name") or "")
    else:
        raw, name = str(entry or ""), ""
    match = CHANNEL_LINK.search(raw)
    channel_id = match.group(2) if match else raw.strip()
    return {"id": channel_id if channel_id.isdigit() else "", "name": name}


def snowflake_at(hours_ago: float) -> str:
    """Discord message id of that moment, for `after=` paging."""
    ms = int((utcnow() - timedelta(hours=hours_ago)).timestamp() * 1000) - DISCORD_EPOCH_MS
    return str(ms << 22)


def _attachments(msg: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for att in msg.get("attachments") or []:
        if not att.get("url"):
            continue
        out.append(
            {
                "name": att.get("filename") or "file",
                "url": att["url"],
                "type": att.get("content_type") or "",
                "width": att.get("width"),
                "height": att.get("height"),
            }
        )
    return out


def _embeds(msg: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for emb in msg.get("embeds") or []:
        title, url = emb.get("title") or "", emb.get("url") or ""
        description = (emb.get("description") or "").strip()
        if not (title or url or description):
            continue
        image = (emb.get("thumbnail") or emb.get("image") or {}).get("url") or ""
        out.append(
            {
                "title": title[:300],
                "description": description[:600],
                "url": url,
                "site": (emb.get("provider") or {}).get("name") or (emb.get("author") or {}).get("name") or "",
                "image": image,
                "kind": emb.get("type") or "",
            }
        )
    return out


def is_image(attachment: dict[str, Any]) -> bool:
    name = attachment.get("name", "").lower()
    return attachment.get("type", "").startswith("image/") or name.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp"))


def describe_extras(text: str, attachments: list[dict[str, Any]], embeds: list[dict[str, Any]]) -> str:
    """The message as Claude reads it: text, then what was attached or linked."""
    lines = [text] if text else []
    for att in attachments:
        lines.append(f"[{'Ảnh' if is_image(att) else 'Tệp'}: {att['name']}]")
    for emb in embeds:
        parts = [p for p in (emb["site"], emb["title"], emb["description"][:300], emb["url"]) if p]
        lines.append("[Link: " + " — ".join(parts) + "]")
    return "\n".join(lines)


def raw_message_to_item(msg: dict[str, Any], guild_id: str = "", channel_name: str = "", guild_name: str = "") -> CollectedItem | None:
    """A message object as Discord's API returns it."""
    author = msg.get("author") or {}
    if msg.get("type") in SYSTEM_TYPES or author.get("bot"):
        return None
    channel = str(msg.get("channel_id") or "")
    msg_id = str(msg.get("id") or "")
    if not channel or not msg_id:
        return None
    text = (msg.get("content") or "").strip()
    attachments, embeds = _attachments(msg), _embeds(msg)
    if not (text or attachments or embeds):
        return None
    content = describe_extras(text, attachments, embeds)
    reactions = sum(int(r.get("count") or 0) for r in msg.get("reactions") or [])
    referenced = msg.get("referenced_message") or {}
    reply_to = (msg.get("message_reference") or {}).get("message_id") or referenced.get("id") or ""
    guild = guild_id or msg.get("guild_id") or "@me"
    first_line = (text.splitlines()[0] if text else "") or (attachments[0]["name"] if attachments else embeds[0]["title"] or embeds[0]["url"])
    extra: dict[str, Any] = {"channel": channel_name or channel, "channel_id": channel, "guild": guild_name, "reply_to": reply_to}
    if attachments:
        extra["attachments"] = attachments
    if embeds:
        extra["embeds"] = embeds
    if referenced:
        ref_author = referenced.get("author") or {}
        extra["reply_author"] = ref_author.get("global_name") or ref_author.get("username") or ""
        extra["reply_text"] = (referenced.get("content") or "").strip()[:300]
    return CollectedItem(
        url=f"https://discord.com/channels/{guild}/{channel}/{msg_id}",
        title=first_line[:160],
        content=content[:4000],
        author=author.get("global_name") or author.get("username") or "",
        published_at=to_datetime(msg.get("timestamp")),
        external_id=msg_id,
        media_type="message",
        metrics={"likes": reactions} if reactions else {},
        extra=extra,
    )


def message_to_item(row: dict[str, Any], channel_name: str = "") -> CollectedItem | None:
    """A row from discord-cli's store (text only; raw_json when it has one)."""
    try:
        raw = json.loads(row.get("raw_json") or "{}")
    except (TypeError, json.JSONDecodeError):
        raw = {}
    msg = {
        **raw,
        "id": str(row.get("msg_id") or raw.get("id") or ""),
        "channel_id": row.get("channel_id") or raw.get("channel_id") or "",
        "content": row.get("content") or "",
        "timestamp": row.get("timestamp") or raw.get("timestamp"),
        "author": {"username": row.get("sender_name") or "", **(raw.get("author") or {})},
        "attachments": [],  # discord-cli already wrote them into the text as "[attachment: x]"
        "embeds": [],
    }
    return raw_message_to_item(msg, row.get("guild_id") or raw.get("guild_id") or "", row.get("channel_name") or channel_name, row.get("guild_name") or "")


class DiscordCollector(Collector):
    type = "discord"
    default_backends = ["discord-api", "discord-cli"]

    @property
    def backends(self) -> list[str]:
        """The API first even where sources.yaml lists only discord-cli: it keeps attachments and link previews."""
        listed = list(self.source.get("backends") or self.default_backends)
        return listed if "discord-api" in listed else ["discord-api", *listed]

    def _channels(self) -> list[dict[str, str]]:
        channels = [c for c in map(channel_entry, self.source.get("channels") or []) if c["id"]]
        if not channels:
            raise CollectError("Chưa khai báo kênh Discord (channels trong sources.yaml)")
        return channels

    def _api(self, path: str, token: str, **params: Any) -> Any:
        return self.http.get_json(API_BASE + path, headers={**BROWSER_HEADERS, "Authorization": token}, params=params)

    def fetch_discord_api(self) -> list[CollectedItem]:
        token = os.environ.get("DISCORD_TOKEN", "").strip()
        if not token:
            raise CollectError("Chưa có DISCORD_TOKEN")
        channels = self._channels()
        hours = int(self.source.get("hours", 26))  # a little over a day, so nothing falls between two digests
        items: list[CollectedItem] = []
        errors: list[str] = []
        for channel in channels:
            channel_id, name = channel["id"], channel.get("name", "")
            try:
                info = self._api(f"/channels/{channel_id}", token)
                guild_id = str(info.get("guild_id") or "")
                name = info.get("name") or name or channel_id  # the channel's real name; sources.yaml's only as fallback
                after, fetched = snowflake_at(hours), 0
                while fetched < self.limit * 2:
                    batch = self._api(f"/channels/{channel_id}/messages", token, limit=100, after=after)
                    if not batch:
                        break
                    fetched += len(batch)
                    items.extend(i for i in (raw_message_to_item(m, guild_id, name) for m in batch if isinstance(m, dict)) if i)
                    after = str(max(int(m["id"]) for m in batch))
                    if len(batch) < 100:
                        break
                    self.http.pause(1.0)
            except CollectError as exc:
                errors.append(f"#{name or channel_id}: {exc}")
                continue
            self.http.pause(3.0)  # unhurried, like a person reading
        if errors and not items:
            raise CollectError("; ".join(errors))
        return items

    def fetch_discord_cli(self) -> list[CollectedItem]:
        channels = self._channels()
        hours = int(self.source.get("hours", 26))  # a little over a day, so nothing falls between two digests
        items: list[CollectedItem] = []
        errors: list[str] = []
        for channel in channels:
            channel_id, name = str(channel["id"]), channel.get("name", "")
            try:
                args = ["discord", "dc", "sync", channel_id, "-n", str(self.limit), "--json"]
                run_cli(args, timeout=300)
                rows = run_cli(["discord", "recent", "-c", channel_id, "--hours", str(hours), "-n", str(self.limit * 2), "--json"])
            except CollectError as exc:
                if "channel_resolution_error" in str(exc):
                    continue  # nothing stored for this channel yet (quiet channel): no new messages
                errors.append(f"#{name or channel_id}: {exc}")
                continue
            items.extend(i for i in (message_to_item(r, name) for r in rows if isinstance(r, dict)) if i)
            self.http.pause(3.0)  # unhurried, like a person reading
        if errors and not items:
            raise CollectError("; ".join(errors))
        return items
