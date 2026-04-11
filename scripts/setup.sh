#!/usr/bin/env sh
# ─────────────────────────────────────────────
#  scripts/setup.sh — bootstrap the local lab
# ─────────────────────────────────────────────
set -e

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

echo "==> moqompare setup"

# ── Prerequisites ──────────────────────────────────────────────────────────
check_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "[error] '$1' is required but not found in PATH"
    exit 1
  fi
}

check_docker_compose() {
  if docker compose version >/dev/null 2>&1; then
    COMPOSE_CMD="docker compose"
    return 0
  fi
  if command -v docker-compose >/dev/null 2>&1; then
    COMPOSE_CMD="docker-compose"
    return 0
  fi

  echo "[error] Docker Compose is required but not available"
  echo "[error] Install the Docker Compose v2 plugin or docker-compose"
  exit 1
}

check_docker_daemon() {
  if docker info >/dev/null 2>&1; then
    return 0
  fi

  context="$(docker context show 2>/dev/null || echo "")"
  echo "[error] Docker daemon is not reachable"
  if [ "$context" = "colima" ]; then
    echo "[error] Active context is 'colima' — start it with: colima start --runtime docker"
  else
    echo "[error] Start your Docker runtime, then retry"
  fi
  exit 1
}

check_cmd docker
check_docker_compose
check_docker_daemon

# ── .env ──────────────────────────────────────────────────────────────────
if [ ! -f .env ]; then
  cp .env.example .env
  echo "[setup] Created .env from .env.example — review it before starting"
else
  echo "[setup] .env already present, skipping"
fi

# ── Pull images ─────────────────────────────────────────────────────────
echo "[setup] Pulling Docker images..."
$COMPOSE_CMD pull

echo ""
echo "==> Setup complete. Run 'make up' or 'scripts/run.sh' to start the lab."
