#!/usr/bin/env sh
# ─────────────────────────────────────────────
#  scripts/run.sh — start all services
# ─────────────────────────────────────────────
set -e

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

if [ ! -f .env ]; then
  echo "[run] .env not found — run 'scripts/setup.sh' first"
  exit 1
fi

echo "==> Starting moqompare..."
docker compose up -d

echo ""
echo "Services:"
docker compose ps

# Load .env to read ports
. ./.env 2>/dev/null || true
WEB_PORT="${WEB_PORT:-3000}"
ORIGIN_PORT="${ORIGIN_PORT:-8080}"

echo ""
echo "  Browser UI  : http://localhost:${WEB_PORT}"
echo "  HLS origin  : http://localhost:${ORIGIN_PORT}/hls/"
echo ""
echo "Run 'make logs' to stream logs."
