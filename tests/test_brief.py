from datetime import timedelta

from sqlalchemy import select

from radar.ai import brief, community
from radar.ai.classifier import classify
from radar.collectors.base import CollectedItem
from radar.ingest import store_items
from radar.models import Item, Report, utcnow
from radar.pipeline import make_claude
from tests.test_community import seed_talk


def seed(session, config, fake_anthropic):
    store_items(
        session,
        "reddit",
        [CollectedItem(url=f"https://example.com/reddit/{i}", title=t) for i, t in enumerate(["Looking for a Shopify theme with mega menu", "Shopify theme quick add broken"])],
        config.keywords,
    )
    seed_talk(session, config)
    session.commit()
    claude = make_claude(session, config, fake_anthropic)
    classify(session, config, claude)
    community.refresh(session, config, claude)
    session.commit()
    return claude


def test_brief_picks_posts_and_discussions_from_what_it_was_shown(session, config, fake_anthropic):
    claude = seed(session, config, fake_anthropic)
    report = session.get(Report, brief.refresh(session, config, claude, force=True))
    content = report.content
    assert report.kind == "brief" and content["headline"] and content["summary"]
    posts = {i.id for i in session.scalars(select(Item).where(Item.source_id == "reddit"))}
    talk = {i.id for i in session.scalars(select(Item).where(Item.source_id.in_(["discord", "shopify-community"])))}
    # Posts only from posts, discussions only from community talk, unknown ids dropped.
    assert {p["item_id"] for p in content["must_read"]} == posts
    assert {p["item_id"] for p in content["discussions"]} <= talk and content["discussions"]
    assert len(content["discussions"]) <= 5 and all(p["why"] for p in content["discussions"])
    assert 99999 not in content["highlights"][0]["item_ids"]
    # The prompt showed the community digest too.
    call = next(c for c in fake_anthropic.messages.calls if "headline" in c["output_config"]["format"]["schema"]["properties"])
    assert "Cộng đồng bàn nhiều về theme editor chậm." in call["messages"][0]["content"]


def test_brief_is_written_when_due_and_something_new_came_in(session, config, fake_anthropic):
    claude = seed(session, config, fake_anthropic)
    first = session.get(Report, brief.refresh(session, config, claude))
    assert first is not None
    assert brief.refresh(session, config, claude) is None  # too soon
    first.created_at = utcnow() - timedelta(hours=7)
    for item in session.scalars(select(Item)):
        item.first_seen = utcnow() - timedelta(hours=8)
    session.flush()
    assert not brief.brief_due(session, config)  # old enough, but nothing new since
    store_items(session, "reddit", [CollectedItem(url="https://example.com/reddit/new", title="Shopify theme section group question")], config.keywords)
    session.flush()
    assert brief.brief_due(session, config)


def test_no_brief_without_anything_to_read(session, config, fake_anthropic):
    claude = make_claude(session, config, fake_anthropic)
    assert brief.refresh(session, config, claude, force=True) is None

