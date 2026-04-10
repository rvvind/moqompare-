#!/bin/sh
# ─────────────────────────────────────────────────────────────────────────────
#  fanout.sh — MoQ subscriber fan-out simulator
#
#  Spawns FANOUT_N concurrent moq-cli watch processes against the relay,
#  each subscribing to the live broadcast. Logs per-subscriber events and
#  a summary every FANOUT_REPORT_SECS seconds.
#
#  Environment:
#    FANOUT_N              Number of concurrent subscribers (default: 5)
#    FANOUT_RELAY_URL      Relay URL (default: http://relay:4443)
#    FANOUT_BROADCAST      Broadcast name (default: stream)
#    FANOUT_REPORT_SECS    Stats report interval in seconds (default: 10)
#    FANOUT_DURATION       Total run time in seconds, 0 = forever (default: 0)
# ─────────────────────────────────────────────────────────────────────────────

N="${FANOUT_N:-5}"
RELAY_URL="${FANOUT_RELAY_URL:-http://relay:4443}"
BROADCAST="${FANOUT_BROADCAST:-stream}"
REPORT_SECS="${FANOUT_REPORT_SECS:-10}"
DURATION="${FANOUT_DURATION:-0}"

STATS_DIR="/tmp/fanout_stats"
mkdir -p "${STATS_DIR}"

log() { echo "[fanout] $(date -u +%H:%M:%S) $*"; }

# ── Per-subscriber loop ───────────────────────────────────────────────────────
# Uses separate plain-number files to avoid grep-inside-substring bugs.
subscriber_loop() {
  idx="$1"
  c_file="${STATS_DIR}/sub_${idx}_c"   # connect count
  d_file="${STATS_DIR}/sub_${idx}_d"   # disconnect count
  echo 0 > "${c_file}"
  echo 0 > "${d_file}"

  while true; do
    c=$(cat "${c_file}")
    c=$(( c + 1 ))
    echo "${c}" > "${c_file}"

    # moq-cli watch subscribes and discards received objects
    if moq-cli \
        --url "${RELAY_URL}" \
        watch \
        --broadcast "${BROADCAST}" \
        --output /dev/null \
        2>&1 | while IFS= read -r line; do
          echo "[fanout:${idx}] ${line}"
        done; then
      :
    fi

    d=$(cat "${d_file}")
    d=$(( d + 1 ))
    echo "${d}" > "${d_file}"

    log "sub ${idx}: disconnected (${d} total), reconnecting…"
    sleep 1
  done
}

# ── Start N subscribers ───────────────────────────────────────────────────────
log "starting ${N} subscribers → ${RELAY_URL} broadcast=${BROADCAST}"
i=0
while [ "${i}" -lt "${N}" ]; do
  subscriber_loop "${i}" &
  i=$(( i + 1 ))
done

# ── Periodic stats report ─────────────────────────────────────────────────────
START=$(date +%s)

while true; do
  sleep "${REPORT_SECS}"

  total_c=0
  total_d=0
  for c_file in "${STATS_DIR}"/sub_*_c; do
    [ -f "${c_file}" ] || continue
    v=$(cat "${c_file}")
    total_c=$(( total_c + v ))
  done
  for d_file in "${STATS_DIR}"/sub_*_d; do
    [ -f "${d_file}" ] || continue
    v=$(cat "${d_file}")
    total_d=$(( total_d + v ))
  done
  active=$(( total_c - total_d ))

  log "STATS  subscribers=${N}  active=${active}  connects=${total_c}  disconnects=${total_d}"

  if [ "${DURATION}" -gt 0 ]; then
    NOW=$(date +%s)
    ELAPSED=$(( NOW - START ))
    if [ "${ELAPSED}" -ge "${DURATION}" ]; then
      log "duration ${DURATION}s reached — stopping"
      kill 0
      exit 0
    fi
  fi
done
