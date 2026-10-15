#!/usr/bin/env bash
# Chuẩn bị VPS Ubuntu/Debian mới cho Shopify Radar. Chạy MỘT lần, bằng root hoặc sudo,
# từ thư mục repo đã clone. Hai cách:
#
#   sudo bash deploy/setup-vps.sh                    # chạy bằng IP: http://<ip-vps>:3000
#   sudo bash deploy/setup-vps.sh :8080              # chạy bằng IP, cổng khác
#   sudo bash deploy/setup-vps.sh radar.congty.com   # có domain: https://radar.congty.com (Caddy)
#
# Script làm:
#   1. cài Docker (nếu chưa có);
#   2. bật firewall: chỉ mở SSH và cổng dashboard (hoặc 80/443 khi có domain);
#   3. tạo swap 2 GB nếu máy ít RAM (build dashboard cần ~2 GB);
#   4. tạo .env từ .env.example với mật khẩu/secret ngẫu nhiên, mật khẩu admin, địa chỉ truy cập;
#   5. tạo thư mục secrets/ và backups/.
# Script không ghi đè secret đã có trong .env; chạy lại an toàn, và chạy lại với tham số khác
# để đổi giữa IP và domain.
set -euo pipefail

TARGET="${1:-}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

if [[ $EUID -ne 0 ]]; then
  echo "Cần chạy bằng root: sudo bash deploy/setup-vps.sh [domain | ip:cổng | :cổng]" >&2
  exit 1
fi
TARGET="${TARGET#http://}"; TARGET="${TARGET#https://}"; TARGET="${TARGET%%/*}"

HOST="${TARGET%%:*}"
PORT=""
[[ "$TARGET" == *:* ]] && PORT="${TARGET##*:}"
if [[ -z "$HOST" || "$HOST" =~ ^[0-9]+(\.[0-9]+){3}$ ]]; then
  MODE=ip
  PORT="${PORT:-3000}"
  [[ "$PORT" =~ ^[0-9]+$ ]] || { echo "Cổng không hợp lệ: $PORT" >&2; exit 1; }
  if [[ -z "$HOST" ]]; then
    HOST="$(curl -fsS --max-time 5 https://api.ipify.org 2>/dev/null || hostname -I | awk '{print $1}')"
  fi
  URL="http://${HOST}:${PORT}"
else
  MODE=domain
  URL="https://${HOST}"
fi
echo "Dashboard sẽ ở: ${URL}"

echo "==> 1. Docker"
if ! command -v docker >/dev/null 2>&1; then
  apt-get update -y
  apt-get install -y ca-certificates curl
  curl -fsSL https://get.docker.com | sh
fi
systemctl enable --now docker
docker compose version

echo "==> 2. Firewall"
if ! command -v ufw >/dev/null 2>&1; then apt-get install -y ufw; fi
ufw allow OpenSSH >/dev/null
if [[ "$MODE" == domain ]]; then
  ufw allow 80/tcp >/dev/null
  ufw allow 443/tcp >/dev/null
  ufw allow 443/udp >/dev/null
else
  ufw allow "${PORT}/tcp" >/dev/null
fi
ufw --force enable >/dev/null
ufw status | head -n 12

echo "==> 3. Swap"
mem_mb=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
if [[ "$mem_mb" -lt 4000 ]] && ! swapon --show | grep -q .; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
  echo "Đã tạo swap 2 GB (RAM ${mem_mb} MB)"
else
  echo "Không cần swap (RAM ${mem_mb} MB hoặc đã có swap)"
fi

echo "==> 4. File .env"
[[ -f .env ]] || cp .env.example .env
chmod 600 .env
# set_env KEY VALUE: set KEY only when it is missing or empty in .env (secrets are kept).
# put_env KEY VALUE: always set KEY (values derived from how the server is reached).
set_env() {
  local key="$1" value="$2"
  if grep -qE "^${key}=.+" .env; then return; fi
  put_env "$key" "$value"
}
put_env() {
  local key="$1" value="$2"
  if grep -qE "^#? ?${key}=" .env; then
    sed -i -E "s|^#? ?${key}=.*|${key}=${value}|" .env
  else
    echo "${key}=${value}" >> .env
  fi
  echo "  đặt ${key}"
}
# Placeholder in .env.example counts as unset.
sed -i 's|^POSTGRES_PASSWORD=doi-mat-khau-nay$|POSTGRES_PASSWORD=|' .env
set_env POSTGRES_PASSWORD "$(openssl rand -hex 24)"
set_env RADAR_API_TOKEN "$(openssl rand -hex 32)"
set_env NEXTAUTH_SECRET "$(openssl rand -base64 32 | tr -d '\n')"
set_env ADMIN_PASSWORD "$(openssl rand -base64 18 | tr -d '\n/+=')"
put_env NEXTAUTH_URL "$URL"
put_env AUTH_DISABLED false
if [[ "$MODE" == domain ]]; then
  put_env DOMAIN "$HOST"
  put_env COMPOSE_FILE "docker-compose.yml:deploy/docker-compose.vps.yml:deploy/docker-compose.https.yml"
else
  put_env WEB_PORT "$PORT"
  put_env COMPOSE_FILE "docker-compose.yml:deploy/docker-compose.vps.yml"
fi

echo "==> 5. Thư mục"
mkdir -p secrets/rdt-cli secrets/youtube backups
chmod 700 secrets backups
# Run with sudo: hand the files back to the user who called it, and let that user run docker.
if [[ -n "${SUDO_USER:-}" && "$SUDO_USER" != root ]]; then
  chown "$SUDO_USER": .env
  chown -R "$SUDO_USER": secrets backups
  if ! id -nG "$SUDO_USER" | grep -qw docker; then
    usermod -aG docker "$SUDO_USER"
    echo "  đã thêm ${SUDO_USER} vào nhóm docker: đăng xuất SSH rồi vào lại để dùng lệnh docker không cần sudo"
  fi
fi

ADMIN_PASSWORD_VALUE="$(grep -E '^ADMIN_PASSWORD=' .env | cut -d= -f2-)"
if [[ "$MODE" == domain ]]; then
  GOOGLE_NOTE="  Google OAuth (tùy chọn): redirect URI  ${URL}/api/auth/callback/google"
else
  GOOGLE_NOTE="  Chạy bằng IP thì Google không cho đăng nhập (chỉ nhận domain HTTPS): dùng mật khẩu admin."
fi

cat <<NEXT

Xong phần chuẩn bị. Còn lại (xem deploy/DEPLOY.md):
  1. Điền vào .env: ANTHROPIC_API_KEY, GROQ_API_KEYS, PHASE2_EMAILS (email admin),
     TWITTER_AUTH_TOKEN/TWITTER_CT0, DISCORD_TOKEN          →  nano .env
  2. Chép credential.json của rdt-cli vào secrets/rdt-cli/
  3. Chạy:  docker compose up -d --build
  4. Mở:    ${URL}
     Admin đăng nhập ở ${URL}/login bằng email trong PHASE2_EMAILS và mật khẩu:
        ${ADMIN_PASSWORD_VALUE}
     (lưu trong .env, biến ADMIN_PASSWORD; đổi thì sửa .env rồi: docker compose up -d web)
${GOOGLE_NOTE}
NEXT
