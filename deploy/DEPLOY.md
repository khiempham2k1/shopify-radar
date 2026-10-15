# Triển khai Shopify Radar lên VPS

Có hai cách chạy:

| | Chạy bằng IP (mặc định) | Có domain |
|---|---|---|
| Địa chỉ | `http://<ip-vps>:3000` (đổi cổng được) | `https://radar.congty.com` |
| Lệnh cài | `sudo bash deploy/setup-vps.sh` | `sudo bash deploy/setup-vps.sh radar.congty.com` |
| Admin đăng nhập | Email trong `PHASE2_EMAILS` + `ADMIN_PASSWORD` | Mật khẩu như bên trái, hoặc Google |
| Mã hóa | Không (HTTP) | HTTPS tự động (Caddy + Let's Encrypt) |

Ở cả hai cách, API và Postgres chỉ nằm trong mạng nội bộ của Docker, không mở ra Internet. Worker tự chạy thu thập, phân loại mỗi 2 giờ và viết báo cáo tuần sáng thứ Hai. Sau này có domain thì chạy lại script cài đặt với domain là chuyển sang HTTPS, không mất dữ liệu.

**Chạy bằng IP thì Google không đăng nhập được**, vì Google chỉ nhận địa chỉ trả về là domain HTTPS. Admin đăng nhập bằng mật khẩu. Kết nối HTTP không mã hóa, nên đừng dùng lại mật khẩu này ở nơi khác, và nên chuyển sang domain khi có thể.

```
Chạy bằng IP:  Internet ──:3000──▶ web (Next.js) ──▶ api (FastAPI) ──▶ postgres
Có domain:     Internet ──443──▶ caddy ──▶ web ──▶ api ──▶ postgres
                                            worker (radar scheduler) ──┘
```

## 0. Chuẩn bị

| Cần có | Ghi chú |
|---|---|
| VPS Ubuntu 22.04/24.04 (hoặc Debian 12) | Tối thiểu 2 vCPU, 2 GB RAM (script tự thêm 2 GB swap), 30 GB ổ. Khuyên 4 GB RAM nếu nghe nhiều video. |
| Cổng mở ở nhà cung cấp | Nhiều nhà cung cấp (AWS, GCP, Vultr…) có firewall riêng ngoài VPS: mở cổng 3000 (cách IP) hoặc 80/443 (cách domain). |
| Domain (chỉ cách domain) | Tạo bản ghi **A** trỏ về IP VPS, ví dụ `radar.congty.com`. Đợi DNS cập nhật trước bước chạy. |
| Quyền đọc repo | Repo private: dùng [deploy key](https://docs.github.com/en/authentication/connecting-to-github-with-ssh/managing-deploy-keys) (chỉ đọc) hoặc Personal Access Token. |
| Các key và cookie | `ANTHROPIC_API_KEY`, `GROQ_API_KEYS`, cookie X, token Discord, `credential.json` của rdt-cli (lấy từ máy bạn đang chạy local). Google OAuth client nếu dùng domain và muốn đăng nhập Google. |

**IP datacenter có thể bị chặn.** YouTube đôi khi đòi "Sign in to confirm you're not a bot", Reddit hoặc X có thể trả 403 với IP của nhà cung cấp VPS. Trang Sức khỏe nguồn sẽ báo nguồn nào lỗi. Nếu gặp, đặt `RADAR_HTTP_PROXY` (proxy residential) trong `.env`.

## 1. Lấy code

```bash
ssh root@<ip-vps>
git clone -b main git@github.com:khiempham2k1/test-project.git /opt/radar
cd /opt/radar
```

## 2. Chạy script cài đặt (một lần)

```bash
sudo bash deploy/setup-vps.sh                    # chạy bằng IP, cổng 3000 (tự tìm IP public)
sudo bash deploy/setup-vps.sh :8080              # chạy bằng IP, cổng 8080
sudo bash deploy/setup-vps.sh radar.congty.com   # có domain, HTTPS
```

Script làm các việc sau:
- cài Docker;
- bật firewall, chỉ mở SSH và cổng dashboard (hoặc 80/443 khi có domain);
- thêm swap nếu máy ít RAM;
- tạo `.env` với mật khẩu Postgres, `RADAR_API_TOKEN`, `NEXTAUTH_SECRET` và **`ADMIN_PASSWORD`** ngẫu nhiên, cùng `NEXTAUTH_URL` đúng địa chỉ truy cập.

Cuối cùng script in ra địa chỉ và mật khẩu admin. Chạy lại không đổi các secret đã có; chạy lại với tham số khác là đổi giữa IP và domain.

## 3. Điền `.env`

```bash
nano .env
```

| Biến | Lấy ở đâu |
|---|---|
| `ANTHROPIC_API_KEY` | console.anthropic.com |
| `GROQ_API_KEYS` | console.groq.com, nhiều key ngăn bằng dấu phẩy |
| `PHASE2_EMAILS` | Email admin được đăng nhập, ngăn bằng dấu phẩy |
| `ADMIN_PASSWORD` | Script đã tạo sẵn; muốn đổi thì sửa ở đây |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | Chỉ khi có domain và muốn đăng nhập Google (bước 4); để trống thì trang đăng nhập chỉ có mật khẩu |
| `TWITTER_AUTH_TOKEN`, `TWITTER_CT0` | Cookie x.com của tài khoản radar (giống lúc chạy local) |
| `DISCORD_TOKEN` | Token tài khoản Discord của radar (giống lúc chạy local) |
| `RADAR_HTTP_PROXY` | Để trống, chỉ điền khi nguồn bị chặn IP |

Không đổi `AUTH_DISABLED` (phải là `false` trên VPS), `NEXTAUTH_URL`, `WEB_PORT`, `COMPOSE_FILE`: script đặt các biến này theo cách chạy.

## 4. Google OAuth (chỉ khi có domain, tùy chọn)

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

Mở `http://<ip-vps>:3000` (hoặc `https://radar.congty.com`). Admin mở thẳng `/login`, ví dụ `http://<ip-vps>:3000/login`, rồi đăng nhập bằng email trong `PHASE2_EMAILS` và `ADMIN_PASSWORD`. Sai mật khẩu 10 lần thì email đó bị khóa đăng nhập 15 phút.

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
| Không mở được `http://<ip>:3000` | `docker compose ps` xem web có `healthy` không; kiểm tra firewall của nhà cung cấp VPS đã mở cổng; `curl -I http://127.0.0.1:3000/login` ngay trên VPS |
| Đăng nhập xong bị đưa về `localhost` hoặc địa chỉ khác | `NEXTAUTH_URL` trong `.env` phải đúng địa chỉ bạn mở trên trình duyệt (kể cả cổng). Sửa rồi `docker compose up -d web` |
| Báo "Email hoặc mật khẩu không đúng" | Email phải nằm trong `PHASE2_EMAILS`; mật khẩu xem `grep ADMIN_PASSWORD .env`. Sửa `.env` thì chạy `docker compose up -d web` |
| Không vào được HTTPS, log caddy báo lỗi chứng chỉ | DNS chưa trỏ đúng IP, hoặc cổng 80/443 bị chặn ở firewall của nhà cung cấp VPS. Kiểm tra `dig +short radar.congty.com` |
| `502 Bad Gateway` | Web chưa sẵn sàng: `docker compose ps`, `docker compose logs web api` |
| Đăng nhập Google báo `redirect_uri_mismatch` | Redirect URI ở bước 4 phải khớp chính xác `https://<domain>/api/auth/callback/google` |
| Đăng nhập xong vẫn không thấy Giai đoạn 2 | Email chưa có trong `PHASE2_EMAILS`, sửa `.env` rồi `docker compose up -d web` |
| Build dừng vì hết RAM | Kiểm tra swap: `swapon --show`; chạy lại `sudo bash deploy/setup-vps.sh` (cùng tham số lúc cài) |
| YouTube/Reddit/X lỗi 403 hoặc "not a bot" | IP VPS bị chặn: đặt `RADAR_HTTP_PROXY`, hoặc chấp nhận dùng nguồn dự phòng (Reddit tự chuyển sang Exa khi rdt-cli lỗi) |
