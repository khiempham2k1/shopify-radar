# Shopify Radar

Dashboard nội bộ cho team làm theme (Shopify Theme Store): theo dõi thay đổi nền tảng Shopify, thảo luận trên social và web, rồi dùng Claude để lọc, tóm tắt và viết báo cáo tuần. Radar tập trung vào những gì ảnh hưởng tới theme; thay đổi chỉ dành cho app bị bỏ qua, trừ app block và theme app extension.

Kế hoạch và các quyết định: [`docs/PLAN.md`](docs/PLAN.md).

## Cách hoạt động

```
config/ (sources.yaml, keywords.txt, priorities.txt, interests.txt, terms.txt, prompts/)
        │
radar/collectors (cron) ──▶ Postgres ◀── radar/ai (Claude: tag, phân loại, tóm tắt, báo cáo tuần)
 rss, github, editions,         │  ▲
 reddit, twitter, community,    │  └── radar/transcribe (video YouTube: phụ đề → Groq Whisper → tóm tắt)
 youtube, web_search, hn        ▼
                         api/ (FastAPI) ──▶ web/ (Next.js, đăng nhập Google)
```

Mỗi lần chạy (mặc định mỗi 2 giờ, xem `schedule.collect` trong `config/sources.yaml`):

0. **Ưu tiên nguồn chính thức.** Mọi nguồn nền tảng (changelog, Editions, GitHub của Shopify, @ShopifyDevs/@ShopifyEng/@Shopify) và trang trên domain của Shopify (shopify.dev, help.shopify.com…, xem `official` trong `sources.yaml`) là nguồn chính thức: thu thập trước, luôn là bản được giữ khi trùng (bản Reddit/X có trước sẽ chuyển thành "Cũng có trên"), xếp trước trong danh sách, được cộng `scoring.official_boost`, và là căn cứ khi Claude phân loại và viết báo cáo. Feed hiện nhãn "✓ Chính thức".
1. **Thu thập.** Mỗi nguồn có danh sách công cụ theo thứ tự ưu tiên, theo cách của [Agent Reach](https://github.com/Panniantong/agent-reach): Exa MCP cho web search, Jina Reader để đọc trang, `yt-dlp` cho YouTube, `rdt-cli` cho Reddit (dự phòng bằng Exa), `twitter-cli` cho X. Công cụ chính lỗi thì chuyển sang công cụ dự phòng và báo trên trang Sức khỏe nguồn.
   Tài khoản chính thức trên X (@ShopifyDevs, @ShopifyEng, @Shopify) là nguồn `x-official`, hiện ở trang Thay đổi nền tảng. **Không lưu trùng:** cùng một bài (cùng URL, cùng tweet, retweet; với tài khoản chính thức thì cả cùng nội dung hoặc cùng link tới một trang cụ thể) chỉ giữ một dòng, ghi "Đăng bởi" các tài khoản và "Cũng có trên" các nguồn khác. Tweet chỉ trỏ tới bài changelog đã có thì gắn vào bài đó. Bài thảo luận (Reddit, Community…) có link tới một thay đổi vẫn là dòng riêng vì đó là thông tin mới.
2. **Chỉ giữ thông tin mới.** Bài/video đăng trước `freshness.max_age_days` (mặc định 30 ngày, từng nguồn đặt riêng được) bị bỏ ngay khi thu thập. Item cũ đã lưu từ trước bị xóa ở lần chạy sau, trừ item đang có người xử lý. YouTube và web search bỏ cả kết quả không rõ ngày đăng (`drop_undated`).
3. **Chủ đề ưu tiên** (`config/priorities.txt`, ví dụ `Shopify Canvas`). Mỗi chủ đề được tìm thêm trên mọi nguồn có `queries`. Item nhắc tới chủ đề luôn hiển thị, được cộng `scoring.priority_boost` điểm, có nhãn ★, đứng đầu trang Tổng quan và luôn có trong báo cáo tuần.
4. **Lọc từ khóa** theo cú pháp của TrendRadar (`config/keywords.txt`). Item của nguồn nền tảng luôn được gửi cho Claude.
5. **Claude phân loại** theo lô (`claude-opus-5-5`, effort `low`). Kết quả gồm tag lấy từ `interests.txt`, điểm liên quan, cảm xúc, **ảnh hưởng tới ai** (Theme: code theme; Partner: công ty với tư cách nhà bán theme trên Theme Store; Merchant: người dùng theme), mức ảnh hưởng, hạn chót và tóm tắt tiếng Việt. Thay đổi chỉ dành cho app và headless (Hydrogen) bị bỏ qua; Storefront API chỉ giữ khi theme dùng tới. Mỗi item chỉ gửi một lần. Lô nào lỗi thì item vẫn hiển thị nhờ khớp từ khóa và được gửi lại ở lần chạy sau.
6. **Video YouTube** lấy phụ đề trước. Không có phụ đề mới dùng Groq Whisper, với nhiều key trong `GROQ_API_KEYS` dùng xoay vòng: key bị giới hạn tạm nghỉ đúng thời gian Groq báo, đoạn audio đang dở gửi lại bằng key khác; hết key thì video chờ lần chạy sau. Trạng thái từng key (admin) ở trang Sức khỏe nguồn. Claude tóm tắt (effort `medium`), bản tóm tắt thay cho nội dung item, rồi item được phân loại lại.
7. **Chấm điểm** 0–10 dựa trên mức liên quan, tương tác, số nguồn cùng nhắc và độ mới (tính từ ngày đăng thật). Feed xếp theo **độ hot** (0–10): mức tương tác so với các bài cùng nguồn (để view YouTube không lấn át upvote Reddit), cộng thêm khi nhiều nguồn cùng nhắc, giảm một nửa sau mỗi `scoring.hot_half_life_hours` (mặc định 24 giờ). Có thể chuyển sang xếp theo mức liên quan hoặc mới nhất.
8. **Báo cáo tuần** chạy sáng thứ Hai (effort `high`).

## Quyền xem

- **Giai đoạn 1** (Tổng quan, Thay đổi nền tảng, Feed, Sức khỏe nguồn): ai mở được dashboard đều xem được, không cần đăng nhập, và không thấy link đăng nhập.
- **Chỉ quản trị đăng nhập:** các email trong `PHASE2_EMAILS` (ngăn bằng dấu phẩy) mở thẳng `/login`, đăng nhập Google. Tài khoản khác bị từ chối. Quản trị thấy Giai đoạn 2 (Báo cáo tuần, Cài đặt, Chi phí AI), nút "Không liên quan" và chi tiết kỹ thuật. API cũng chặn theo danh sách này, không chỉ ẩn menu.
- Trang công khai không hiện chi tiết kỹ thuật (tên công cụ, lỗi chi tiết, cấu hình, DB). Tài khoản Giai đoạn 2 vẫn thấy cột "Công cụ đang dùng" và lỗi chi tiết ở Sức khỏe nguồn; trạng thái đăng nhập Reddit/X nằm ở trang Cài đặt.
- `AUTH_DISABLED=true` (chỉ dùng khi chạy local) mở mọi trang, kể cả Giai đoạn 2.

## Chạy trên server nội bộ

```bash
cp .env.example .env          # điền ANTHROPIC_API_KEY, GROQ_API_KEY, RADAR_API_TOKEN, Google OAuth...
# Cookie Reddit của tài khoản riêng cho radar: chép credential.json của rdt-cli vào secrets/rdt-cli/
docker compose up -d --build
docker compose exec worker radar doctor --network   # kiểm tra công cụ, đăng nhập, kết nối
docker compose exec worker radar run                # chạy một lần ngay, không chờ lịch
```

Dashboard ở cổng 3000. API và Postgres chỉ mở trong mạng nội bộ của docker compose.

Nếu sửa lịch chạy (`schedule`) trên trang Cài đặt, cần khởi động lại worker (`docker compose restart worker`). Các thay đổi khác (nguồn, từ khóa, chủ đề) có hiệu lực từ lần chạy sau.

## Lệnh của worker

| Lệnh | Việc |
|---|---|
| `radar migrate` | Áp dụng migration DB (Alembic) |
| `radar run [--source ID]` | Chạy một lượt đầy đủ |
| `radar collect` / `classify` / `videos` / `score` | Chạy từng bước |
| `radar report` | Viết báo cáo tuần trước ngay |
| `radar doctor [--network]` | Kiểm tra công cụ, cookie, key |
| `radar scheduler` | Chạy theo lịch (lệnh mặc định của worker) |

## Chạy trên máy (local)

Cần Python 3.12 trở lên (`python3 --version`; trên Mac: `brew install python@3.12`) và Node.js 22. Muốn lấy dữ liệu thật thì cần thêm `ffmpeg` (`brew install ffmpeg`).

**1. Backend** (ở thư mục gốc của repo, không phải `web/`):

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env        # điền ANTHROPIC_API_KEY, GROQ_API_KEY nếu muốn chạy thật
radar migrate               # tạo DB SQLite ở .data/radar.db
python -m radar.demo        # (tùy chọn) nạp dữ liệu mẫu để xem dashboard
python -m uvicorn api.main:app --port 8000
```

`radar` và API tự đọc file `.env` ở thư mục gốc. Lệnh `radar` chỉ có khi virtualenv đang bật (`source .venv/bin/activate`).

**2. Dashboard** (terminal khác):

```bash
cd web
cp .env.example .env        # sửa: RADAR_API_URL=http://127.0.0.1:8000 và AUTH_DISABLED=true
npm ci && npm run dev       # mở http://localhost:3000
```

**3. Lấy dữ liệu thật** (terminal backend, virtualenv đang bật):

```bash
pip install "twitter-cli @ git+https://github.com/jackwener/twitter-cli.git@7c634e0d396b1e7af9f63315b414925fe4f29ae7" "rdt-cli @ git+https://github.com/public-clis/rdt-cli.git@5e4fb3720d5c174e976cd425ccc3b879d52cac66"
radar doctor --network      # xem công cụ nào chạy được, thiếu key/cookie gì
radar run                   # thu thập, phân loại, nghe video, chấm điểm
```

Nguồn nào lỗi (thiếu cookie Reddit/X, thiếu key) chỉ báo trên trang Sức khỏe nguồn, các nguồn khác vẫn chạy.

Sau khi đổi nhiều ở `interests.txt` (trọng tâm của radar), chạy `radar classify --reset` để bỏ tag và kết quả cũ, rồi phân loại lại các item gần đây theo nội dung mới.

## Phát triển

```bash
pip install -e ".[dev]"
python -m pytest                              # SQLite
TEST_DATABASE_URL=postgresql+psycopg://... python -m pytest   # Postgres
```

Cấu trúc:

- `radar/collectors/`: một file cho mỗi nhóm nguồn. Thêm nguồn mới bằng cách viết một lớp `Collector` có các hàm `fetch_<backend>`.
- `radar/filter/keywords.py`: cú pháp từ khóa.
- `radar/ai/`: client Claude (structured outputs, prompt caching, server-side fallback, Message Batches), tag, phân loại, báo cáo tuần.
- `radar/transcribe/`: phụ đề, Groq Whisper, hàng đợi video.
- `api/main.py`: API cho dashboard.
- `web/`: dashboard Next.js.
- `migrations/`: Alembic.
