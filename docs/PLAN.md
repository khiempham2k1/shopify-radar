# Shopify Radar — Kế hoạch triển khai

## 1. Mục tiêu

Dashboard nội bộ phục vụ team phát triển **theme (Shopify Theme Store)** và **app (Shopify App)**, giúp:

1. Phát hiện sớm thay đổi của Shopify có thể ảnh hưởng sản phẩm (API, deprecation, yêu cầu Theme Store, chính sách Partner…).
2. Nắm được merchant và cộng đồng đang nói gì, phàn nàn gì, cần gì trên social và web.

**Ngoài phạm vi (hiện tại):**
- App Store radar.
- Theme Store radar: snapshot đối thủ, theme mới, review. Có thể thêm sau mà không cần đổi kiến trúc.
- Thông báo qua Slack hoặc các kênh khác. Đầu ra duy nhất là dashboard.
- Theo dõi thương hiệu (tên theme/app/công ty của mình và đối thủ). Radar theo chủ đề, không theo thương hiệu.

## 2. Kiến trúc

Tham khảo kiến trúc của [TrendRadar](https://github.com/sansan0/TrendRadar): job chạy theo lô, mọi trạng thái nằm trong DB, cấu hình bằng file.

```
config/ (sources.yaml, keywords.txt, interests.txt, prompts/)
        │
collectors/ (cron)  ──▶  Postgres  ◀── ai/ (pipeline 2 bước, tiết kiệm token, fallback keyword)
 rss, github, reddit,      items, item_metrics_history, crawl_runs, source_status,
 community, youtube,       ai_tags, ai_results, ai_analyzed, item_status
 search, hackernews
                                │
                     api/ (FastAPI) + mcp/ ──▶ web/ (Next.js dashboard)
```

**Stack đề xuất:** Python (FastAPI, worker theo lịch) · Postgres · LiteLLM (đa nhà cung cấp, có model dự phòng) · Next.js · Docker Compose.

### Cấu trúc repo dự kiến

```
shopify-radar/
├── config/        sources.yaml, keywords.txt, interests.txt, prompts/
├── radar/
│   ├── collectors/   rss, github, reddit, community, youtube, search, hackernews
│   ├── filter/       keyword DSL (theo cú pháp TrendRadar)
│   ├── ai/           client (LiteLLM), tag_extractor, classifier, insights
│   ├── scoring/      công thức điểm có trọng số
│   ├── storage/      models, migrations
│   └── jobs/         scheduler, các lệnh doctor/status
├── api/           FastAPI
├── mcp/           tool hỏi đáp
├── web/           Next.js dashboard
└── docker/
```

### Các cách làm học từ TrendRadar

| TrendRadar | Áp dụng cho Shopify Radar |
|---|---|
| Job theo lô do cron gọi, trạng thái ở DB | Mỗi collector là một job ghi vào DB; dashboard chỉ đọc |
| Cấu hình bằng file (`config.yaml`, `frequency_words.txt`, `ai_interests.txt`, prompt `[system]/[user]`) | `sources.yaml`, `keywords.txt`, `interests.txt`, `prompts/*.txt` |
| Cú pháp từ khóa: nhóm, `[alias]`, `/regex/`, `+bắt buộc`, `!loại trừ`, `@giới hạn`, loại trừ toàn cục | Dùng lại nguyên cú pháp, làm lớp lọc thô trước khi gọi AI |
| Item duy nhất theo `(url, nguồn)`, có `first/last_crawl_time`, `crawl_count`, `rank_history`, `crawl_source_status` | `items`, `item_metrics_history`, `crawl_runs`, `source_status` (trang Sức khỏe nguồn) |
| Chế độ `incremental` / `current` / `daily` | Bộ lọc dashboard: Mới / Đang nổi / Hôm nay / Tuần này |
| AI filter 2 bước: sở thích → tag (lưu `version`, `prompt_hash`) → phân loại theo lô, trả JSON | `interests.txt` → tag; phân loại trả thêm `sentiment`, `impact`, `deadline` |
| Không phân tích lại item cũ, so hash để phân loại lại, AI lỗi thì quay về keyword, dùng `json-repair` | Áp dụng nguyên |
| Điểm có trọng số: thứ hạng, tần suất, độ nóng | Liên quan (AI), tương tác, số nguồn cùng nhắc, độ mới |
| LiteLLM + `fallback_models`, giới hạn `max_news_for_analysis` | Model rẻ để phân loại, model mạnh cho báo cáo tuần |
| MCP tools (`search_news`, `analyze_topic_trend`, `compare_periods`, `read_article`) | Nền cho chat hỏi đáp trên dashboard |

**Không học theo:**
- Module thông báo.
- Phụ thuộc một API tổng hợp duy nhất.
- Chỉ phân loại theo tiêu đề (post social cần thêm nội dung, cắt khoảng 500 ký tự).
- Mỗi ngày một file SQLite (dùng một Postgres duy nhất).
- HTML tĩnh (dùng web app thật).
- Cấu hình cho một người dùng.

TrendRadar theo license GPL-3.0, nên chỉ học kiến trúc và tự viết lại, không copy code.

## 3. Lộ trình (khoảng 5–6 tuần)

| Giai đoạn | Thời gian | Kết quả chính |
|---|---|---|
| **0. Chuẩn bị** | 3–5 ngày | Viết file chủ đề quan tâm và từ khóa, lấy API key, dựng khung repo và Docker |
| **1. Lõi: nền tảng, social, web** | 2.5–3 tuần | Pipeline thu thập → lọc → AI → DB; dashboard Tổng quan, Thay đổi nền tảng, Feed, Sức khỏe nguồn |
| **2. AI Insights** | 2 tuần | Báo cáo tuần, chat hỏi đáp, trang Cài đặt |

### Giai đoạn 0: Chuẩn bị (3–5 ngày)

- [ ] Viết **file chủ đề quan tâm** (`config/interests.txt`), mô tả bằng ngôn ngữ tự nhiên như `ai_interests.txt` của TrendRadar. Ví dụ: thay đổi API và deprecation, yêu cầu Theme Store, checkout extensibility, hiệu năng theme, nhu cầu và phàn nàn của merchant về theme/app.
- [ ] Viết bộ từ khóa ban đầu (`config/keywords.txt`):
  - Nhu cầu merchant: "best shopify theme for …", "looking for a shopify theme", "theme doesn't support", "switch theme from …".
  - Kỹ thuật: "Online Store 2.0", "theme app extension", "checkout extensibility", "Shopify Editions", "theme store requirements".
- [ ] Đăng ký các tài khoản: Reddit API, YouTube Data API, search API (Brave hoặc Serper), một nhà cung cấp LLM.
- [ ] Dựng khung repo và Docker Compose gồm `postgres`, `worker`, `api`, `web`.
- [ ] Chọn nơi chạy: VPS hoặc server nội bộ.

### Giai đoạn 1: Lõi — nền tảng, social, web (2.5–3 tuần)

**Backend (khoảng 1.5 tuần)**

- [ ] Schema Postgres:
  - `sources`
  - `items`: duy nhất theo `url` + nguồn; có `first_seen`, `last_seen`, `seen_count`
  - `item_metrics_history`: upvote, comment, view theo thời gian
  - `crawl_runs`, `source_status`
  - `ai_tags` (kèm `version`, `prompt_hash`), `ai_results`, `ai_analyzed`
  - `item_status`: trạng thái, người phụ trách
- [ ] Collectors:

  | Nguồn | Cách lấy |
  |---|---|
  | Shopify dev changelog, Shopify news, Google Alerts | RSS |
  | Shopify CLI, theme mẫu, Polaris | GitHub releases |
  | r/shopify, r/shopifydev, r/ecommerce (subreddit và tìm kiếm) | Reddit API (OAuth) |
  | Shopify Community | Trang công khai hoặc RSS nếu có |
  | YouTube (review và hướng dẫn về theme/app) | YouTube Data API |
  | Web search theo bộ truy vấn | Brave Search hoặc Serper |
  | Hacker News | Algolia API |

- [ ] Mỗi collector có: thử lại khi lỗi, khoảng nghỉ ngẫu nhiên giữa các request, kiểm tra domain, ghi `source_status`.
- [ ] Bộ lọc từ khóa: nhóm, regex, `+` bắt buộc, `!` loại trừ, danh sách loại trừ toàn cục.
- [ ] AI pipeline 2 bước:
  - Từ file chủ đề quan tâm, AI sinh danh sách tag. Ví dụ: "Thay đổi nền tảng: Checkout", "Yêu cầu Theme Store", "Nhu cầu merchant: tốc độ".
  - Phân loại theo lô, AI trả `{id, tag, score, sentiment, impact, deadline}`.
  - Bỏ qua item đã phân tích; khi file chủ đề đổi thì so hash để quyết định phân loại lại; AI lỗi thì quay về lọc từ khóa.
- [ ] Chấm điểm: `liên quan (AI) × w1 + tương tác × w2 + số nguồn cùng nhắc × w3 + độ mới × w4`. Trọng số đặt trong config.

**API và dashboard (khoảng 1–1.5 tuần)**

- [ ] API:
  - Danh sách item, lọc theo nguồn, tag, cảm xúc, thời gian, chế độ Mới / Đang nổi / Hôm nay.
  - Cập nhật trạng thái và người phụ trách.
  - Thống kê tổng quan.
  - Sức khỏe nguồn.
- [ ] Đăng nhập Google, giới hạn trong domain công ty.
- [ ] Màn hình:
  - **Tổng quan:** chỉ số tuần (số item mới theo chủ đề, cảm xúc, thay đổi nền tảng còn hạn) và danh sách "Cần xử lý".
  - **Thay đổi nền tảng:** timeline, nhãn mức ảnh hưởng, đếm ngược hạn chót, trạng thái (chưa xem / đang xử lý / xong).
  - **Feed:** gộp các nguồn, có bộ lọc và tìm kiếm toàn văn, nhãn AI, gắn cờ "không liên quan".
  - **Sức khỏe nguồn:** lần chạy gần nhất, lỗi, số item.
- [ ] Triển khai Docker lên VPS, cron chạy mỗi 1–3 giờ.

**Tiêu chí hoàn thành:**
- Thay đổi nền tảng được phát hiện trong vòng 24 giờ.
- Ít nhất 80% trong top 20 item của Feed là thông tin có ích.
- Team mở dashboard hằng ngày.

### Giai đoạn 2: AI Insights (2 tuần)

- [ ] Báo cáo tuần tự động, lưu lại để xem lịch sử: cơ hội, rủi ro, việc cần làm.
- [ ] Chat hỏi đáp trên dữ liệu với các tool `search_items`, `topic_trend`, `compare_periods`, `read_item`.
- [ ] Trang Cài đặt: sửa từ khóa, nguồn, chủ đề quan tâm. Chuyển cấu hình từ file vào DB.
- [ ] Theo dõi chi phí token.
- [ ] Tùy chọn: thêm X/Twitter nếu có ngân sách.

## 4. Nguồn lực và chi phí ước tính

- **Nhân sự:** 1 dev backend/data (Python) và 1 dev frontend (Next.js), cộng PM bán thời gian. Hoặc 1 fullstack trong khoảng 8–9 tuần.
- **Chi phí hằng tháng** (ước tính sơ bộ, cần kiểm tra lại giá):

| Hạng mục | Chi phí ước tính |
|---|---|
| VPS | $20–40 |
| LLM | $10–50 |
| Search API | $0–50 |
| Reddit, YouTube | Miễn phí trong hạn mức |
| X/Twitter | Đắt, để sau |

## 5. Rủi ro

| Rủi ro | Cách giảm |
|---|---|
| Shopify Community đổi cấu trúc HTML hoặc chặn truy cập | Tần suất thấp, cache, cảnh báo trên trang Sức khỏe nguồn, parser dễ sửa |
| Điều khoản API (Reddit, scraping) | Đọc kỹ điều khoản, chỉ dùng nội bộ, không phát lại dữ liệu ra ngoài |
| Dữ liệu social nhiều nhiễu | Lọc từ khóa thô trước, AI sau, ngưỡng `min_score`, gắn cờ "không liên quan" để tinh chỉnh |
| Chi phí token tăng | Không phân tích lại item cũ, cắt nội dung, giới hạn số item mỗi lần phân tích |
| Không ai dùng dashboard | Danh sách "Cần xử lý" có người phụ trách; báo cáo tuần là đầu vào cho họp sản phẩm |
| Facebook Groups, LinkedIn, TikTok không có API phù hợp | Không đưa vào phạm vi |

## 6. Cần chốt trước khi bắt đầu

1. Stack: Python (FastAPI) và Next.js (đề xuất), hay toàn bộ TypeScript.
2. Nhà cung cấp LLM và ngân sách hằng tháng.
3. Nơi chạy: VPS hay server nội bộ.
4. Người phụ trách chính, tức người đọc và xử lý danh sách "Cần xử lý".
