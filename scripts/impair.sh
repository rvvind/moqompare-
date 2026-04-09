#!/usr/bin/env sh
# ─────────────────────────────────────────────
#  scripts/impair.sh — apply / clear network
#  impairment profiles via tc netem
#
#  Usage:
#    impair.sh baseline       clear all impairments
#    impair.sh jitter         delay 30ms ±20ms, loss 1%
#    impair.sh squeeze        rate limit to 500kbit
#    impair.sh outage         100% loss for 5s then auto-clear
#    impair.sh status         show current tc rules
#
#  Requires NET_ADMIN capability (run with sudo or
#  inside a container with cap_add: [NET_ADMIN]).
#
#  Phase 0: stub — prints what would be applied.
#  Phase 3+: runs real tc commands.
# ─────────────────────────────────────────────
set -e

IFACE="${IMPAIR_IFACE:-eth0}"
PROFILE="${1:-}"

usage() {
  echo "Usage: $0 <baseline|jitter|squeeze|outage|status>"
  exit 1
}

[ -z "$PROFILE" ] && usage

echo "[impair] interface: $IFACE  profile: $PROFILE"
echo "[impair] NOTE: Phase 0 stub — no tc commands executed yet"
echo ""

case "$PROFILE" in
  baseline)
    echo "[impair] Would run: tc qdisc del dev $IFACE root (clear all rules)"
    ;;
  jitter)
    echo "[impair] Would run: tc qdisc add dev $IFACE root netem delay 30ms 20ms loss 1%"
    ;;
  squeeze)
    echo "[impair] Would run: tc qdisc add dev $IFACE root tbf rate 500kbit burst 32kbit latency 400ms"
    ;;
  outage)
    echo "[impair] Would run: tc qdisc add dev $IFACE root netem loss 100%"
    echo "[impair] Would sleep 5s then clear (baseline)"
    ;;
  status)
    echo "[impair] Would run: tc qdisc show dev $IFACE"
    ;;
  *)
    echo "[impair] Unknown profile: $PROFILE"
    usage
    ;;
esac
