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
    assert result["translated"] == 6  # every stored Discord message, the 2-day-old one too
    message = session.scalar(select(community.Item).where(community.Item.external_id == "0"))
    assert message.summary == f"Bản dịch {message.id}"
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
    assert community.refresh(session, config, claude) == {"images": 0, "translated": 0, "summarized": 0, "digest": None}


def test_quiet_discord_channel_is_not_an_error(monkeypatch):
    from radar.collectors.base import CollectError

    def run_cli(args, timeout=120):
        if args[1] == "dc":
            return {"fetched": 0, "stored": 0}
        raise CollectError("discord: channel_resolution_error – Channel '222' not found in local database")

    monkeypatch.setattr("radar.collectors.discord.run_cli", run_cli)
    collector = DiscordCollector({"id": "discord", "channels": [{"id": "222"}]})
    collector.http.pause = lambda *_: None
    assert collector.fetch_discord_cli() == []


def test_channel_from_link_or_id():
    from radar.collectors.discord import channel_entry

    link = "https://discord.com/channels/1433454270136582280/1433454271415713959"
    assert channel_entry(link) == {"id": "1433454271415713959", "name": ""}
    assert channel_entry({"url": link, "name": "partners"}) == {"id": "1433454271415713959", "name": "partners"}
    assert channel_entry({"id": "222", "name": "general"}) == {"id": "222", "name": "general"}
    assert channel_entry(222)["id"] == "222" and channel_entry("not a channel")["id"] == ""


def test_translation_splits_batch_on_max_tokens(session, config, fake_anthropic):
    from tests.conftest import default_responder, make_message

    seed_talk(session, config)
    calls = []

    def responder(kwargs):
        if "translations" in kwargs["output_config"]["format"]["schema"]["properties"]:
            calls.append(kwargs)
            if kwargs["messages"][0]["content"].count("[id=") > 3:
                message = make_message({"translations": []})
                message.stop_reason = "max_tokens"
                return message
        return default_responder(kwargs)

    fake_anthropic.messages.responder = responder
    claude = ClaudeClient(session, model="claude-opus-5-5", client=fake_anthropic)
    assert community.translate_messages(session, config, claude) == 6
    assert len(calls) == 3  # 6 messages: too long, then 3 + 3


def test_reset_digests_starts_over(session, config, fake_anthropic):
    seed_talk(session, config)
    claude = ClaudeClient(session, model="claude-opus-5-5", client=fake_anthropic)
    community.refresh(session, config, claude)
    assert community.delete_digests(session) == 1
    fresh = session.get(Report, community.refresh(session, config, claude, force=True)["digest"])
    assert fresh.items_considered == 6  # all talk of the last 24 h again, nothing lost
    assert session.scalar(select(community.Item).where(community.Item.external_id == "0")).summary  # translations kept


def api_message(msg_id, content="", **fields):
    return {
        "id": msg_id,
        "type": fields.pop("type", 0),
        "channel_id": "222",
        "content": content,
        "timestamp": (utcnow() - timedelta(minutes=5)).isoformat(),
        "author": {"username": "vikas", "global_name": "Vikas"},
        **fields,
    }


def test_api_message_keeps_attachments_embeds_and_reply():
    from radar.collectors.discord import raw_message_to_item

    item = raw_message_to_item(
        api_message(
            "50",
            "We checked this viraldeck and it looks like this-",
            attachments=[{"filename": "Z.png", "url": "https://cdn.discordapp.com/attachments/1/2/Z.png?ex=1", "content_type": "image/png", "width": 800, "height": 600}],
            embeds=[{"type": "link", "title": "Crisp Dezign", "description": "Shopify Partner", "url": "https://www.shopify.com/partners/directory/partner/crisp-dezign", "provider": {"name": "Shopify"}}],
            message_reference={"message_id": "49"},
            referenced_message={"id": "49", "content": "Who made this theme?", "author": {"username": "sul"}},
            reactions=[{"count": 2}],
        ),
        guild_id="111",
        channel_name="general",
    )
    assert item.url == "https://discord.com/channels/111/222/50" and item.author == "Vikas"
    assert "[Ảnh: Z.png]" in item.content and "[Link: Shopify — Crisp Dezign — Shopify Partner — https://www.shopify.com/partners/directory/partner/crisp-dezign]" in item.content
    assert item.extra["attachments"][0]["url"].startswith("https://cdn.discordapp.com/") and item.extra["embeds"][0]["site"] == "Shopify"
    assert item.extra["reply_to"] == "49" and item.extra["reply_author"] == "sul" and item.extra["reply_text"] == "Who made this theme?"
    assert item.metrics == {"likes": 2}
    # Only images: titled after the file. Bots and system messages are left out.
    only_image = raw_message_to_item(api_message("51", attachments=[{"filename": "image.png", "url": "https://cdn/x.png"}]), "111")
    assert only_image.title == "image.png" and only_image.content == "[Ảnh: image.png]"
    assert raw_message_to_item(api_message("52", "hi", author={"username": "bot", "bot": True})) is None
    assert raw_message_to_item(api_message("53", "joined", type=7)) is None
    assert raw_message_to_item(api_message("54")) is None


