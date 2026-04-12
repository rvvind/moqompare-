#!/usr/bin/env sh
# ─────────────────────────────────────────────
#  scripts/run.sh — start all services
# ─────────────────────────────────────────────
set -e

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

check_docker_compose() {
  if docker compose version >/dev/null 2>&1; then
    COMPOSE_CMD="docker compose"
    return 0
  fi
  if command -v docker-compose >/dev/null 2>&1; then
    COMPOSE_CMD="docker-compose"
    return 0
  fi

  echo "[run] Docker Compose is required but not available"
  echo "[run] Install the Docker Compose v2 plugin or docker-compose"
  exit 1
}

check_docker_daemon() {
  if docker info >/dev/null 2>&1; then
    return 0
  fi

  context="$(docker context show 2>/dev/null || echo "")"
  echo "[run] Docker daemon is not reachable"
  if [ "$context" = "colima" ]; then
    echo "[run] Active context is 'colima' — start it with: colima start --runtime docker"
  else
    echo "[run] Start your Docker runtime, then retry"
  fi
  exit 1
}

ensure_cluster_credentials() {
  python3 scripts/generate_cluster_credentials.py
}

if [ ! -f .env ]; then
  echo "[run] .env not found — run 'scripts/setup.sh' first"
  exit 1
fi

check_docker_compose
check_docker_daemon
ensure_cluster_credentials

echo "==> Starting moqompare..."
$COMPOSE_CMD up -d

echo ""
echo "Services:"
$COMPOSE_CMD ps

# Load .env to read ports
. ./.env 2>/dev/null || true
WEB_PORT="${WEB_PORT:-3000}"
ORIGIN_PORT="${ORIGIN_PORT:-8080}"

echo ""
echo "  Browser UI  : http://localhost:${WEB_PORT}"
echo "  HLS origin  : http://localhost:${ORIGIN_PORT}/hls/"
echo ""
echo "Run 'make logs' to stream logs."
