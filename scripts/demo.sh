#!/usr/bin/env sh
# ─────────────────────────────────────────────
#  scripts/demo.sh — end-to-end demo
#
#  Starts the lab, waits for services to be
#  healthy, then cycles through impairment
#  profiles so the difference between HLS and
#  MoQ can be observed.
#
#  Phase 0: only prints what the demo will do.
#  Phase 3+: wires up real impairment injection.
# ─────────────────────────────────────────────
set -e

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

echo "==> moqompare demo (phase 0 — dry run)"
echo ""
echo "When fully implemented, this script will:"
echo "  1. Start all services"
echo "  2. Wait for HLS and MoQ players to report healthy"
echo "  3. Run: baseline (60s)"
echo "  4. Apply: jitter + loss — delay 30ms ±20ms, loss 1%  (60s)"
echo "  5. Apply: bandwidth squeeze — 500kbit cap              (60s)"
echo "  6. Apply: burst outage — 100% loss for 5s, then clear (60s)"
echo "  7. Print summary of observed latency and rebuffer counts"
echo ""
echo "To run the lab now: make up"
