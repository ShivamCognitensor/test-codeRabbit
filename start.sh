#!/usr/bin/env sh
set -e

# Optional: run migrations (only if you use alembic in this container)
alembic upgrade head

# Optional: run seed only when enabled
if [ "${SEED_VOICEBOT:-0}" = "1" ]; then
  python -m app.seed_voicebot
fi

exec uvicorn app.main:app --host 0.0.0.0 --port 8007
