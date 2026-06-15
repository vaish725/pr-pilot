#!/usr/bin/env bash
set -euo pipefail

# Usage: ./scripts/start-smee.sh <SMEE_CHANNEL_URL>
# Example: ./scripts/start-smee.sh https://smee.io/abcd1234

SMEE_URL=${1:-}
if [ -z "$SMEE_URL" ]; then
  echo "Please provide your smee channel URL. Create one at https://smee.io and pass it as the first argument." >&2
  exit 2
fi

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

echo "Loading environment from .env (if present)"
if [ -f .env ]; then
  # shellcheck disable=SC2046
  export $(grep -v '^#' .env | xargs)
fi

echo "Starting FastAPI server on http://127.0.0.1:8000"
python3 -m pr_pilot.server &
SERVER_PID=$!

echo "Starting smee-client to forward $SMEE_URL -> http://localhost:8000/webhook"
npx -y smee-client --url "$SMEE_URL" --target "http://localhost:8000/webhook"

echo "Stopping server (pid $SERVER_PID)"
kill $SERVER_PID || true
