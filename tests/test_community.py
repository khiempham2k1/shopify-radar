import json
from datetime import timedelta

from sqlalchemy import select

from radar.ai import community
from radar.ai.classifier import pending_items
from radar.ai.client import ClaudeClient
from radar.collectors.base import CollectedItem
from radar.collectors.discord import DiscordCollector, message_to_item
from radar.ingest import store_items
from radar.models import Report, utcnow


def row(msg_id, content, minutes_ago=10, **raw):
    ts = (utcnow() - timedelta(minutes=minutes_ago)).isoformat()
    return {
        "guild_id": "111",
        "guild_name": "Shopify Devs",
        "channel_id": "222",
        "channel_name": "general",
        "msg_id": msg_id,
        "sender_name": "alice",
        "content": content,
        "timestamp": ts,
        "raw_json": json.dumps({"id": msg_id, "type": raw.pop("type", 0), "author": {"username": "alice", "bot": raw.pop("bot", False)}, **raw}),
    }


def test_discord_message_parsing():
    item = message_to_item(row("9", "Theme editor is slow after the update\nanyone else?", reactions=[{"count": 3}, {"count": 2}], message_reference={"message_id": "8"}))
    assert item.url == "https://discord.com/channels/111/222/9"
    assert item.title == "Theme editor is slow after the update" and item.metrics == {"likes": 5}
    assert item.extra["channel"] == "general" and item.extra["reply_to"] == "8" and item.media_type == "message"
    assert message_to_item(row("10", "")) is None
    assert message_to_item(row("11", "joined", type=7)) is None
    assert message_to_item(row("12", "beep", bot=True)) is None


def test_discord_collector_syncs_then_reads(monkeypatch):
    calls = []

    def run_cli(args, timeout=120):
        calls.append(args[:3])
        if args[1] == "dc":
            return {"fetched": 2, "stored": 2}
        return [row("1", "How do I add a section group?"), row("2", "Use sections/header-group.json")]

    monkeypatch.setattr("radar.collectors.discord.run_cli", run_cli)
    collector = DiscordCollector({"id": "discord", "channels": [{"id": "222", "name": "general"}], "limit": 50})
    collector.http.pause = lambda *_: None
    items = collector.fetch_discord_cli()
    assert [c[:2] for c in calls] == [["discord", "dc"], ["discord", "recent"]]
    assert [i.external_id for i in items] == ["1", "2"]


def test_discord_without_channels_reports_it():
    result = DiscordCollector({"id": "discord", "channels": []}).collect()
    assert result.status == "error" and "Chưa khai báo kênh" in result.message


def seed_talk(session, config):
    msgs = [message_to_item(row(str(i), f"Theme editor slow with many sections, message {i}", minutes_ago=30 + i)) for i in range(5)]
    store_items(session, "discord", msgs, config.keywords, max_age_days=7)
    store_items(
        session,
        "shopify-community",
        [CollectedItem(url="https://community.shopify.com/t/editor-slow/1", title="Editor slow on Dawn", content="Since yesterday the theme editor takes 20s to load.", published_at=utcnow())],
        config.keywords,
        max_age_days=7,
    )
    old = message_to_item(row("old", "Two days ago", minutes_ago=60 * 48))
    store_items(session, "discord", [old], config.keywords, max_age_days=7)
    session.flush()


def test_community_items_skip_classification_and_feed(session, config):
    seed_talk(session, config)
    assert not [i for i in pending_items(session, config) if i.source_id in ("discord", "shopify-community")]


def test_digest_and_thread_summaries(session, config, fake_anthropic):
    seed_talk(session, config)
    claude = ClaudeClient(session, model="claude-opus-5-5", client=fake_anthropic)
    result = community.refresh(session, config, claude)
    assert result["summarized"] == 1 and result["digest"]
    thread = session.scalar(select(community.Item).where(community.Item.source_id == "shopify-community"))
    assert thread.summary.startswith("Tóm tắt chủ đề")
    report = session.get(Report, result["digest"])
    assert report.kind == "community" and report.items_considered == 6  # 5 messages + 1 thread; the 2-day-old one is outside
    content = report.content
    assert content["overview"] and content["topics"][0]["kind"] == "problem"
    assert 99999 not in content["topics"][0]["item_ids"]  # unknown ids dropped
    assert {p["name"] for p in content["places"]} == {"Discord #general", "Shopify Community"}
    assert set(content["all_item_ids"]) == {i.id for i in community.window_items(session, 24)}
    # Not due again right away; forced, but nothing new since: no digest repeating the same talk.
    assert community.refresh(session, config, claude)["digest"] is None
    assert community.refresh(session, config, claude, force=True)["digest"] is None


def test_next_digest_holds_only_new_talk(session, config, fake_anthropic):
    seed_talk(session, config)
    claude = ClaudeClient(session, model="claude-opus-5-5", client=fake_anthropic)
    first = session.get(Report, community.refresh(session, config, claude)["digest"])
    # Time passes: the talk was stored 10 minutes ago, the digest written 5 minutes ago.
    for item in session.scalars(select(community.Item)):
        item.first_seen = utcnow() - timedelta(minutes=10)
    first.created_at = utcnow() - timedelta(minutes=5)
    session.flush()
    new = message_to_item(row("new", "Anyone else seeing the editor freeze?", minutes_ago=1))
    store_items(session, "discord", [new], config.keywords, max_age_days=7)
    session.flush()
    second = session.get(Report, community.refresh(session, config, claude, force=True)["digest"])
    assert second.items_considered == 1
    assert second.content["all_item_ids"] == [session.scalar(select(community.Item).where(community.Item.external_id == "new")).id]


def test_no_digest_without_talk(session, config, fake_anthropic):
    claude = ClaudeClient(session, model="claude-opus-5-5", client=fake_anthropic)
    assert community.refresh(session, config, claude) == {"summarized": 0, "digest": None}


def test_quiet_discord_channel_is_not_an_error(monkeypatch):
    from radar.collectors.base import CollectError

    def run_cli(args, timeout=120):
        if args[1] == "dc":
            return {"fetched": 0, "stored": 0}
        raise CollectError("discord: channel_resolution_error – Channel '222' not found in local database")

    monkeypatch.setattr("radar.collectors.discord.run_cli", run_cli)
    collector = DiscordCollector({"id": "discord", "channels": [{"id": "222"}]})
    collector.http.pause = lambda *_: None
    result = collector.collect()
    assert result.status == "ok" and result.items == []


def test_channel_from_link_or_id():
    from radar.collectors.discord import channel_entry

    link = "https://discord.com/channels/1433454270136582280/1433454271415713959"
    assert channel_entry(link) == {"id": "1433454271415713959", "name": ""}
    assert channel_entry({"url": link, "name": "partners"}) == {"id": "1433454271415713959", "name": "partners"}
    assert channel_entry({"id": "222", "name": "general"}) == {"id": "222", "name": "general"}
    assert channel_entry(222)["id"] == "222" and channel_entry("not a channel")["id"] == ""
