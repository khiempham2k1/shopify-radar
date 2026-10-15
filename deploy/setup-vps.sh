#!/usr/bin/env bash
# Chuẩn bị VPS Ubuntu/Debian mới cho Shopify Radar. Chạy MỘT lần, bằng root hoặc sudo,
# từ thư mục repo đã clone:   sudo bash deploy/setup-vps.sh radar.congty.com
#
# Script làm:
#   1. cài Docker (nếu chưa có);
#   2. bật firewall: chỉ mở SSH, 80, 443;
#   3. tạo swap 2 GB nếu máy ít RAM (build dashboard cần ~2 GB);
#   4. tạo .env từ .env.example với mật khẩu/secret ngẫu nhiên và domain;
#   5. tạo thư mục secrets/ và backups/.
# Script không ghi đè giá trị đã có trong .env; chạy lại an toàn.
set -euo pipefail

DOMAIN="${1:-}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

if [[ $EUID -ne 0 ]]; then
  echo "Cần chạy bằng root: sudo bash deploy/setup-vps.sh <domain>" >&2
  exit 1
fi
if [[ -z "$DOMAIN" ]]; then
  read -rp "Domain cho dashboard (vd. radar.congty.com, đã trỏ A record về IP VPS): " DOMAIN
fi
DOMAIN="${DOMAIN#http://}"; DOMAIN="${DOMAIN#https://}"; DOMAIN="${DOMAIN%%/*}"
[[ -n "$DOMAIN" ]] || { echo "Thiếu domain" >&2; exit 1; }

echo "==> 1. Docker"
if ! command -v docker >/dev/null 2>&1; then
  apt-get update -y
  apt-get install -y ca-certificates curl
  curl -fsSL https://get.docker.com | sh
fi
systemctl enable --now docker
docker compose version

echo "==> 2. Firewall (SSH, 80, 443)"
if ! command -v ufw >/dev/null 2>&1; then apt-get install -y ufw; fi
ufw allow OpenSSH >/dev/null
ufw allow 80/tcp >/dev/null
ufw allow 443/tcp >/dev/null
ufw allow 443/udp >/dev/null
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
# set_env KEY VALUE: set KEY only when it is missing or empty in .env
set_env() {
  local key="$1" value="$2"
  if grep -qE "^${key}=.+" .env; then return; fi
  if grep -qE "^${key}=" .env; then
    sed -i "s|^${key}=.*|${key}=${value}|" .env
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
set_env DOMAIN "$DOMAIN"
sed -i "s|^NEXTAUTH_URL=http://localhost:3000$|NEXTAUTH_URL=|" .env
set_env NEXTAUTH_URL "https://${DOMAIN}"
sed -i 's|^AUTH_DISABLED=.*|AUTH_DISABLED=false|' .env
set_env COMPOSE_FILE "docker-compose.yml:deploy/docker-compose.vps.yml"

echo "==> 5. Thư mục"
mkdir -p secrets/rdt-cli backups
chmod 700 secrets backups

cat <<NEXT

Xong phần chuẩn bị. Còn lại (xem deploy/DEPLOY.md):
  1. Điền vào .env: ANTHROPIC_API_KEY, GROQ_API_KEYS, GOOGLE_CLIENT_ID/SECRET, PHASE2_EMAILS,
     TWITTER_AUTH_TOKEN/TWITTER_CT0, DISCORD_TOKEN          →  nano .env
  2. Google OAuth: thêm redirect URI  https://${DOMAIN}/api/auth/callback/google
  3. Chép credential.json của rdt-cli vào secrets/rdt-cli/
  4. Chạy:  docker compose up -d --build
  5. Mở:    https://${DOMAIN}
NEXT
