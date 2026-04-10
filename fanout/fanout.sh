#!/bin/sh
# ─────────────────────────────────────────────────────────────────────────────
#  fanout.sh — MoQ subscriber fan-out simulator
#
#  Spawns FANOUT_N concurrent moq-cli watch processes against the relay,
#  each subscribing to the live broadcast. Logs per-subscriber connect/
#  disconnect events and a summary every FANOUT_REPORT_SECS seconds.
#
#  Environment:
#    FANOUT_N              Number of concurrent subscribers (default: 5)
#    FANOUT_RELAY_URL      Relay URL (default: http://relay:4443)
#    FANOUT_BROADCAST      Broadcast name (default: stream)
#    FANOUT_REPORT_SECS    Stats report interval in seconds (default: 10)
#    FANOUT_DURATION       Total run time in seconds, 0 = forever (default: 0)
# ─────────────────────────────────────────────────────────────────────────────
set -e

N="${FANOUT_N:-5}"
RELAY_URL="${FANOUT_RELAY_URL:-http://relay:4443}"
BROADCAST="${FANOUT_BROADCAST:-stream}"
REPORT_SECS="${FANOUT_REPORT_SECS:-10}"
DURATION="${FANOUT_DURATION:-0}"

PIDS_FILE="/tmp/fanout_pids"
STATS_DIR="/tmp/fanout_stats"
mkdir -p "${STATS_DIR}"
> "${PIDS_FILE}"

log() { echo "[fanout] $(date -u +%H:%M:%S) $*"; }

# ── Per-subscriber watch loop ─────────────────────────────────────────────
subscriber_loop() {
  idx="$1"
  stat_file="${STATS_DIR}/sub_${idx}"
  echo "connects=0 disconnects=0 last_status=starting" > "${stat_file}"

  while true; do
    connects=$(grep -o 'connects=[0-9]*' "${stat_file}" | cut -d= -f2)
    connects=$(( connects + 1 ))
    echo "connects=${connects} disconnects=$(grep -o 'disconnects=[0-9]*' "${stat_file}" | cut -d= -f2) last_status=connecting" > "${stat_file}"

    # moq-cli watch subscribes and dumps received objects to /dev/null
    if moq-cli \
        --url "${RELAY_URL}" \
        watch \
        --broadcast "${BROADCAST}" \
        --output /dev/null \
        2>&1 | while IFS= read -r line; do
          echo "[fanout:${idx}] ${line}"
        done; then
      status="clean_exit"
    else
      status="error_exit"
    fi

    disconnects=$(grep -o 'disconnects=[0-9]*' "${stat_file}" | cut -d= -f2)
    disconnects=$(( disconnects + 1 ))
    echo "connects=${connects} disconnects=${disconnects} last_status=${status}" > "${stat_file}"
    log "sub ${idx}: reconnecting (${disconnects} disconnects so far)"
    sleep 1
  done
}

# ── Start N subscribers ───────────────────────────────────────────────────
log "starting ${N} subscribers → ${RELAY_URL} broadcast=${BROADCAST}"
i=0
while [ "$i" -lt "$N" ]; do
  subscriber_loop "$i" &
  echo "$!" >> "${PIDS_FILE}"
  i=$(( i + 1 ))
done

# ── Periodic stats reporter ───────────────────────────────────────────────
report_stats() {
  total_connects=0
  total_disconnects=0
  active=0
  for f in "${STATS_DIR}"/sub_*; do
    [ -f "$f" ] || continue
    c=$(grep -o 'connects=[0-9]*' "$f" | cut -d= -f2)
    d=$(grep -o 'disconnects=[0-9]*' "$f" | cut -d= -f2)
    s=$(grep -o 'last_status=[^ ]*' "$f" | cut -d= -f2)
    total_connects=$(( total_connects + c ))
    total_disconnects=$(( total_disconnects + d ))
    [ "$s" = "connecting" ] && active=$(( active + 1 ))
  done
  log "STATS  subscribers=${N}  active=${active}  connects=${total_connects}  disconnects=${total_disconnects}"
}

# ── Main loop: report stats, handle duration limit ───────────────────────
START=$(date +%s)
while true; do
  sleep "${REPORT_SECS}"
  report_stats

  if [ "${DURATION}" -gt 0 ]; then
    NOW=$(date +%s)
    ELAPSED=$(( NOW - START ))
    if [ "${ELAPSED}" -ge "${DURATION}" ]; then
      log "duration ${DURATION}s reached — stopping subscribers"
      kill $(cat "${PIDS_FILE}") 2>/dev/null || true
      report_stats
      log "done"
      exit 0
    fi
  fi
done
