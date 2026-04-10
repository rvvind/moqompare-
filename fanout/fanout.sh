#!/bin/sh
# ─────────────────────────────────────────────────────────────────────────────
#  fanout.sh — MoQ subscriber fan-out simulator
#
#  Spawns FANOUT_N concurrent moq-relay cluster nodes, each connecting to the
#  main relay as a cluster peer.  Each cluster node subscribes to the root's
#  announcement namespace, which registers as an active connection/subscription
#  on the main relay and is visible in relay logs.
#
#  Environment:
#    FANOUT_N              Number of concurrent subscriber nodes (default: 5)
#    FANOUT_RELAY_URL      Relay URL (default: http://relay:4443)
#    FANOUT_BROADCAST      Broadcast name — informational only (default: stream)
#    FANOUT_REPORT_SECS    Stats report interval in seconds (default: 10)
#    FANOUT_DURATION       Total run time in seconds, 0 = forever (default: 0)
# ─────────────────────────────────────────────────────────────────────────────

N="${FANOUT_N:-5}"
RELAY_URL="${FANOUT_RELAY_URL:-http://relay:4443}"
BROADCAST="${FANOUT_BROADCAST:-stream}"
REPORT_SECS="${FANOUT_REPORT_SECS:-10}"
DURATION="${FANOUT_DURATION:-0}"
CLUSTER_TOKEN_FILE="${FANOUT_CLUSTER_TOKEN:-/cluster_token}"

# Strip scheme and trailing path to get host:port
RELAY_HOST=$(echo "${RELAY_URL}" | sed 's|^[a-z]*://||' | cut -d/ -f1)

log() { echo "[fanout] $(date -u +%H:%M:%S) $*"; }

# ── Wait for relay ────────────────────────────────────────────────────────────
log "waiting for relay at ${RELAY_HOST}…"
attempt=0
while [ "${attempt}" -lt 30 ]; do
  wget -qO- "http://${RELAY_HOST}/certificate.sha256" >/dev/null 2>&1 && break
  attempt=$(( attempt + 1 ))
  sleep 2
done
if ! wget -qO- "http://${RELAY_HOST}/certificate.sha256" >/dev/null 2>&1; then
  log "ERROR: relay not reachable after 60 s — aborting"
  exit 1
fi
log "relay at ${RELAY_HOST} ready (broadcast=${BROADCAST})"

# ── Spawn N cluster relay nodes ───────────────────────────────────────────────
# Each node binds on a unique port and connects to the main relay as a cluster
# peer.  --tls-disable-verify bypasses the self-signed cert check.
# The cluster connection registers as an active subscriber on the main relay
# and is visible in its logs.
BASE_PORT=5000
idx=0
while [ "${idx}" -lt "${N}" ]; do
  PORT=$(( BASE_PORT + idx ))
  log "starting subscriber node ${idx} on :${PORT}"
  (
    # --cluster-node uses the real Docker container hostname so the peers
    # advertised to the root relay are resolvable within the compose network.
    MOQ_AUTH_PUBLIC= moq-relay \
      --server-bind "[::]:${PORT}" \
      --tls-generate "fanout-${idx}" \
      --cluster-root "${RELAY_HOST}" \
      --cluster-node "$(hostname):${PORT}" \
      --cluster-token "${CLUSTER_TOKEN_FILE}" \
      --tls-disable-verify \
      2>&1 | while IFS= read -r line; do
        echo "[fanout:${idx}] ${line}"
      done
  ) &
  idx=$(( idx + 1 ))
done

log "started ${N} subscriber nodes → ${RELAY_HOST}"

# ── Periodic stats report ─────────────────────────────────────────────────────
START=$(date +%s)

while true; do
  sleep "${REPORT_SECS}"
  log "STATS  nodes=${N}  relay=${RELAY_HOST}"

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
