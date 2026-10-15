#!/usr/bin/env bash
# Sao lưu Postgres thành backups/radar-YYYYmmdd-HHMM.sql.gz, giữ 14 ngày gần nhất.
#   bash deploy/backup.sh
# Chạy hằng ngày bằng cron (xem deploy/DEPLOY.md).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

KEEP_DAYS="${KEEP_DAYS:-14}"
mkdir -p backups
file="backups/radar-$(date +%Y%m%d-%H%M).sql.gz"
docker compose exec -T postgres pg_dump -U radar -d radar --no-owner | gzip > "$file"
if [[ ! -s "$file" ]]; then
  echo "Sao lưu rỗng, kiểm tra container postgres" >&2
  rm -f "$file"
  exit 1
fi
find backups -name 'radar-*.sql.gz' -mtime "+${KEEP_DAYS}" -delete
echo "Đã sao lưu: $file ($(du -h "$file" | cut -f1))"
