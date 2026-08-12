#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi

. .venv/bin/activate
pip install -r requirements.txt

if [ ! -f .env ] && [ -f .env.example ]; then
  cp .env.example .env
fi

echo "MealKey 餐启已启动: http://127.0.0.1:8000"
exec uvicorn app.main:app --host 127.0.0.1 --port 8000
