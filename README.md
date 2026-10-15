# Shopify Radar

Dashboard nội bộ cho team làm theme (Shopify Theme Store) và app (Shopify App): theo dõi thay đổi nền tảng Shopify, thảo luận trên social và web, rồi dùng Claude để lọc, tóm tắt và viết báo cáo tuần.

Kế hoạch và các quyết định: [`docs/PLAN.md`](docs/PLAN.md).

## Cách hoạt động

```
config/ (sources.yaml, keywords.txt, interests.txt, terms.txt, prompts/)
        │
radar/collectors (cron) ──▶ Postgres ◀── radar/ai (Claude: tag, phân loại, tóm tắt, báo cáo tuần)
 rss, github, editions,         │  ▲
 reddit, twitter, community,    │  └── radar/transcribe (video YouTube: phụ đề → Groq Whisper → tóm tắt)
 youtube, web_search, hn        ▼
                         api/ (FastAPI) ──▶ web/ (Next.js, đăng nhập Google)
```

Mỗi lần chạy (mặc định mỗi 2 giờ, xem `schedule.collect` trong `config/sources.yaml`):

1. **Thu thập.** Mỗi nguồn có danh sách công cụ theo thứ tự ưu tiên, theo cách của [Agent Reach](https://github.com/Panniantong/agent-reach): Exa MCP cho web search, Jina Reader để đọc trang, `yt-dlp` cho YouTube, `rdt-cli` cho Reddit (dự phòng bằng Exa), `twitter-cli` cho X. Công cụ chính lỗi thì chuyển sang công cụ dự phòng và báo trên trang Sức khỏe nguồn.
2. **Lọc từ khóa** theo cú pháp của TrendRadar (`config/keywords.txt`). Item của nguồn nền tảng luôn được gửi cho Claude.
3. **Claude phân loại** theo lô (`claude-opus-5-5`, effort `low`). Kết quả gồm tag lấy từ `interests.txt`, điểm liên quan, cảm xúc, mức ảnh hưởng, hạn chót và tóm tắt tiếng Việt. Mỗi item chỉ gửi một lần. Lô nào lỗi thì item vẫn hiển thị nhờ khớp từ khóa và được gửi lại ở lần chạy sau.
4. **Video YouTube** lấy phụ đề trước. Không có phụ đề mới dùng Groq Whisper. Claude tóm tắt (effort `medium`), bản tóm tắt thay cho nội dung item, rồi item được phân loại lại.
5. **Chấm điểm** 0–10 dựa trên mức liên quan, tương tác, số nguồn cùng nhắc và độ mới.
6. **Báo cáo tuần** chạy sáng thứ Hai (effort `high`).

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