def test_discord_api_pages_through_new_messages(monkeypatch):
    monkeypatch.setenv("DISCORD_TOKEN", "radar-token")
    calls = []

    def api(self, path, token, **params):
        calls.append((path, params.get("after")))
        assert token == "radar-token"
        if path == "/channels/222":
            return {"id": "222", "name": "general", "guild_id": "111"}
        if len([c for c in calls if c[0].endswith("/messages")]) == 1:
            return [api_message(str(200 - i), f"message {i}") for i in range(100)]  # a full page, newest first
        return [api_message("300", "the last one")]

    monkeypatch.setattr(DiscordCollector, "_api", api)
    collector = DiscordCollector({"id": "discord", "channels": ["https://discord.com/channels/111/222"], "backends": ["discord-cli"], "limit": 300})
    collector.http.pause = lambda *_: None
    assert collector.backends == ["discord-api", "discord-cli"]  # the API first even when only discord-cli is listed
    items = collector.fetch_discord_api()
    assert len(items) == 101 and items[0].extra["channel"] == "general"
    message_calls = [c for c in calls if c[0].endswith("/messages")]
    assert len(message_calls) == 2 and message_calls[1][1] == "200"  # second page starts after the newest id seen


def test_message_read_in_full_later_is_updated_and_translated_again(session, config):
    from radar.collectors.discord import raw_message_to_item

    old = message_to_item(row("60", "look at this\n[attachment: Z.png]"))
    store_items(session, "discord", [old], config.keywords, max_age_days=7)
    stored = session.scalar(select(community.Item).where(community.Item.external_id == "60"))
    stored.summary = "bản dịch cũ"
    full = raw_message_to_item(api_message("60", "look at this", attachments=[{"filename": "Z.png", "url": "https://cdn/Z.png", "content_type": "image/png"}]), "111", "general")
    store_items(session, "discord", [full], config.keywords, max_age_days=7)
    assert stored.content == "look at this\n[Ảnh: Z.png]" and stored.summary == ""
    assert stored.extra["attachments"][0]["name"] == "Z.png"


def test_images_are_described_and_fed_to_translation(session, config, fake_anthropic):
    from radar.collectors.discord import raw_message_to_item

    msg = raw_message_to_item(
        api_message("70", "is this a bug?", attachments=[{"filename": "err.png", "url": "https://cdn.discordapp.com/err.png", "content_type": "image/png"}]),
        "111",
        "general",
    )
    store_items(session, "discord", [msg], config.keywords, max_age_days=7)
    claude = ClaudeClient(session, model="claude-opus-5-5", client=fake_anthropic)
    result = community.refresh(session, config, claude)
    assert result["images"] == 1
    item = session.scalar(select(community.Item).where(community.Item.external_id == "70"))
    assert item.extra["image_note"] == "Ảnh chụp thông báo lỗi trong theme editor."
    image_call = next(c for c in fake_anthropic.messages.calls if "note" in c["output_config"]["format"]["schema"]["properties"])
    assert image_call["messages"][0]["content"][0] == {"type": "image", "source": {"type": "url", "url": "https://cdn.discordapp.com/err.png"}}
    translate_call = next(c for c in fake_anthropic.messages.calls if "translations" in c["output_config"]["format"]["schema"]["properties"])
    assert "[Nội dung ảnh: Ảnh chụp thông báo lỗi trong theme editor.]" in translate_call["messages"][0]["content"]
    # Described once: the next run does not look again.
    assert community.refresh(session, config, claude)["images"] == 0


