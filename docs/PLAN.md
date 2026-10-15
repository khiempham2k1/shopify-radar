# Shopify Radar — Kế hoạch triển khai

**Trạng thái:** đã chốt ngày 14/10/2026 (mục 6). Code của Giai đoạn 0, 1 và 2 đã xong; còn các bước team cần làm để chạy thật (mục 7).

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

**Stack (đã chốt):** Python (FastAPI, worker theo lịch) · Postgres · Claude qua Anthropic Python SDK (phân loại, tóm tắt, báo cáo tuần) · Groq Whisper (chỉ dùng để chuyển giọng nói trong video thành văn bản) · các công cụ thu thập miễn phí do [Agent Reach](https://github.com/Panniantong/agent-reach) chọn (xem mục bên dưới) · Next.js · Docker Compose.

### Cấu trúc repo dự kiến

```
shopify-radar/
├── config/        sources.yaml, keywords.txt, interests.txt, prompts/
├── radar/
│   ├── collectors/   rss, github, reddit, twitter, community, youtube, search, web_reader, hackernews
│   ├── filter/       keyword DSL (theo cú pháp TrendRadar)
│   ├── ai/           client (Anthropic SDK), tag_extractor, classifier, summarizer, insights
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
| Không phân tích lại item cũ, so hash để phân loại lại, AI lỗi thì quay về keyword, dùng `json-repair` | Áp dụng nguyên; thay `json-repair` bằng structured outputs của Claude (JSON đúng schema) |
| Điểm có trọng số: thứ hạng, tần suất, độ nóng | Liên quan (AI), tương tác, số nguồn cùng nhắc, độ mới |
| LiteLLM + `fallback_models`, giới hạn `max_news_for_analysis` | Một nhà cung cấp (Claude) nên dùng thẳng Anthropic SDK; chỉnh mức `effort` theo từng tác vụ; giới hạn số item mỗi lần phân tích |

**Không học theo:**
- Module thông báo.
- Phụ thuộc một API tổng hợp duy nhất.
- Chỉ phân loại theo tiêu đề (post social cần thêm nội dung, cắt khoảng 500 ký tự).
- Mỗi ngày một file SQLite (dùng một Postgres duy nhất).
- HTML tĩnh (dùng web app thật).
- Cấu hình cho một người dùng.

TrendRadar theo license GPL-3.0, nên chỉ học kiến trúc và tự viết lại, không copy code.

### Dùng Agent Reach để thu thập miễn phí

[Agent Reach](https://github.com/Panniantong/agent-reach) (license MIT) không phải thư viện thu thập dữ liệu. Nó là một lớp **chọn, cài và kiểm tra sức khỏe** các công cụ mã nguồn mở miễn phí cho từng nền tảng, kèm danh sách công cụ dự phòng khi công cụ chính bị nền tảng chặn. Việc đọc và tìm kiếm thật do các công cụ gốc đó làm. Shopify Radar dùng nó theo ba cách:

1. **Dùng lại lựa chọn công cụ** cho các collector, thay cho API trả phí hoặc API cần xin duyệt:

   | Nhu cầu | Công cụ (miễn phí) | Thay cho |
   |---|---|---|
   | Tìm kiếm web | Exa qua MCP (`mcporter call exa.web_search_exa`), không cần API key | Brave Search / Serper |
   | Đọc toàn văn một trang (kết quả search, blog, Community) | Jina Reader (`https://r.jina.ai/URL`) | Tự viết parser HTML |
   | Tìm video YouTube và lấy phụ đề | `yt-dlp` (`ytsearchN:query`, `--write-auto-sub`) | YouTube Data API |
   | Reddit | `rdt-cli` với cookie của một tài khoản riêng; dự phòng bằng Exa `site:reddit.com` | Reddit API (từ 11/2025 không còn tự đăng ký được, phải xin duyệt) |
   | X/Twitter | `twitter-cli` với cookie của một tài khoản riêng | X API trả phí |
   | RSS, GitHub | `feedparser`, `gh` CLI | (giữ nguyên) |

2. **Dùng lại code** (MIT nên được phép): module `agent_reach/transcribe.py` đã làm sẵn việc tải audio, nén, chia đoạn 10 phút và gọi Groq Whisper. Hàm `WebChannel.read()` đã có xử lý trang chống bot của Jina Reader.
3. **Học cách kiểm tra sức khỏe** của `agent-reach doctor`: mỗi nguồn có danh sách công cụ theo thứ tự ưu tiên, chạy thử thật (không chỉ kiểm tra lệnh có tồn tại) để chọn công cụ đang dùng được, và đưa ra hướng dẫn sửa khi lỗi. Trang Sức khỏe nguồn hiển thị công cụ nào đang được dùng cho từng nguồn.

Cài từ GitHub, không cài từ PyPI: gói cùng tên trên PyPI không phải dự án này. Ghim version các công cụ gốc và cập nhật có kiểm soát, vì các công cụ dựa trên cookie hay bị nền tảng chặn rồi phải đổi.

Không dùng: các nguồn cần phiên đăng nhập trên Chrome desktop (Facebook, Instagram qua OpenCLI), vì không chạy được trên server.

## 3. Lộ trình (khoảng 5–5.5 tuần)

| Giai đoạn | Thời gian | Kết quả chính |
|---|---|---|
| **0. Chuẩn bị** | 3–5 ngày | Viết file chủ đề quan tâm và từ khóa, chuẩn bị tài khoản và công cụ, dựng khung repo và Docker |
| **1. Lõi: nền tảng, social, web** | 3–3.5 tuần | Pipeline thu thập → lọc → AI → DB; dashboard Tổng quan, Thay đổi nền tảng, Feed, Sức khỏe nguồn |
| **2. AI Insights** | 1–1.5 tuần | Báo cáo tuần, trang Cài đặt |

### Giai đoạn 0: Chuẩn bị (3–5 ngày)

- [x] Viết **file chủ đề quan tâm** (`config/interests.txt`), mô tả bằng ngôn ngữ tự nhiên như `ai_interests.txt` của TrendRadar. Ví dụ: thay đổi API và deprecation, yêu cầu Theme Store, checkout extensibility, hiệu năng theme, nhu cầu và phàn nàn của merchant về theme/app.
- [x] Viết bộ từ khóa ban đầu (`config/keywords.txt`):
  - Nhu cầu merchant: "best shopify theme for …", "looking for a shopify theme", "theme doesn't support", "switch theme from …".
  - Kỹ thuật: "Online Store 2.0", "theme app extension", "checkout extensibility", "Shopify Editions", "theme store requirements".
- [ ] **(Team làm)** Chuẩn bị tài khoản và key (đều miễn phí), điền vào `.env`:
  - Groq API key (Whisper; gói miễn phí có giới hạn tần suất).
  - Một tài khoản Reddit và một tài khoản X **riêng cho radar**, không dùng tài khoản chính, để lấy cookie cho `rdt-cli` và `twitter-cli`.
  - Anthropic API key (Claude) cho phân loại, tóm tắt và báo cáo tuần.
- [x] Cài công cụ trong image Docker (`docker/Dockerfile`): `agent-reach` (từ GitHub), `yt-dlp` kèm Deno (YouTube cần JS runtime), `ffmpeg`, `rdt-cli`, `twitter-cli`. Exa MCP được gọi bằng MCP client của Python nên không cần `mcporter`; GitHub releases đọc qua Atom feed nên không cần `gh`. Kiểm tra bằng `radar doctor --network` (cách làm giống `agent-reach doctor`).
- [x] Dựng khung repo và Docker Compose gồm `postgres`, `worker`, `api`, `web`.
- [ ] **(Team làm)** Chuẩn bị server nội bộ chạy Docker (đã chốt chạy nội bộ). Kiểm tra server truy cập được Reddit, X, YouTube, Exa, Jina, Groq và Anthropic API.

### Giai đoạn 1: Lõi — nền tảng, social, web (3–3.5 tuần)

**Backend (khoảng 2 tuần)**

- [x] Schema Postgres:
  - `sources`
  - `items`: duy nhất theo `url` + nguồn; có `first_seen`, `last_seen`, `seen_count`
  - `item_metrics_history`: upvote, comment, view theo thời gian
  - `crawl_runs`, `source_status`
  - `ai_tags` (kèm `version`, `prompt_hash`), `ai_results`, `ai_analyzed`
  - `item_status`: trạng thái, người phụ trách
  - `item_transcripts`: transcript video (văn bản, các đoạn có mốc thời gian, ngôn ngữ, thời lượng, model, trạng thái xử lý)
- [x] Collectors:

  | Nguồn | Cách lấy |
  |---|---|
  | Shopify dev changelog (shopify.dev/changelog), Shopify news, Google Alerts | RSS |
  | [Shopify Changelog](https://changelog.shopify.com/): thay đổi sản phẩm phía merchant | RSS nếu có, nếu không thì thu thập trang công khai |
  | [Shopify Editions](https://www.shopify.com/editions): các đợt ra mắt lớn mỗi mùa | Thu thập trang công khai mỗi ngày; phát hiện Edition mới, tách từng tính năng thành item riêng để AI phân loại |
  | Shopify CLI, theme mẫu, Polaris | GitHub releases |
  | r/shopify, r/shopifydev, r/ecommerce (subreddit và tìm kiếm) | `rdt-cli` (cookie tài khoản riêng); dự phòng Exa `site:reddit.com` |
  | X/Twitter (tìm theo bộ truy vấn) | `twitter-cli` (cookie tài khoản riêng) |
  | Shopify Community | RSS nếu có, nếu không thì đọc trang qua Jina Reader |
  | YouTube (review và hướng dẫn về theme/app) | `yt-dlp` để tìm video (`ytsearchN:query`) và lấy metadata; nội dung video lấy từ phụ đề hoặc Groq (xem bên dưới) |
  | Web search theo bộ truy vấn | Exa qua MCP (miễn phí, không cần key); đọc toàn văn kết quả qua Jina Reader |
  | Hacker News | Algolia API |

- [x] Mỗi collector có: thử lại khi lỗi, khoảng nghỉ ngẫu nhiên giữa các request, kiểm tra domain, ghi `source_status`.
- [x] Bộ lọc từ khóa: nhóm, regex, `+` bắt buộc, `!` loại trừ, danh sách loại trừ toàn cục.
- [x] AI pipeline 2 bước:
  - Từ file chủ đề quan tâm, AI sinh danh sách tag. Ví dụ: "Thay đổi nền tảng: Checkout", "Yêu cầu Theme Store", "Nhu cầu merchant: tốc độ".
  - Phân loại theo lô, AI trả `{id, tag, score, sentiment, impact, deadline}`.
  - Bỏ qua item đã phân tích; khi file chủ đề đổi thì so hash để quyết định phân loại lại; AI lỗi thì quay về lọc từ khóa.
- [x] Dùng Claude (`claude-opus-5-5`, Anthropic Python SDK):
  - Phân loại theo lô (khoảng 50 item mỗi lần gọi) với `effort: low`; tóm tắt transcript video với `effort: medium`; báo cáo tuần với `effort: high`.
  - Structured outputs (`output_config.format`) để luôn nhận JSON đúng schema.
  - Prompt caching cho phần cố định (system prompt, danh sách tag, nội dung `interests.txt`) để giảm chi phí input.
  - Phân loại không cần ngay lập tức có thể gửi qua Message Batches API để giảm 50% chi phí, đổi lại kết quả có thể về chậm hơn.
  - Kiểm tra `stop_reason` trước khi đọc kết quả (bao gồm trường hợp `refusal`), thử lại khi gặp lỗi 429 hoặc 5xx.
- [x] Lấy nội dung video YouTube (phụ đề trước, Groq sau):
  - Chỉ xử lý video đã qua lọc sơ bộ (tiêu đề và mô tả qua từ khóa và AI, điểm ≥ ngưỡng) và không dài quá giới hạn trong config (ví dụ 60 phút), để kiểm soát chi phí.
  - **Thử phụ đề trước** bằng `yt-dlp --write-sub --write-auto-sub --skip-download`. Video có phụ đề thì dùng luôn, không tốn quota Groq.
  - Video không có phụ đề: tải audio, nén về mono 16 kHz bitrate thấp, chia đoạn 10 phút, theo đúng cách của `agent_reach/transcribe.py`. Viết lại trong `radar/transcribe/media.py` thay vì import, vì cần Groq trả `verbose_json` để giữ mốc thời gian (hàm của Agent Reach chỉ trả văn bản).
  - Gọi Groq `whisper-large-v3-turbo`, lấy transcript kèm mốc thời gian. Truyền danh sách thuật ngữ Shopify (Liquid, metafield, checkout extensibility…) qua tham số `prompt` để nhận diện đúng từ chuyên ngành.
  - Lưu vào `item_transcripts`, xóa file audio sau khi xong.
  - Claude tóm tắt transcript: một đoạn tóm tắt tiếng Việt và 3–5 ý chính kèm mốc thời gian. **Cập nhật nội dung item** bằng bản tóm tắt này, rồi chạy lại phân loại AI dựa trên nội dung video thay vì chỉ tiêu đề.
  - Chạy như một hàng đợi riêng sau collector, mỗi video có trạng thái chờ / đang xử lý / xong / lỗi, có thử lại. Không xử lý lại video đã có transcript.
- [x] Chấm điểm: `liên quan (AI) × w1 + tương tác × w2 + số nguồn cùng nhắc × w3 + độ mới × w4`. Trọng số đặt trong config.

**API và dashboard (khoảng 1–1.5 tuần)**

- [x] API:
  - Danh sách item, lọc theo nguồn, tag, cảm xúc, thời gian, chế độ Mới / Đang nổi / Hôm nay.
  - Cập nhật trạng thái và người phụ trách.
  - Thống kê tổng quan.
  - Sức khỏe nguồn.
- [x] Đăng nhập Google, giới hạn trong domain công ty.
- [x] Màn hình:
  - **Tổng quan:** chỉ số tuần (số item mới theo chủ đề, cảm xúc, thay đổi nền tảng còn hạn) và danh sách "Cần xử lý".
  - **Thay đổi nền tảng:** timeline gộp dev changelog, Shopify Changelog và Shopify Editions; lọc theo nguồn; nhãn mức ảnh hưởng, đếm ngược hạn chót, trạng thái (chưa xem / đang xử lý / xong). Mỗi Edition có trang tóm tắt riêng, liệt kê các tính năng liên quan tới theme/app.
  - **Feed:** gộp các nguồn, có bộ lọc và tìm kiếm toàn văn (tìm được cả trong transcript video), nhãn AI, gắn cờ "không liên quan". Video YouTube hiển thị tóm tắt từ nội dung video, các ý chính kèm mốc thời gian (bấm để mở video đúng đoạn đó) và nhãn "Đã nghe nội dung" hoặc "Đang xử lý".
  - **Sức khỏe nguồn:** lần chạy gần nhất, lỗi, số item, và **công cụ đang dùng** cho từng nguồn (theo cách `agent-reach doctor` chọn công cụ). Cảnh báo khi cookie Reddit hoặc X sắp hết hạn. Thêm dòng cho hàng đợi video: số video lấy từ phụ đề, số video qua Groq, số phút audio, số video lỗi.
- [ ] **(Team làm)** Triển khai Docker Compose lên server nội bộ (`docker compose up -d --build`); lịch chạy mặc định mỗi 2 giờ.

**Tiêu chí hoàn thành:**
- Thay đổi nền tảng được phát hiện trong vòng 24 giờ.
- Ít nhất 80% trong top 20 item của Feed là thông tin có ích.
- Team mở dashboard hằng ngày.

### Giai đoạn 2: AI Insights (1–1.5 tuần)

- [x] Báo cáo tuần tự động, lưu lại để xem lịch sử: cơ hội, rủi ro, việc cần làm.
- [x] Trang Cài đặt: sửa từ khóa, nguồn, chủ đề quan tâm. Chuyển cấu hình từ file vào DB.
- [x] Theo dõi chi phí token Claude (đọc `usage` của từng lần gọi, tổng hợp theo ngày và theo tác vụ).

## 4. Nguồn lực và chi phí ước tính

- **Nhân sự:** 1 dev backend/data (Python) và 1 dev frontend (Next.js), cộng PM bán thời gian. Hoặc 1 fullstack trong khoảng 8–9 tuần.
- **Chi phí hằng tháng** (ước tính sơ bộ, cần kiểm tra lại giá):

| Hạng mục | Chi phí ước tính |
|---|---|
| Server | $0 (server nội bộ) |
| Claude (`claude-opus-5-5`, $4/$20 mỗi triệu token input/output) | Khoảng $30–70: phân loại ~400–500 item/ngày là phần lớn; tóm tắt video và báo cáo tuần chỉ vài đô. Giảm được bằng prompt caching và Batch API (−50% cho phần gửi qua batch). Nếu cần rẻ hơn nữa, có thể dùng `claude-haiku-5-5` ($0.10/$0.50) riêng cho phân loại, sau khi đo chất lượng |
| Groq Whisper | $0 trong gói miễn phí; vượt thì khoảng $0.04/giờ audio. Video có phụ đề không tốn gì |
| Web search (Exa MCP), Jina Reader | $0 |
| Reddit, X, YouTube (qua `rdt-cli`, `twitter-cli`, `yt-dlp`) | $0 |
| Proxy | Thường không cần vì chạy trên server nội bộ; nếu IP văn phòng bị chặn thì khoảng $1/tháng theo Agent Reach |

## 5. Rủi ro

| Rủi ro | Cách giảm |
|---|---|
| Shopify Community đổi cấu trúc HTML hoặc chặn truy cập | Tần suất thấp, cache, cảnh báo trên trang Sức khỏe nguồn, parser dễ sửa |
| Điều khoản sử dụng (Reddit, X, YouTube, scraping) | Chỉ dùng nội bộ, không phát lại dữ liệu ra ngoài |
| Dữ liệu social nhiều nhiễu | Lọc từ khóa thô trước, AI sau, ngưỡng `min_score`, gắn cờ "không liên quan" để tinh chỉnh |
| Chi phí token tăng | Không phân tích lại item cũ, cắt nội dung, giới hạn số item mỗi lần phân tích |
| Không ai dùng dashboard | Tech lead chịu trách nhiệm xem danh sách "Cần xử lý" hằng ngày và giao việc; báo cáo tuần là đầu vào cho họp sản phẩm |
| Facebook Groups, LinkedIn, TikTok không có API phù hợp | Không đưa vào phạm vi (OpenCLI cần Chrome desktop, không chạy được trên server) |
| Tài khoản Reddit/X dùng cookie bị khóa | Dùng tài khoản riêng cho radar, tần suất thấp; cảnh báo trên trang Sức khỏe nguồn; Reddit có dự phòng qua Exa |
| Công cụ miễn phí bị nền tảng chặn hoặc ngừng phát triển | Mỗi nguồn có danh sách công cụ dự phòng như Agent Reach; ghim version; theo dõi bản cập nhật của Agent Reach để đổi công cụ |
| Exa MCP và Jina Reader miễn phí có giới hạn tần suất, không có cam kết dịch vụ | Chạy theo lô với khoảng nghỉ, cache kết quả; nếu bị giới hạn thường xuyên thì cân nhắc gói trả phí |
| Tải audio YouTube bằng công cụ bên thứ ba có thể trái điều khoản YouTube, và IP server dễ bị YouTube chặn | Đã chấp nhận vì dự án chỉ dùng nội bộ. Vẫn chỉ xử lý video đã lọc, tần suất thấp, xóa audio sau khi xử lý, theo dõi tỉ lệ lỗi trên trang Sức khỏe nguồn |
| Video dài hoặc file audio vượt giới hạn của Groq | Giới hạn độ dài trong config, nén audio, chia đoạn rồi ghép transcript |
| Transcript sai thuật ngữ chuyên ngành | Truyền danh sách thuật ngữ qua tham số `prompt` của Whisper; tóm tắt bằng LLM để giảm ảnh hưởng của lỗi nhỏ |

## 6. Quyết định đã chốt

| Hạng mục | Quyết định |
|---|---|
| Stack | Python (FastAPI, worker) + Next.js (dashboard) + Postgres, chạy bằng Docker Compose |
| AI | Claude (`claude-opus-5-5`) cho phân loại, tóm tắt và báo cáo tuần; Groq chỉ dùng cho speech-to-text |
| Thu thập dữ liệu | Công cụ miễn phí theo Agent Reach (Exa MCP, Jina Reader, `yt-dlp`, `rdt-cli`, `twitter-cli`, `feedparser`, `gh`) |
| Nơi chạy | Server nội bộ |
| Phạm vi sử dụng | Chỉ nội bộ; đã chấp nhận rủi ro điều khoản khi tải audio YouTube và dùng cookie Reddit/X |
| Người phụ trách | Tech lead xem danh sách "Cần xử lý" hằng ngày và giao việc |
| Ngoài phạm vi | App Store, Theme Store, thông báo Slack, theo dõi thương hiệu, MCP/chat hỏi đáp |

## 7. Trạng thái triển khai (15/10/2026)

Code của cả ba giai đoạn đã có trong repo. Cách chạy xem [`README.md`](../README.md).

| Phần | Ở đâu | Đã kiểm tra |
|---|---|---|
| Cấu hình, prompt | `config/` | Test đọc `keywords.txt` thật |
| Schema DB + migration | `radar/models.py`, `migrations/` | Migration chạy trên Postgres 16 |
| Collectors (11 nguồn, có công cụ dự phòng) | `radar/collectors/` | Test với dữ liệu mẫu; CLI `rdt` và `twitter` được gọi đúng cờ |
| Lọc từ khóa (cú pháp TrendRadar) | `radar/filter/keywords.py` | Test |
| Claude: tag, phân loại, tóm tắt video, báo cáo tuần, Batch API | `radar/ai/` | Test với client Claude giả |
| Video: phụ đề → Groq Whisper | `radar/transcribe/` | Test với dữ liệu mẫu |
| Chấm điểm, lịch chạy, `radar doctor` | `radar/scoring.py`, `radar/scheduler.py`, `radar/doctor.py` | Test; `radar doctor` chạy thật |
| API | `api/main.py` | Test; chạy thật trên Postgres |
| Dashboard (8 màn hình, đăng nhập Google) | `web/` | `npm run build`, lint, typecheck; chạy thử với dữ liệu mẫu ở desktop, mobile và dark mode |
| Docker Compose | `docker-compose.yml`, `docker/Dockerfile`, `web/Dockerfile` | Đã build cả hai image và chạy đủ 4 container (postgres, api, worker, web): migration, các trang web, proxy, `radar doctor`, một lượt `radar run`. Môi trường phát triển chặn kho gói Debian và GitHub, nên bản build thử thay `apt install ffmpeg` bằng ffmpeg tĩnh và lấy `rdt-cli` 0.4.1 từ PyPI; Dockerfile trong repo giữ nguyên |

66 test backend chạy trên cả SQLite và Postgres. CI ở `.github/workflows/ci.yml`.

**Chưa kiểm tra được với dữ liệu thật:** môi trường phát triển bị chặn mạng tới Shopify, Reddit, X, YouTube, Exa, Jina, Hacker News và Groq, và không có Anthropic API key. Lần chạy đầu trên server nội bộ cần xem kỹ trang Sức khỏe nguồn. Riêng Shopify Changelog, Shopify Editions và Shopify Community, cách tách nội dung trang có thể cần chỉnh theo HTML thật (`link_pattern`, cách tách heading).

**Team cần làm để chạy thật:**
1. Điền `.env`: `ANTHROPIC_API_KEY`, `GROQ_API_KEY`, `RADAR_API_TOKEN`, Google OAuth, `ALLOWED_EMAIL_DOMAINS`, `NEXTAUTH_URL`, cookie X; chép `credential.json` của `rdt-cli` vào `secrets/rdt-cli/`.
2. Dán URL RSS của Google Alerts vào `config/sources.yaml` (nguồn `google-alerts`).
3. `docker compose up -d --build` trên server nội bộ, rồi chạy `docker compose exec worker radar doctor --network` và `radar run`.
4. Sau 1–2 tuần, đánh giá theo tiêu chí hoàn thành (mục 3) và chỉnh `keywords.txt`, `interests.txt` trên trang Cài đặt.

**Khác với plan ban đầu:**
- Exa MCP được gọi bằng MCP client của Python, không cần `mcporter` (Node).
- GitHub releases đọc qua Atom feed, không cần `gh`.
- Phần tải và chia audio viết lại theo cách của `agent_reach/transcribe.py` thay vì import, vì cần mốc thời gian từ Groq.
- Nguồn YouTube đặt `keyword_filter: false`: tiêu đề video ít thông tin nên mọi video được gửi cho Claude chấm sơ bộ.
- Trang Chi phí AI tách thành màn hình riêng.
- Trọng tâm chuyển sang theme (quyết định sau khi chạy thử): `interests.txt`, `keywords.txt`, truy vấn và prompt chỉ giữ những gì ảnh hưởng tới theme; thay đổi chỉ dành cho app bị bỏ qua, trừ app block và theme app extension. Nguồn Shopify news vẫn tắt vì là tin doanh nghiệp.
- Thêm sau khi chạy thử thật: chỉ giữ thông tin mới (`freshness.max_age_days`, mặc định 30 ngày; độ mới tính từ ngày đăng thật) và chủ đề ưu tiên (`config/priorities.txt`, sửa trên trang Cài đặt).
