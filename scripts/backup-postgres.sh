#!/usr/bin/env bash
# 生产 Postgres 备份。密钥不进仓库：从环境变量读 DATABASE_URL。
set -euo pipefail
OUT_DIR="${BACKUP_DIR:-./backups}"
mkdir -p "$OUT_DIR"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
FILE="$OUT_DIR/mealky-$STAMP.dump"
if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "DATABASE_URL is required" >&2
  exit 1
fi
pg_dump --format=custom --no-owner --file="$FILE" "$DATABASE_URL"
echo "wrote $FILE"