def test_unreadable_image_is_not_retried(session, config, fake_anthropic):
    from radar.collectors.discord import raw_message_to_item
    from tests.conftest import default_responder

    msg = raw_message_to_item(api_message("80", "", attachments=[{"filename": "gone.png", "url": "https://cdn/gone.png", "content_type": "image/png"}]), "111")
    store_items(session, "discord", [msg], config.keywords, max_age_days=7)

    def responder(kwargs):
        if "note" in kwargs["output_config"]["format"]["schema"]["properties"]:
            import anthropic
            import httpx

            raise anthropic.BadRequestError("Could not fetch image", response=httpx.Response(400, request=httpx.Request("POST", "https://api")), body=None)
        return default_responder(kwargs)

    fake_anthropic.messages.responder = responder
    claude = ClaudeClient(session, model="claude-opus-5-5", client=fake_anthropic)
    assert community.describe_images(session, config, claude) == 0
    item = session.scalar(select(community.Item).where(community.Item.external_id == "80"))
    assert item.extra["image_failed"] is True
    assert community.describe_images(session, config, claude) == 0


def test_image_only_message_needs_no_translation(session, config, fake_anthropic):
    from radar.collectors.discord import raw_message_to_item

    assert community.own_text("look\n[Ảnh: a.png]\n[Link: Shopify — x]") == "look"
    msg = raw_message_to_item(api_message("90", attachments=[{"filename": "a.png", "url": "https://cdn/a.png", "content_type": "image/png"}]), "111")
    store_items(session, "discord", [msg], config.keywords, max_age_days=7)
    claude = ClaudeClient(session, model="claude-opus-5-5", client=fake_anthropic)
    assert community.translate_messages(session, config, claude) == 0
    assert not [c for c in fake_anthropic.messages.calls if "translations" in c["output_config"]["format"]["schema"]["properties"]]


def test_one_name_per_discord_channel(session, config):
    from radar.collectors.discord import raw_message_to_item

    old = message_to_item({**row("100", "from discord-cli", minutes_ago=60), "channel_name": "partners"})
    store_items(session, "discord", [old], config.keywords, max_age_days=7)
    session.flush()
    new = raw_message_to_item(api_message("101", "through the API"), "111", "partners-chat")
    store_items(session, "discord", [new], config.keywords, max_age_days=7)
    session.flush()
    assert community.sync_channel_names(session) == 1
    names = {i.extra["channel"] for i in session.scalars(select(community.Item).where(community.Item.source_id == "discord"))}
    assert names == {"partners-chat"}


def conversation(session, config):
    """#1 gets two replies and a reply to a reply; #4 has 3 reactions and no reply; #5 is alone."""
    from radar.collectors.discord import raw_message_to_item

    msgs = [
        api_message("1", "Editor freezes with 30 sections, anyone?", timestamp=(utcnow() - timedelta(minutes=50)).isoformat()),
        api_message("2", "Same here", message_reference={"message_id": "1"}, timestamp=(utcnow() - timedelta(minutes=40)).isoformat()),
        api_message("3", "Try disabling apps", message_reference={"message_id": "1"}, timestamp=(utcnow() - timedelta(minutes=30)).isoformat()),
        api_message("6", "That fixed it, thanks", message_reference={"message_id": "3"}, timestamp=(utcnow() - timedelta(minutes=20)).isoformat()),
        api_message("4", "New Dawn release is out", reactions=[{"count": 3}], timestamp=(utcnow() - timedelta(minutes=15)).isoformat()),
        api_message("5", "gm", timestamp=(utcnow() - timedelta(minutes=5)).isoformat()),
    ]
    store_items(session, "discord", [raw_message_to_item(m, "111", "general") for m in msgs], config.keywords, max_age_days=7)
    session.flush()
    return {i.external_id: i.id for i in session.scalars(select(community.Item).where(community.Item.source_id == "discord"))}


def test_conversation_stats_count_the_whole_reply_chain(session, config):
    ids = conversation(session, config)
    stats = community.conversation_stats(session)
    assert stats[ids["1"]] == {"replies": 2, "thread": 3, "reactions": 0, "engagement": 6}
    assert stats[ids["3"]]["thread"] == 1 and stats[ids["4"]]["engagement"] == 3 and stats[ids["5"]]["engagement"] == 0
