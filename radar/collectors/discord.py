"""Discord channels through discord-cli (jackwener/discord-cli), with the radar's own account.

The account joins the public community server like any member; discord-cli
reads channels with that account's token (DISCORD_TOKEN). This is user-token
automation, which Discord's terms do not allow and may punish by closing the
account, so: a dedicated account, read only, a few channels, every two hours.

Each run syncs new messages into discord-cli's local store, then reads the
last `hours` of them. Messages are not classified one by one: the community
page sums them up in a Vietnamese digest (radar/ai/community.py).
"""

from __future__ import annotations

import json
import re
from typing import Any

from radar.collectors.base import CollectedItem, CollectError, Collector, run_cli, to_datetime

SYSTEM_TYPES = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 14, 15, 16, 17, 18}  # joins, pins, boosts…


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


def message_to_item(row: dict[str, Any], channel_name: str = "") -> CollectedItem | None:
    content = (row.get("content") or "").strip()
    try:
        raw = json.loads(row.get("raw_json") or "{}")
    except (TypeError, json.JSONDecodeError):
        raw = {}
    if not content or raw.get("type") in SYSTEM_TYPES or (raw.get("author") or {}).get("bot"):
        return None
    guild = row.get("guild_id") or raw.get("guild_id") or "@me"
    channel = row.get("channel_id") or raw.get("channel_id") or ""
    msg_id = str(row.get("msg_id") or raw.get("id") or "")
    if not channel or not msg_id:
        return None
    reactions = sum(int(r.get("count") or 0) for r in raw.get("reactions") or [])
    reply_to = (raw.get("message_reference") or {}).get("message_id")
    name = row.get("channel_name") or channel_name or channel
    return CollectedItem(
        url=f"https://discord.com/channels/{guild}/{channel}/{msg_id}",
        title=content.splitlines()[0][:160],
        content=content[:4000],
        author=row.get("sender_name") or (raw.get("author") or {}).get("username") or "",
        published_at=to_datetime(row.get("timestamp") or raw.get("timestamp")),
        external_id=msg_id,
        media_type="message",
        metrics={"likes": reactions} if reactions else {},
        extra={"channel": name, "channel_id": channel, "guild": row.get("guild_name") or "", "reply_to": reply_to or ""},
    )


class DiscordCollector(Collector):
    type = "discord"
    default_backends = ["discord-cli"]

    def fetch_discord_cli(self) -> list[CollectedItem]:
        channels = [c for c in map(channel_entry, self.source.get("channels") or []) if c["id"]]
        if not channels:
            raise CollectError("Chưa khai báo kênh Discord (channels trong sources.yaml)")
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
