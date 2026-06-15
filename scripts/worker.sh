#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

if [ -f .env ]; then
  export $(grep -v '^#' .env | xargs)
fi

REDIS_URL=${REDIS_URL:-redis://localhost:6379}

echo "Starting RQ worker for queue 'pr-jobs' (REDIS_URL=$REDIS_URL)"
rq worker pr-jobs --url "$REDIS_URL"
