#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  impair.sh — apply a network impairment profile to the moqompare lab
#
#  Usage: ./scripts/impair.sh <profile>
#
#  Profiles:
#    baseline  — remove all tc rules (clean slate)
#    jitter    — 30 ms delay ±20 ms, 1 % packet loss
#    squeeze   — 500 kbit/s bandwidth cap
#    outage    — 100 % packet loss for 5 s, then auto-clear
#    status    — show current profile
#
#  Delegates to the impairment container's HTTP API (proxied through the
#  web container at /impair/<profile>).
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

PROFILE="${1:-}"
API_BASE="${IMPAIR_API_URL:-http://localhost:3000/impair}"

usage() {
  echo "Usage: $0 <baseline|jitter|squeeze|outage|status>"
  exit 1
}

[[ -z "$PROFILE" ]] && usage

case "$PROFILE" in
  status)
    curl -sf "${API_BASE}/status" | python3 -c \
      "import json,sys; d=json.load(sys.stdin); print('[impair] current profile:', d.get('profile','unknown'))"
    exit 0
    ;;
  baseline|jitter|squeeze|outage) ;;
  *)
    echo "Unknown profile: $PROFILE"
    usage
    ;;
esac

echo "[impair] applying profile: $PROFILE"
response=$(curl -sf -X POST "${API_BASE}/${PROFILE}" \
  -H "Accept: application/json" --max-time 5)

echo "$response" | python3 -c "
import json, sys
d = json.load(sys.stdin)
if d.get('ok'):
    print('[impair] OK — profile:', d.get('profile'))
    if d.get('auto_clear_secs'):
        print('[impair] auto-clears in', d['auto_clear_secs'], 's')
else:
    print('[impair] ERROR:', d.get('errors', 'unknown'))
    sys.exit(1)
"
