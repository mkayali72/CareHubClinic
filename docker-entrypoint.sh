#!/bin/sh
set -eu

alembic upgrade head
exec python -m uvicorn app.main:app \
  --host "${HOST:-0.0.0.0}" \
  --port "${PORT:-8000}"