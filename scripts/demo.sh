#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  demo.sh — end-to-end moqompare demo
#
#  Usage: ./scripts/demo.sh [--no-browser]
#
#  Steps:
#    1. Ensures all services are up and healthy
#    2. Opens the comparison UI in the browser (unless --no-browser)
#    3. Waits for HLS stream to be reachable
#    4. Cycles through impairment profiles with pauses so you can observe
#       the effect on each player
#    5. Returns to baseline and prints a metrics snapshot
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

cd "$(dirname "$0")/.."

OPEN_BROWSER=1
for arg in "$@"; do
  [[ "$arg" == "--no-browser" ]] && OPEN_BROWSER=0
done

WEB_URL="${WEB_URL:-http://localhost:3000}"
METRICS_URL="${WEB_URL}/metrics"
IMPAIR_URL="${WEB_URL}/impair"

log()  { echo "[demo] $*"; }
warn() { echo "[demo] WARN: $*" >&2; }

# ── 1. Ensure services are up ─────────────────────────────────────────────────
log "checking docker compose services…"
if ! docker compose ps --quiet 2>/dev/null | grep -q .; then
  log "no running containers found — starting with 'make up'…"
  make up
fi

log "waiting for web service to become healthy…"
for i in $(seq 1 30); do
  if curl -sf "${WEB_URL}/health" >/dev/null 2>&1; then
    log "web is up"
    break
  fi
  if [[ $i -eq 30 ]]; then
    warn "web did not become healthy after 30 s"
    warn "run 'make logs' to investigate"
    exit 1
  fi
  sleep 1
done

log "waiting for metrics collector to become healthy…"
for i in $(seq 1 15); do
  if curl -sf "${METRICS_URL}/health" >/dev/null 2>&1; then
    log "metrics collector is up"
    break
  fi
  if [[ $i -eq 15 ]]; then
    warn "metrics collector did not become healthy — continuing without it"
    break
  fi
  sleep 1
done

# ── 2. Open browser ───────────────────────────────────────────────────────────
if [[ $OPEN_BROWSER -eq 1 ]]; then
  log "opening ${WEB_URL} …"
  case "$(uname -s)" in
    Darwin) open "${WEB_URL}" ;;
    Linux)  xdg-open "${WEB_URL}" 2>/dev/null || true ;;
    *)      log "(cannot auto-open browser on this platform)" ;;
  esac
fi

# ── 3. Wait for HLS stream to be reachable ────────────────────────────────────
log "waiting for HLS manifest…"
for i in $(seq 1 20); do
  if curl -sf "${WEB_URL}/hls/stream.m3u8" >/dev/null 2>&1; then
    log "HLS stream is live"
    break
  fi
  if [[ $i -eq 20 ]]; then
    warn "HLS manifest not reachable after 20 s — check packager logs"
  fi
  sleep 1
done

# ── 4. Impairment cycle ───────────────────────────────────────────────────────
apply() {
  local profile="$1"
  local secs="$2"
  log ">>> applying impairment: ${profile}"
  curl -sf -X POST "${IMPAIR_URL}/${profile}" \
    -H "Accept: application/json" --max-time 5 \
    | python3 -c "
import json,sys
d=json.load(sys.stdin)
if d.get('ok'):
    print('[demo] profile applied:', d.get('profile'))
else:
    print('[demo] WARN: impairment error:', d.get('errors'), file=sys.stderr)
" || warn "impair request failed for profile '${profile}'"
  log "    (waiting ${secs} s — observe both players)"
  sleep "${secs}"
}

log "──────────────────────────────────────────────"
log " IMPAIRMENT DEMO CYCLE"
log " Watch ${WEB_URL} — both panels side by side"
log "──────────────────────────────────────────────"

apply baseline  5
apply jitter   20
apply baseline  5
apply squeeze  20
apply baseline  5
apply outage   10   # auto-clears after 5 s; we wait 10 to see recovery

log "demo cycle complete — ensuring baseline is set"
curl -sf -X POST "${IMPAIR_URL}/baseline" >/dev/null || true

# ── 5. Print metrics snapshot ─────────────────────────────────────────────────
log "──────────────────────────────────────────────"
log " METRICS SNAPSHOT"
log "──────────────────────────────────────────────"
if curl -sf "${METRICS_URL}/snapshot" 2>/dev/null \
    | python3 -c "
import json,sys
d=json.load(sys.stdin)
for proto, g in d.get('gauges',{}).items():
    if not g:
        continue
    print(f'  [{proto}]')
    for k, v in sorted(g.items()):
        print(f'    {k}: {v}')
print()
for p, n in d.get('counters',{}).get('impairment_profile_changes',{}).items():
    print(f'  impairment/{p}: {n} change(s)')
"; then
  :
else
  warn "could not fetch metrics snapshot (collector may not have received browser reports yet)"
  warn "ensure the browser is open at ${WEB_URL} and both players are running"
fi

log "──────────────────────────────────────────────"
log " Done."
log "   Prometheus metrics : ${METRICS_URL}/metrics"
log "   JSON snapshot       : ${METRICS_URL}/snapshot"
log "──────────────────────────────────────────────"
