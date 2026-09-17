#!/bin/sh
set -eu

alembic upgrade head
if [ "$#" -gt 0 ]; then
  exec "$@"
fi
exec python -m uvicorn app.main:app \
  --host "${HOST:-0.0.0.0}" \
  --port "${PORT:-8000}"