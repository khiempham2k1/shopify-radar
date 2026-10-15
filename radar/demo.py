"""Load sample data so the dashboard can be tried without network access or API keys.

    python -m radar.demo        # into DATABASE_URL

Every row is clearly sample data (titles end with "· mẫu" in the source name).
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from radar.config_loader import load_config
from radar.db import session_scope
from radar.ingest import sync_sources
from radar.models import (
    AIAnalyzed,
    AIResult,
    AITag,
    AIUsage,
    CrawlRun,
    Item,
    ItemStatus,
    ItemTranscript,
    Report,
    SourceStatus,
    utcnow,
)
from radar.scoring import rescore

TAGS = [
    ("Thay đổi nền tảng & hạn chót", "API version, deprecation, thay đổi bắt buộc với theme hoặc app"),
    ("Yêu cầu Theme Store", "Tiêu chí duyệt và hiệu năng của Theme Store"),
    ("App block & theme app extension", "App hiển thị trong theme: app block, theme app extension"),
    ("Theme editor & Liquid", "Section, block, metafield, công cụ dev"),
    ("Hiệu năng theme", "Tốc độ trang, editor chậm"),
    ("Nhu cầu merchant", "Tính năng merchant cần mà theme chưa có"),
    ("Lỗi tích hợp app–theme", "App block không hiển thị, xung đột script"),
]

PLATFORM = [
    ("shopify-dev-changelog", "Theme Store raises the minimum mobile Lighthouse performance score", "Theme Store nâng ngưỡng Lighthouse mobile; áp dụng cho theme mới và bản cập nhật gửi duyệt.", 1, "high", 48, 0.95, "doing", "Minh", 2),
    ("shopify-dev-changelog", "Cart Ajax API: legacy line item properties format removed", "Định dạng thuộc tính dòng hàng cũ trong /cart/add.js bị gỡ; theme gửi thuộc tính kiểu cũ cần cập nhật JS giỏ hàng.", 0, "high", 79, 0.9, "new", "", 5),
    ("shopify-changelog", "Theme Store review adds automated accessibility checks", "Theme gửi duyệt phải qua bộ kiểm tra accessibility tự động; Partner cần sửa lỗi trước khi nộp bản cập nhật.", 1, "high", 168, 0.88, "new", "", 6),
    ("shopify-changelog", "Theme editor: block-level color schemes", "Merchant chỉnh màu ở cấp block; theme cần khai báo schema mới.", 3, "med", None, 0.8, "new", "", 7),
    ("github-releases", "Shopify/cli 3.x: theme dev flag rename", "Cờ cũ của lệnh theme dev vẫn chạy nhưng có cảnh báo; nên cập nhật script CI.", 3, "low", None, 0.6, "new", "", 13),
    ("shopify-dev-changelog", "Admin GraphQL API 2026-10 released", "Thêm trường cho metaobject, không có thay đổi phá vỡ với app hiện tại.", 0, "low", None, 0.55, "done", "Minh", 13),
]

EDITION = [
    ("Theme editor", "Block-level settings and color schemes", 3),
    ("Theme editor", "Faster editor for pages with many sections", 4),
    ("Checkout", "Checkout UI extensions for the thank you page", 2),
    ("Checkout", "Post-purchase upsell via extensions", 2),
    ("Apps", "App blocks in more theme areas", 6),
    ("Storefront", "Image CDN improvements for theme performance", 4),
]

FEED = [
    ("reddit", "Any theme that supports bundles + quick add on collection pages without an app?", "Merchant muốn bundles và quick add ngay trên trang collection, không cài thêm app.", 5, "neu", 0.92, {"upvotes": 142, "comments": 87}, 2),
    ("shopify-community", "Theme editor very slow after last update with 40+ sections", "Theme editor chậm rõ rệt với trang trên 40 section; chưa có phản hồi chính thức.", 4, "neg", 0.9, {"comments": 63}, 5),
    ("reddit", "App blocks not rendering in some OS 2.0 themes after update", "App block biến mất ở một số theme sau cập nhật; nguyên nhân do schema của section.", 6, "neg", 0.88, {"upvotes": 58, "comments": 41}, 7),
    ("web-search", "Checkout extensibility migration checklist for agencies", "Danh sách các bước chuyển đổi checkout cho agency kèm mốc thời gian.", 2, "neu", 0.8, {}, 24),
    ("youtube", "Best Shopify themes for fashion stores 2026 (tested)", "Thử 8 theme trên shop thời trang 1.200 sản phẩm; bộ lọc size/màu và swatch là yếu tố quyết định.", 5, "pos", 0.78, {"views": 48200}, 26),
    ("twitter", "Shopify merchants keep asking for mega menus with images on mobile", "Yêu cầu mega menu có ảnh trên mobile lặp lại nhiều lần trong tuần.", 5, "neu", 0.74, {"likes": 210, "retweets": 31, "comments": 18}, 30),
    ("reddit", "Moving from WooCommerce to Shopify: which theme handles 5k SKUs with filters?", "Merchant cần theme chịu được 5.000+ SKU với bộ lọc nhiều tầng.", 5, "neu", 0.7, {"upvotes": 37, "comments": 29}, 50),
    ("hackernews", "Show HN: Open-source Liquid linter with auto-fix", "Công cụ lint Liquid mã nguồn mở, tự sửa lỗi phổ biến; dùng được trong CI.", 3, "pos", 0.62, {"points": 214, "comments": 66}, 110),
    # Priority topic (config/priorities.txt): shown at the top even with a low AI score.
    ("reddit", "Anyone tried Shopify Canvas for theme work yet?", "Dev hỏi cách dùng Shopify Canvas với theme hiện có; chưa có câu trả lời chính thức.", 3, "neu", 0.45, {"upvotes": 12, "comments": 9}, 8),
    ("youtube", "Shopify theme speed optimization: 5 fixes that actually work", "Năm cách tăng tốc theme: image_url đúng kích thước, lazy load section, hoãn script app.", 4, "neu", 0.66, {"views": 12900}, 140),
]


def seed(session: Session) -> None:
    config = load_config(session)
    sync_sources(session, config)
    now = utcnow()
    today = date.today()
    tags = []
    for priority, (name, desc) in enumerate(TAGS, start=1):
        tag = AITag(tag=name, description=desc, priority=priority, version=1, prompt_hash=config.interests_hash)
        session.add(tag)
        tags.append(tag)
    session.flush()

    def add(source_id, title, summary, tag_index, sentiment, score, metrics, hours_ago, *, impact=None, deadline_days=None, media="post", extra=None, status=None, owner="", affects=None):
        item = Item(
            source_id=source_id,
            url=f"https://example.com/sample/{source_id}/{abs(hash(title)) % 10**8}",
            title=title,
            content=summary,
            summary=summary,
            media_type=media,
            first_seen=now - timedelta(hours=hours_ago),
            last_seen=now - timedelta(hours=max(0, hours_ago - 1)),
            metrics=metrics,
            extra=extra or {},
            keyword_matched=True,
        )
        session.add(item)
        session.flush()
        session.add(
            AIResult(
                item_id=item.id,
                tag_id=tags[tag_index].id,
                score=score,
                sentiment=sentiment,
                impact=impact,
                affects=affects or ("theme,merchant" if media == "change" else "merchant"),
                deadline=today + timedelta(days=deadline_days) if deadline_days else None,
            )
        )
        session.add(AIAnalyzed(item_id=item.id, prompt_hash=config.interests_hash, matched=True))
        if status and status != "new":
            session.add(ItemStatus(item_id=item.id, status=status, owner=owner, updated_by="demo"))
        return item

    for source_id, title, summary, tag_i, impact, deadline, score, status, owner, hours in PLATFORM:
        affects = "theme,partner" if "Theme Store" in title else "theme" if "API" in title or "cli" in title else None
        add(source_id, title, summary, tag_i, "neu", score, {}, hours, impact=impact, deadline_days=deadline, media="change", status=status, owner=owner, affects=affects)
    for section, feature, tag_i in EDITION:
        add(
            "shopify-editions",
            f"Summer '26: {feature}",
            f"Tính năng mới trong Summer '26 thuộc nhóm {section}.",
            tag_i,
            "neu",
            0.7,
            {},
            300,
            impact="med",
            media="change",
            extra={"edition": "Summer '26", "section": section},
        )
    for source_id, title, summary, tag_i, sentiment, score, metrics, hours in FEED:
        media = "video" if source_id == "youtube" else "post"
        item = add(source_id, title, summary, tag_i, sentiment, score, metrics, hours, media=media, extra={"duration": 1104} if media == "video" else {})
        if media == "video":
            session.add(
                ItemTranscript(
                    item_id=item.id,
                    status="done",
                    via="groq" if "fashion" in title else "subtitle",
                    language="en",
                    text="(transcript mẫu)",
                    segments=[{"start": 0, "end": 5, "text": "(transcript mẫu)"}],
                    points=[{"t": 130, "text": "Tiêu chí chấm: tốc độ mobile, bộ lọc, trang sản phẩm"}, {"t": 405, "text": "Bộ lọc size + màu là lý do chính khiến loại 3 theme"}],
                    duration_s=1104,
                    audio_seconds=1104 if "fashion" in title else 0,
                    model="whisper-large-v3-turbo" if "fashion" in title else "youtube-captions",
                )
            )

    run = CrawlRun(started_at=now - timedelta(minutes=5), finished_at=now, items_new=len(PLATFORM) + len(FEED), items_seen=40)
    session.add(run)
    session.flush()
    statuses = {
        "shopify-community": ("error", "", "HTTP 403 hai lần liên tiếp. Tự thử lại ở lần chạy sau."),
        "reddit": ("warn", "exa", "Đang dùng dự phòng exa. rdt-cli: not_authenticated – cookie hết hạn"),
    }
    for source in config.sources:
        status, backend, message = statuses.get(source["id"], ("ok", (source.get("backends") or [source["type"]])[0], "Dữ liệu mẫu"))
        session.add(SourceStatus(crawl_run_id=run.id, source_id=source["id"], status=status, backend=backend, message=message, items_count=5, duration_ms=1200))

    for day in range(14):
        session.add(AIUsage(task="classify", model="claude-opus-5-5", input_tokens=120000, output_tokens=14000, cache_read_tokens=60000, cost_usd=0.77, created_at=now - timedelta(days=day)))
        if day % 2 == 0:
            session.add(AIUsage(task="summarize", model="claude-opus-5-5", input_tokens=9000, output_tokens=900, cost_usd=0.054, created_at=now - timedelta(days=day)))
    session.add(AIUsage(task="report", model="claude-opus-5-5", input_tokens=60000, output_tokens=4000, cost_usd=0.32, created_at=now - timedelta(days=2)))

    start = today - timedelta(days=today.weekday() + 7)
    session.add(
        Report(
            kind="weekly",
            period_start=start,
            period_end=start + timedelta(days=6),
            items_considered=412,
            model="claude-opus-5-5",
            content={
                "summary": "Tuần này có hai thay đổi nền tảng mức cao và nhu cầu bundles/quick add tăng mạnh. (Báo cáo mẫu)",
                "risks": [{"text": "Ngưỡng hiệu năng Theme Store tăng, hạn trong khoảng 7 tuần.", "item_ids": []}],
                "opportunities": [{"text": "Nhu cầu bundles và quick add ở trang collection tăng.", "item_ids": []}],
                "actions": [{"text": "Đo lại Lighthouse mobile cho tất cả theme.", "owner": "Tech lead"}],
                "tag_counts": [],
            },
        )
    )
    from radar.doctor import Check, save_login_status

    save_login_status(
        session,
        [
            Check("rdt-cli (Reddit)", "warn", "Cookie đã dùng 6 ngày, sắp hết hạn. Chạy `rdt login` hoặc chép credential.json mới của tài khoản radar"),
            Check("twitter-cli (X)", "ok", "Đã đăng nhập"),
        ],
    )
    session.flush()
    # Official X posts: one tweet posted by two accounts, and one that only pointed at a
    # changelog entry, so it is attached to that entry instead of listed again.
    add(
        "x-official",
        "Theme blocks: nesting and presets now available to every Theme Store theme",
        "Shopify thông báo theme block hỗ trợ lồng nhau và preset; theme cần cập nhật schema để dùng.",
        3, "neu", 0.82, {"likes": 640, "retweets": 120, "views": 98000}, 20,
        impact="med", media="post", extra={"posted_by": ["ShopifyDevs", "ShopifyEng"]}, affects="theme,merchant",
    )
    target = session.scalar(select(Item).where(Item.title == "Theme editor: block-level color schemes"))
    if target is not None:
        target.extra = {
            **(target.extra or {}),
            "also": [
                {"source": "x-official", "source_name": "Shopify trên X", "url": "https://x.com/ShopifyDevs/status/1", "author": "@ShopifyDevs", "posted_by": ["ShopifyDevs", "Shopify"]},
            ],
        }

    # Community talk (Discord, Shopify Community): raw messages and a Vietnamese 24-hour digest.
    discord_msgs = [
        ("maria", "Theme editor takes ~20s to load on pages with 30+ sections since yesterday, anyone else?", 3, 6),
        ("dev_kim", "Same here on Dawn 15. Section groups seem to make it worse.", 2, 4),
        ("tom", "Is there a way to nest blocks inside app blocks yet?", 5, 0),
        ("lena", "Tip: use {% render %} with only the variables you need, cut our render time a lot", 9, 11),
    ]
    talk_ids = []
    for i, (author, text, hours_ago, reactions) in enumerate(discord_msgs):
        msg = Item(
            source_id="discord",
            url=f"https://discord.com/channels/111/222/{900 + i}",
            title=text[:160],
            content=text,
            author=author,
            media_type="message",
            published_at=now - timedelta(hours=hours_ago),
            first_seen=now - timedelta(hours=hours_ago),
            last_seen=now,
            metrics={"likes": reactions} if reactions else {},
            extra={"channel": "theme-dev", "channel_id": "222"},
            keyword_matched=True,
        )
        session.add(msg)
        session.flush()
        talk_ids.append(msg.id)
    session.add(
        Report(
            kind="community",
            period_start=today - timedelta(days=1),
            period_end=today,
            items_considered=len(talk_ids) + 1,
            model="claude-opus-5-5",
            content={
                "overview": "Trong 24 giờ qua, cộng đồng tập trung vào việc theme editor chậm trên trang nhiều section, nhất là với Dawn 15 và section group. Ngoài ra có câu hỏi về lồng block trong app block và một mẹo giảm thời gian render bằng {% render %}.",
                "topics": [
                    {"title": "Theme editor chậm với trang nhiều section", "summary": "Nhiều người báo editor mất khoảng 20 giây để tải trang có trên 30 section từ hôm qua; có người nghi section group làm chậm thêm. Chưa có phản hồi chính thức.", "kind": "problem", "sources": ["Discord #theme-dev", "Shopify Community"], "item_ids": talk_ids[:2]},
                    {"title": "Mẹo giảm thời gian render", "summary": "Dùng {% render %} và chỉ truyền biến cần thiết giúp giảm đáng kể thời gian render.", "kind": "tip", "sources": ["Discord #theme-dev"], "item_ids": talk_ids[3:4]},
                ],
                "open_questions": [{"text": "Đã lồng block bên trong app block được chưa?", "item_ids": talk_ids[2:3]}],
                "window_start": (now - timedelta(hours=24)).isoformat(),
                "window_end": now.isoformat(),
                "places": [{"name": "Discord #theme-dev", "count": len(talk_ids)}, {"name": "Shopify Community", "count": 1}],
            },
        )
    )

    rescore(session, config)


def main() -> None:
    from sqlalchemy import inspect

    from radar.db import get_engine

    if not inspect(get_engine()).has_table("settings"):
        raise SystemExit("Chưa có bảng trong DB. Chạy `radar migrate` trước, rồi chạy lại lệnh này.")
    with session_scope() as session:
        seed(session)
    print("Đã nạp dữ liệu mẫu.")


if __name__ == "__main__":
    main()
