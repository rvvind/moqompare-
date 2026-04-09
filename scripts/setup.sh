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

check_cmd docker
check_cmd docker compose 2>/dev/null || check_cmd "docker-compose"

# ── .env ──────────────────────────────────────────────────────────────────
if [ ! -f .env ]; then
  cp .env.example .env
  echo "[setup] Created .env from .env.example — review it before starting"
else
  echo "[setup] .env already present, skipping"
fi

# ── Pull images ─────────────────────────────────────────────────────────
echo "[setup] Pulling Docker images..."
docker compose pull

echo ""
echo "==> Setup complete. Run 'make up' or 'scripts/run.sh' to start the lab."
