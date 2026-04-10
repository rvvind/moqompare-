#!/usr/bin/env python3
"""
impair.py — Impairment HTTP API

Applies tc netem rules to the network interfaces of the web proxy and relay
containers by entering their network namespaces via nsenter.

Targets:
  HLS_CONTAINER  (default: moqompare-web)   — nginx proxy that sits between
                 the browser and origin.  Impairs HLS delivery to the browser
                 without touching publisher→origin ingest (publishers read
                 origin directly, not via web).
  RELAY_CONTAINER (default: moqompare-relay) — QUIC relay.  Impairs outgoing
                 MoQ objects to the browser.

Requires: privileged container with pid:host and iproute2 installed.

Endpoints:
  POST /impair/baseline  — clear all tc rules
  POST /impair/jitter    — 30 ms delay ±20 ms, 1 % loss
  POST /impair/squeeze   — 500 kbit/s rate cap
  POST /impair/outage    — 100 % loss for 5 s, then auto-clear

  GET  /impair/status    — current profile as JSON
"""

import json
import os
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

TARGETS = [
    os.environ.get("HLS_CONTAINER",   "moqompare-web"),
    os.environ.get("RELAY_CONTAINER", "moqompare-relay"),
]

PROFILES = {
    "baseline": [],  # no netem params → clears existing rules
    "jitter":   ["delay", "30ms", "20ms", "distribution", "normal", "loss", "1%"],
    "squeeze":  ["rate", "500kbps"],
    "outage":   ["loss", "100%"],
}

_current_profile = "baseline"
_lock = threading.Lock()
_outage_timer: threading.Timer | None = None


# ── tc helpers ────────────────────────────────────────────────────────────────

def _pid_of(container: str) -> str | None:
    """Get the init PID of a container via `docker inspect`."""
    try:
        r = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Pid}}", container],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0:
            pid = r.stdout.strip()
            if pid and pid != "0":
                return pid
            print(f"[impair] _pid_of({container}): container not running (pid=0)")
        else:
            print(f"[impair] _pid_of({container}): docker inspect failed: {r.stderr.strip()}")
    except Exception as e:
        print(f"[impair] _pid_of({container}) error: {e}")
    return None


def _tc(pid: str, args: list[str]) -> tuple[bool, str]:
    """Run tc in the network namespace of the given PID."""
    if args:
        cmd = ["nsenter", "--target", pid, "--net", "--",
               "tc", "qdisc", "replace", "dev", "eth0", "root", "netem"] + args
    else:
        # 'replace' with no netem params is not valid — delete instead.
        cmd = ["nsenter", "--target", pid, "--net", "--",
               "tc", "qdisc", "del", "dev", "eth0", "root"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        if r.returncode != 0:
            # Deleting a non-existent qdisc is fine (RTNETLINK answers: No such file)
            if "No such file" in r.stderr or "RTNETLINK" in r.stderr:
                return True, ""
            return False, r.stderr.strip()
        return True, ""
    except Exception as e:
        return False, str(e)


def apply_profile(profile: str) -> dict:
    global _current_profile, _outage_timer

    if profile not in PROFILES:
        return {"ok": False, "error": f"unknown profile: {profile}"}

    with _lock:
        # Cancel any pending outage auto-clear.
        if _outage_timer is not None:
            _outage_timer.cancel()
            _outage_timer = None

        args = PROFILES[profile]
        errors = []

        for container in TARGETS:
            pid = _pid_of(container)
            if pid is None:
                errors.append(f"{container}: pid not found")
                continue
            ok, err = _tc(pid, args)
            if not ok:
                errors.append(f"{container}: {err}")
            else:
                print(f"[impair] {profile} → {container} (pid {pid}) OK")

        if profile == "outage" and not errors:
            def _auto_clear():
                print("[impair] outage: auto-clearing after 5 s")
                apply_profile("baseline")

            _outage_timer = threading.Timer(5.0, _auto_clear)
            _outage_timer.daemon = True
            _outage_timer.start()

        _current_profile = profile if not errors else _current_profile
        return {
            "ok": not errors,
            "profile": profile,
            "errors": errors,
            "auto_clear_secs": 5 if profile == "outage" and not errors else None,
        }


# ── HTTP server ───────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[impair] {self.address_string()} {fmt % args}")

    def _send_json(self, code: int, body: dict):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self):
        if self.path in ("/impair/status", "/status"):
            self._send_json(200, {"profile": _current_profile})
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        path = self.path.rstrip("/")
        # Accept  /impair/<profile>  or  /<profile>
        profile = path.split("/")[-1]
        if not profile:
            self._send_json(400, {"error": "profile required"})
            return
        result = apply_profile(profile)
        self._send_json(200 if result["ok"] else 400, result)


if __name__ == "__main__":
    port = int(os.environ.get("IMPAIR_PORT", 8090))
    print(f"[impair] listening on :{port}")
    print(f"[impair] targets: {TARGETS}")

    # Startup smoke-test: verify docker socket is reachable and resolve PIDs.
    for t in TARGETS:
        pid = _pid_of(t)
        if pid:
            print(f"[impair] startup: {t} → pid {pid} OK")
        else:
            print(f"[impair] startup: {t} → pid NOT FOUND (socket missing or container not running)")

    server = HTTPServer(("0.0.0.0", port), Handler)
    server.serve_forever()
