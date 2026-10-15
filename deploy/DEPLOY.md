# Triển khai Shopify Radar lên VPS

Kết quả: dashboard chạy ở `https://<domain>` với HTTPS tự động (Caddy + Let's Encrypt). API và Postgres chỉ nằm trong mạng nội bộ của Docker, không mở ra Internet. Worker tự chạy thu thập, phân loại mỗi 2 giờ và báo cáo tuần sáng thứ Hai.

```
Internet ──443──▶ caddy ──▶ web (Next.js) ──▶ api (FastAPI) ──▶ postgres
                                              worker (radar scheduler) ──┘
```

## 0. Chuẩn bị

| Cần có | Ghi chú |
|---|---|
| VPS Ubuntu 22.04/24.04 (hoặc Debian 12) | Tối thiểu 2 vCPU, 2 GB RAM (script tự thêm 2 GB swap), 30 GB ổ. Khuyên 4 GB RAM nếu nghe nhiều video. |
| Domain hoặc subdomain | Tạo bản ghi **A** trỏ về IP VPS, ví dụ `radar.congty.com`. Đợi DNS cập nhật trước bước chạy. |
| Quyền đọc repo | Repo private: dùng [deploy key](https://docs.github.com/en/authentication/connecting-to-github-with-ssh/managing-deploy-keys) (chỉ đọc) hoặc Personal Access Token. |
| Các key và cookie | `ANTHROPIC_API_KEY`, `GROQ_API_KEYS`, Google OAuth client, cookie X, token Discord, `credential.json` của rdt-cli (lấy từ máy bạn đang chạy local). |

**IP datacenter có thể bị chặn.** YouTube đôi khi đòi "Sign in to confirm you're not a bot", Reddit hoặc X có thể trả 403 với IP của nhà cung cấp VPS. Trang Sức khỏe nguồn sẽ báo nguồn nào lỗi. Nếu gặp, đặt `RADAR_HTTP_PROXY` (proxy residential) trong `.env`.

## 1. Lấy code

```bash
ssh root@<ip-vps>
git clone -b claude/eloquent-gates-ck1hj2 git@github.com:khiempham2k1/test-project.git /opt/radar
cd /opt/radar
```

## 2. Chạy script cài đặt (một lần)

```bash
sudo bash deploy/setup-vps.sh radar.congty.com
```

Script cài Docker, bật firewall (chỉ mở SSH, 80, 443), thêm swap nếu máy ít RAM, và tạo `.env` với mật khẩu Postgres, `RADAR_API_TOKEN`, `NEXTAUTH_SECRET` ngẫu nhiên, `DOMAIN`, `NEXTAUTH_URL=https://<domain>`. Chạy lại không ghi đè giá trị đã có.

## 3. Điền `.env`

```bash
nano .env
```

| Biến | Lấy ở đâu |
|---|---|
| `ANTHROPIC_API_KEY` | console.anthropic.com |
| `GROQ_API_KEYS` | console.groq.com, nhiều key ngăn bằng dấu phẩy |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | Google Cloud Console → APIs & Services → Credentials (bước 4) |
| `PHASE2_EMAILS` | Email admin được đăng nhập, ngăn bằng dấu phẩy |
| `TWITTER_AUTH_TOKEN`, `TWITTER_CT0` | Cookie x.com của tài khoản radar (giống lúc chạy local) |
| `DISCORD_TOKEN` | Token tài khoản Discord của radar (giống lúc chạy local) |
| `RADAR_HTTP_PROXY` | Để trống, chỉ điền khi nguồn bị chặn IP |

Không đổi `AUTH_DISABLED` (phải là `false` trên VPS).

## 4. Google OAuth

Trong OAuth client (loại *Web application*):
- **Authorized JavaScript origins:** `https://radar.congty.com`
- **Authorized redirect URIs:** `https://radar.congty.com/api/auth/callback/google`

## 5. Cookie Reddit

Chép `credential.json` của rdt-cli từ máy local lên VPS:

```bash
# chạy trên máy local
scp ~/.config/rdt-cli/credential.json root@<ip-vps>:/opt/radar/secrets/rdt-cli/
```

## 6. Cấu hình nguồn

Container dùng file trong `config/` của repo. Nếu lúc chạy local bạn đã sửa cấu hình **trên trang Cài đặt** (lưu trong DB local), các thay đổi đó không theo lên VPS. Bạn có hai cách:
- Đưa thay đổi (kênh Discord, từ khóa, `priorities.txt`…) vào file trong `config/`, commit và push, rồi `git pull` trên VPS; hoặc
- Sau khi chạy, đăng nhập admin và nhập lại trên trang Cài đặt.

## 7. Khởi động

```bash
docker compose up -d --build        # lần đầu build mất 5–10 phút
docker compose ps                   # postgres, api, web, worker, caddy: running (healthy)
docker compose logs -f worker       # xem lần chạy đầu: thu thập → phân loại → chấm điểm
```

Worker chạy `radar doctor` rồi chạy một lượt ngay khi khởi động, sau đó theo lịch trong `sources.yaml`.

Kiểm tra công cụ và đăng nhập:

```bash
docker compose exec worker radar doctor --network
```

Mở `https://radar.congty.com`. Admin đăng nhập ở `https://radar.congty.com/login`.

## Vận hành

| Việc | Lệnh |
|---|---|
| Xem log | `docker compose logs -f worker` (hoặc `api`, `web`, `caddy`) |
| Chạy ngay một lượt | `docker compose exec worker radar run` |
| Phân loại lại theo cấu hình mới | `docker compose exec worker radar classify --reset` |
| Tóm tắt cộng đồng ngay | `docker compose exec worker radar digest` |
| Tra một bài | `docker compose exec worker radar find "carts/update"` |
| Khởi động lại | `docker compose restart` |
| Cập nhật code mới | `bash deploy/update.sh` |
| Sửa `.env` | `nano .env` rồi `docker compose up -d` (tạo lại container nhận biến mới) |

### Sao lưu tự động

```bash
bash deploy/backup.sh                      # thử một lần: tạo backups/radar-YYYYmmdd-HHMM.sql.gz
crontab -e
# thêm dòng: sao lưu 3:17 sáng mỗi ngày, giữ 14 ngày
17 3 * * * cd /opt/radar && bash deploy/backup.sh >> backups/backup.log 2>&1
```

Nên chép thư mục `backups/` sang nơi khác định kỳ (S3, Google Drive, máy khác).

### Khôi phục từ bản sao lưu

```bash
docker compose stop api worker web
gunzip -c backups/radar-YYYYmmdd-HHMM.sql.gz | docker compose exec -T postgres psql -U radar -d radar -v ON_ERROR_STOP=1 \
  -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;" -f -
docker compose start api worker web
```

### Cookie và token hết hạn

Trang **Sức khỏe nguồn** (khi đăng nhập admin) hiện trạng thái công cụ và đăng nhập Reddit, X, Discord; `docker compose exec worker radar doctor` cũng kiểm tra được. Khi báo hết hạn:
- **Reddit:** chép `credential.json` mới vào `secrets/rdt-cli/`.
- **X / Discord:** sửa `.env`, rồi chạy `docker compose up -d worker`.

## Sự cố thường gặp

| Hiện tượng | Nguyên nhân và cách sửa |
|---|---|
| Không vào được HTTPS, log caddy báo lỗi chứng chỉ | DNS chưa trỏ đúng IP, hoặc cổng 80/443 bị chặn ở firewall của nhà cung cấp VPS. Kiểm tra `dig +short radar.congty.com` |
| `502 Bad Gateway` | Web chưa sẵn sàng: `docker compose ps`, `docker compose logs web api` |
| Đăng nhập Google báo `redirect_uri_mismatch` | Redirect URI ở bước 4 phải khớp chính xác `https://<domain>/api/auth/callback/google` |
| Đăng nhập xong vẫn không thấy Giai đoạn 2 | Email chưa có trong `PHASE2_EMAILS`, sửa `.env` rồi `docker compose up -d web` |
| Build dừng vì hết RAM | Kiểm tra swap: `swapon --show`; chạy lại `sudo bash deploy/setup-vps.sh <domain>` |
| YouTube/Reddit/X lỗi 403 hoặc "not a bot" | IP VPS bị chặn: đặt `RADAR_HTTP_PROXY`, hoặc chấp nhận dùng nguồn dự phòng (Reddit tự chuyển sang Exa khi rdt-cli lỗi) |
