#!/usr/bin/env bash
# Run MENNBridge without Docker for the backend/frontend - useful for local
# development (hot reload, easier debugging) as an alternative to
# `docker compose up`. Postgres still runs in Docker since there's no
# reason not to containerize a stateless dependency like that.
#
# Reads the same root .env file docker-compose.yml uses.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if [ ! -f .env ]; then
  echo "Missing .env at $ROOT_DIR/.env - copy the template and fill it in first." >&2
  exit 1
fi

# Normalize "KEY = value" / "KEY= value" to "KEY=value" before sourcing -
# bash's `source` treats a space after `=` as "run a command named value
# with KEY set in its environment", not as part of the assignment. Written
# to a real temp file rather than `source <(...)`: process substitution
# silently fails to export anything under macOS's stock bash 3.2.
NORMALIZED_ENV="$(mktemp)"
sed -E 's/^([A-Za-z_][A-Za-z0-9_]*)[[:space:]]*=[[:space:]]*/\1=/' .env > "$NORMALIZED_ENV"
set -a
# shellcheck disable=SC1090
source "$NORMALIZED_ENV"
set +a
rm -f "$NORMALIZED_ENV"

PORT="${PORT:-8000}"
PG_CONTAINER=mennbridge-run-postgres
PG_PORT=5432

CLEANED_UP=0
cleanup() {
  [ "$CLEANED_UP" = 1 ] && return
  CLEANED_UP=1
  echo
  echo "Shutting down..."
  [ -n "${BACKEND_PID:-}" ] && kill "$BACKEND_PID" 2>/dev/null || true
  [ -n "${FRONTEND_PID:-}" ] && kill "$FRONTEND_PID" 2>/dev/null || true
  docker rm -f "$PG_CONTAINER" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

echo "==> Starting Postgres in Docker..."
docker rm -f "$PG_CONTAINER" >/dev/null 2>&1 || true
docker run -d --name "$PG_CONTAINER" \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=mennbridge \
  -p "${PG_PORT}:5432" \
  -v "$ROOT_DIR/backend/db/init.sql:/docker-entrypoint-initdb.d/init.sql:ro" \
  postgres:15-alpine >/dev/null

echo "==> Waiting for Postgres to be ready..."
until docker exec "$PG_CONTAINER" pg_isready -U postgres >/dev/null 2>&1; do
  sleep 1
done

# Always point at the Postgres container this script just started on the
# host's loopback address - whatever DATABASE_URL is in .env is almost
# certainly written for docker-compose's internal "postgres" hostname,
# which doesn't resolve outside that network.
export DATABASE_URL="postgresql://postgres:postgres@127.0.0.1:${PG_PORT}/mennbridge"
echo "==> Using DATABASE_URL=$DATABASE_URL (overriding .env for this native run)"

echo "==> Setting up backend venv..."
cd "$ROOT_DIR/backend"
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q -r requirements.txt

echo "==> Starting backend on port $PORT..."
uvicorn main:app --host 0.0.0.0 --port "$PORT" &
BACKEND_PID=$!

cd "$ROOT_DIR/frontend"
if [ ! -d node_modules ]; then
  echo "==> Installing frontend dependencies..."
  npm install
fi

echo "==> Starting frontend on port 3000..."
BACKEND_URL="http://localhost:${PORT}" npm run dev -- --port 3000 &
FRONTEND_PID=$!

echo
echo "MENNBridge is starting:"
echo "  Backend:   http://localhost:${PORT}/health"
echo "  Dashboard: http://localhost:3000"
echo
echo "Press Ctrl+C to stop everything."

wait "$BACKEND_PID" "$FRONTEND_PID"
