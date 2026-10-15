#!/usr/bin/env bash
# Cập nhật lên code mới nhất của branch đang dùng, build lại và khởi động lại.
#   bash deploy/update.sh
# DB tự chạy migration khi API/worker khởi động; dữ liệu nằm trong volume nên không mất.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

git pull --ff-only
# Folders mounted into containers: create them as this user, or Docker creates them owned by root.
mkdir -p secrets/rdt-cli secrets/youtube backups
docker compose up -d --build
docker image prune -f >/dev/null
docker compose ps
