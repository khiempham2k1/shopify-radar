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
- MCP server và chat hỏi đáp trên dữ liệu.

## 2. Kiến trúc

Tham khảo kiến trúc của [TrendRadar](https://github.com/sansan0/TrendRadar): job chạy theo lô, mọi trạng thái nằm trong DB, cấu hình bằng file.

```
config/ (sources.yaml, keywords.txt, interests.txt, prompts/)
        │
collectors/ (cron)  ──▶  Postgres  ◀── ai/ (pipeline 2 bước, tiết kiệm token, fallback keyword)
 rss, github, reddit,      items, item_metrics_history, crawl_runs, source_status,
 community, youtube,       ai_tags, ai_results, ai_analyzed, item_status, item_transcripts
 search, hackernews           │  ▲
                              │  └── transcribe/ (video YouTube → Groq Whisper → transcript → tóm tắt)
                              ▼
                     api/ (FastAPI) ──▶ web/ (Next.js dashboard)
```

**Stack đề xuất:** Python (FastAPI, worker theo lịch) · Postgres · LiteLLM (đa nhà cung cấp, có model dự phòng) · Groq Whisper (chuyển giọng nói trong video thành văn bản) · Next.js · Docker Compose.

### Cấu trúc repo dự kiến

```
shopify-radar/
├── config/        sources.yaml, keywords.txt, interests.txt, prompts/
├── radar/
│   ├── collectors/   rss, github, reddit, community, youtube, search, hackernews
│   ├── filter/       keyword DSL (theo cú pháp TrendRadar)
│   ├── ai/           client (LiteLLM), tag_extractor, classifier, insights
│   ├── transcribe/   tải audio YouTube, gọi Groq Whisper, lưu transcript, tóm tắt
│   ├── scoring/      công thức điểm có trọng số
│   ├── storage/      models, migrations
│   └── jobs/         scheduler, các lệnh doctor/status
├── api/           FastAPI
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

**Không học theo:**
- Module thông báo.
- Phụ thuộc một API tổng hợp duy nhất.
- Chỉ phân loại theo tiêu đề (post social cần thêm nội dung, cắt khoảng 500 ký tự).
- Mỗi ngày một file SQLite (dùng một Postgres duy nhất).
- HTML tĩnh (dùng web app thật).
- Cấu hình cho một người dùng.

TrendRadar theo license GPL-3.0, nên chỉ học kiến trúc và tự viết lại, không copy code.

## 3. Lộ trình (khoảng 5–5.5 tuần)

| Giai đoạn | Thời gian | Kết quả chính |
|---|---|---|
| **0. Chuẩn bị** | 3–5 ngày | Viết file chủ đề quan tâm và từ khóa, lấy API key, dựng khung repo và Docker |
| **1. Lõi: nền tảng, social, web** | 3–3.5 tuần | Pipeline thu thập → lọc → AI → DB; dashboard Tổng quan, Thay đổi nền tảng, Feed, Sức khỏe nguồn |
| **2. AI Insights** | 1–1.5 tuần | Báo cáo tuần, trang Cài đặt |

### Giai đoạn 0: Chuẩn bị (3–5 ngày)

- [ ] Viết **file chủ đề quan tâm** (`config/interests.txt`), mô tả bằng ngôn ngữ tự nhiên như `ai_interests.txt` của TrendRadar. Ví dụ: thay đổi API và deprecation, yêu cầu Theme Store, checkout extensibility, hiệu năng theme, nhu cầu và phàn nàn của merchant về theme/app.
- [ ] Viết bộ từ khóa ban đầu (`config/keywords.txt`):
  - Nhu cầu merchant: "best shopify theme for …", "looking for a shopify theme", "theme doesn't support", "switch theme from …".
  - Kỹ thuật: "Online Store 2.0", "theme app extension", "checkout extensibility", "Shopify Editions", "theme store requirements".
- [ ] Đăng ký các tài khoản: Reddit API, YouTube Data API, Groq API (Whisper), search API (Brave hoặc Serper), một nhà cung cấp LLM.
- [ ] Dựng khung repo và Docker Compose gồm `postgres`, `worker`, `api`, `web`.
- [ ] Chọn nơi chạy: VPS hoặc server nội bộ.

### Giai đoạn 1: Lõi — nền tảng, social, web (3–3.5 tuần)

**Backend (khoảng 2 tuần)**

- [ ] Schema Postgres:
  - `sources`
  - `items`: duy nhất theo `url` + nguồn; có `first_seen`, `last_seen`, `seen_count`
  - `item_metrics_history`: upvote, comment, view theo thời gian
  - `crawl_runs`, `source_status`
  - `ai_tags` (kèm `version`, `prompt_hash`), `ai_results`, `ai_analyzed`
  - `item_status`: trạng thái, người phụ trách
  - `item_transcripts`: transcript video (văn bản, các đoạn có mốc thời gian, ngôn ngữ, thời lượng, model, trạng thái xử lý)
- [ ] Collectors:

  | Nguồn | Cách lấy |
  |---|---|
  | Shopify dev changelog (shopify.dev/changelog), Shopify news, Google Alerts | RSS |
  | [Shopify Changelog](https://changelog.shopify.com/): thay đổi sản phẩm phía merchant | RSS nếu có, nếu không thì thu thập trang công khai |
  | [Shopify Editions](https://www.shopify.com/editions): các đợt ra mắt lớn mỗi mùa | Thu thập trang công khai mỗi ngày; phát hiện Edition mới, tách từng tính năng thành item riêng để AI phân loại |
  | Shopify CLI, theme mẫu, Polaris | GitHub releases |
  | r/shopify, r/shopifydev, r/ecommerce (subreddit và tìm kiếm) | Reddit API (OAuth) |
  | Shopify Community | Trang công khai hoặc RSS nếu có |
  | YouTube (review và hướng dẫn về theme/app) | YouTube Data API để tìm video; video liên quan được nghe nội dung bằng Groq (xem bên dưới) |
  | Web search theo bộ truy vấn | Brave Search hoặc Serper |
  | Hacker News | Algolia API |

- [ ] Mỗi collector có: thử lại khi lỗi, khoảng nghỉ ngẫu nhiên giữa các request, kiểm tra domain, ghi `source_status`.
- [ ] Bộ lọc từ khóa: nhóm, regex, `+` bắt buộc, `!` loại trừ, danh sách loại trừ toàn cục.
- [ ] AI pipeline 2 bước:
  - Từ file chủ đề quan tâm, AI sinh danh sách tag. Ví dụ: "Thay đổi nền tảng: Checkout", "Yêu cầu Theme Store", "Nhu cầu merchant: tốc độ".
  - Phân loại theo lô, AI trả `{id, tag, score, sentiment, impact, deadline}`.
  - Bỏ qua item đã phân tích; khi file chủ đề đổi thì so hash để quyết định phân loại lại; AI lỗi thì quay về lọc từ khóa.
- [ ] Nghe nội dung video YouTube bằng Groq:
  - Chỉ xử lý video đã qua lọc sơ bộ (tiêu đề và mô tả qua từ khóa và AI, điểm ≥ ngưỡng) và không dài quá giới hạn trong config (ví dụ 60 phút), để kiểm soát chi phí.
  - Tải audio (ví dụ bằng `yt-dlp`), nén về mono 16 kHz bitrate thấp; chia thành nhiều đoạn nếu vượt giới hạn kích thước file của Groq.
  - Gọi Groq `whisper-large-v3-turbo`, lấy transcript kèm mốc thời gian. Truyền danh sách thuật ngữ Shopify (Liquid, metafield, checkout extensibility…) qua tham số `prompt` để nhận diện đúng từ chuyên ngành.
  - Lưu vào `item_transcripts`, xóa file audio sau khi xong.
  - LLM tóm tắt transcript: một đoạn tóm tắt tiếng Việt và 3–5 ý chính kèm mốc thời gian. **Cập nhật nội dung item** bằng bản tóm tắt này, rồi chạy lại phân loại AI dựa trên nội dung video thay vì chỉ tiêu đề.
  - Chạy như một hàng đợi riêng sau collector, mỗi video có trạng thái chờ / đang xử lý / xong / lỗi, có thử lại. Không xử lý lại video đã có transcript.
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
  - **Thay đổi nền tảng:** timeline gộp dev changelog, Shopify Changelog và Shopify Editions; lọc theo nguồn; nhãn mức ảnh hưởng, đếm ngược hạn chót, trạng thái (chưa xem / đang xử lý / xong). Mỗi Edition có trang tóm tắt riêng, liệt kê các tính năng liên quan tới theme/app.
  - **Feed:** gộp các nguồn, có bộ lọc và tìm kiếm toàn văn (tìm được cả trong transcript video), nhãn AI, gắn cờ "không liên quan". Video YouTube hiển thị tóm tắt từ nội dung video, các ý chính kèm mốc thời gian (bấm để mở video đúng đoạn đó) và nhãn "Đã nghe nội dung" hoặc "Đang xử lý".
  - **Sức khỏe nguồn:** lần chạy gần nhất, lỗi, số item. Thêm dòng cho hàng đợi Groq: số video đã xử lý, số phút audio, số video lỗi.
- [ ] Triển khai Docker lên VPS, cron chạy mỗi 1–3 giờ.

**Tiêu chí hoàn thành:**
- Thay đổi nền tảng được phát hiện trong vòng 24 giờ.
- Ít nhất 80% trong top 20 item của Feed là thông tin có ích.
- Team mở dashboard hằng ngày.

### Giai đoạn 2: AI Insights (1–1.5 tuần)

- [ ] Báo cáo tuần tự động, lưu lại để xem lịch sử: cơ hội, rủi ro, việc cần làm.
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
| Groq Whisper (`whisper-large-v3-turbo`, khoảng $0.04/giờ audio) | Khoảng $1–5 (ví dụ 100 video × 15 phút/tháng ≈ 25 giờ ≈ $1) |
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
| Tải audio YouTube bằng công cụ bên thứ ba có thể trái điều khoản YouTube, và IP server dễ bị YouTube chặn | Chỉ dùng nội bộ, chỉ xử lý video đã lọc, tần suất thấp, xóa audio sau khi xử lý; cân nhắc rủi ro pháp lý trước khi bật; theo dõi tỉ lệ lỗi trên trang Sức khỏe nguồn |
| Video dài hoặc file audio vượt giới hạn của Groq | Giới hạn độ dài trong config, nén audio, chia đoạn rồi ghép transcript |
| Transcript sai thuật ngữ chuyên ngành | Truyền danh sách thuật ngữ qua tham số `prompt` của Whisper; tóm tắt bằng LLM để giảm ảnh hưởng của lỗi nhỏ |

## 6. Cần chốt trước khi bắt đầu

1. Stack: Python (FastAPI) và Next.js (đề xuất), hay toàn bộ TypeScript.
2. Nhà cung cấp LLM và ngân sách hằng tháng.
3. Nơi chạy: VPS hay server nội bộ.
4. Người phụ trách chính, tức người đọc và xử lý danh sách "Cần xử lý".
