#!/usr/bin/env python3
"""
impair.py — Impairment HTTP API

Two classes of impairment:

1. tc netem (network-layer) — applied to container eth0 via nsenter:
     HLS_CONTAINER  (default: moqompare-web)   — nginx proxy; impairs HLS
                    delivery to the browser without touching publisher→origin.
     RELAY_CONTAINER (default: moqompare-relay) — QUIC relay; impairs outgoing
                    MoQ objects to the browser.

2. Manifest freeze (application-layer) — HTTP call to manifest-proxy:
     stale_manifest — POST /freeze to manifest-proxy; HLS players receive the
                    same stale segment list on every poll and cannot advance.
                    MoQ is manifest-less and completely unaffected.
                    Auto-clears after 30 s.

Requires: privileged container with pid:host and iproute2 installed.

Endpoints:
  POST /impair/baseline        — clear all tc rules + unfreeze manifests
  POST /impair/jitter          — 30 ms delay ±20 ms, 1 % loss
  POST /impair/squeeze         — 500 kbit/s rate cap
  POST /impair/outage          — 100 % loss for 5 s, then auto-clear
  POST /impair/stale_manifest  — freeze manifests for 30 s, then auto-clear
  POST /impair/inject_cue      — inject EXT-X-CUE-OUT into HLS manifest
                                 (optional ?duration=<secs>, default 30)

  GET  /impair/status          — current profile as JSON
"""

import json
import os
import subprocess
import threading
import urllib.request
import urllib.error
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

TARGETS = [
    os.environ.get("HLS_CONTAINER",   "moqompare-web"),
    os.environ.get("RELAY_CONTAINER", "moqompare-relay"),
]

MANIFEST_PROXY_URL = os.environ.get("MANIFEST_PROXY_URL", "http://manifest-proxy:8091")

# netem profiles — stale_manifest is handled separately (no netem)
NETEM_PROFILES = {
    "baseline": [],  # empty → delete qdisc
    "jitter":   ["delay", "30ms", "20ms", "distribution", "normal", "loss", "1%"],
    "squeeze":  ["rate", "500kbps"],
    "outage":   ["loss", "100%"],
}

ALL_PROFILES = set(NETEM_PROFILES) | {"stale_manifest"}
# inject_cue is handled separately (not a netem profile)
AD_PROFILES  = {"inject_cue"}

_current_profile = "baseline"
_lock = threading.Lock()
_auto_clear_timer: threading.Timer | None = None


# ── tc helpers ────────────────────────────────────────────────────────────────

def _pid_of(container: str) -> str | None:
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
    if args:
        cmd = ["nsenter", "--target", pid, "--net", "--",
               "tc", "qdisc", "replace", "dev", "eth0", "root", "netem"] + args
    else:
        cmd = ["nsenter", "--target", pid, "--net", "--",
               "tc", "qdisc", "del", "dev", "eth0", "root"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        if r.returncode != 0:
            if ("No such file" in r.stderr or "RTNETLINK" in r.stderr
                    or "handle of zero" in r.stderr):
                return True, ""  # no qdisc to delete — that's fine
            return False, r.stderr.strip()
        return True, ""
    except Exception as e:
        return False, str(e)


def _apply_netem(profile: str) -> list[str]:
    """Apply netem rules for a profile; return list of error strings."""
    args = NETEM_PROFILES[profile]
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
            print(f"[impair] netem {profile} → {container} (pid {pid}) OK")
    return errors


# ── manifest-proxy helpers ────────────────────────────────────────────────────

def _manifest_freeze() -> tuple[bool, str]:
    try:
        req = urllib.request.Request(
            f"{MANIFEST_PROXY_URL}/freeze", method="POST",
            headers={"Content-Length": "0"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = json.loads(resp.read())
            print(f"[impair] manifest freeze OK — {body.get('cached', '?')} path(s) cached")
            return True, ""
    except Exception as e:
        return False, str(e)


def _manifest_unfreeze() -> tuple[bool, str]:
    try:
        req = urllib.request.Request(
            f"{MANIFEST_PROXY_URL}/unfreeze", method="POST",
            headers={"Content-Length": "0"},
        )
        with urllib.request.urlopen(req, timeout=5):
            print("[impair] manifest unfreeze OK")
            return True, ""
    except Exception as e:
        return False, str(e)


# ── Ad cue helpers ────────────────────────────────────────────────────────────

def _inject_cue(duration: int = 30, trace_id: str | None = None) -> dict:
    try:
        query = f"duration={duration}"
        if trace_id:
            query += f"&trace_id={urllib.parse.quote(trace_id)}"
        req = urllib.request.Request(
            f"{MANIFEST_PROXY_URL}/cue_out?{query}",
            method="POST",
            headers={"Content-Length": "0"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = json.loads(resp.read())
            print(f"[impair] cue-out armed — duration={duration}s trace_id={trace_id or '-'}")
            return {
                "ok": True,
                "profile": "inject_cue",
                "errors": [],
                "auto_clear_secs": None,
                "trace_id": trace_id,
                "manifest_proxy": body,
            }
    except Exception as e:
        print(f"[impair] inject_cue error trace_id={trace_id or '-'}: {e}")
        return {
            "ok": False,
            "profile": "inject_cue",
            "errors": [str(e)],
            "auto_clear_secs": None,
            "trace_id": trace_id,
        }


# ── Profile application ───────────────────────────────────────────────────────

def apply_profile(profile: str) -> dict:
    global _current_profile, _auto_clear_timer

    if profile not in ALL_PROFILES:
        return {"ok": False, "errors": [f"unknown profile: {profile}"]}

    with _lock:
        if _auto_clear_timer is not None:
            _auto_clear_timer.cancel()
            _auto_clear_timer = None

        errors = []

        if profile == "stale_manifest":
            # No netem — clear any existing network rules first, then freeze manifests
            _apply_netem("baseline")
            ok, err = _manifest_freeze()
            if not ok:
                errors.append(f"manifest-proxy: {err}")
            else:
                def _auto_unfreeze():
                    print("[impair] stale_manifest: auto-clearing after 30 s")
                    apply_profile("baseline")
                _auto_clear_timer = threading.Timer(30.0, _auto_unfreeze)
                _auto_clear_timer.daemon = True
                _auto_clear_timer.start()

        else:
            # Always unfreeze manifests when switching away
            _manifest_unfreeze()
            errors = _apply_netem(profile)

            if profile == "outage" and not errors:
                def _auto_clear():
                    print("[impair] outage: auto-clearing after 5 s")
                    apply_profile("baseline")
                _auto_clear_timer = threading.Timer(5.0, _auto_clear)
                _auto_clear_timer.daemon = True
                _auto_clear_timer.start()

        _current_profile = profile if not errors else _current_profile

        auto_secs = None
        if profile == "outage" and not errors:
            auto_secs = 5
        elif profile == "stale_manifest" and not errors:
            auto_secs = 30

        return {
            "ok": not errors,
            "profile": profile,
            "errors": errors,
            "auto_clear_secs": auto_secs,
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
        import urllib.parse as _up
        path    = self.path.rstrip("/")
        parsed  = _up.urlparse(path)
        profile = parsed.path.split("/")[-1]
        qs      = dict(_up.parse_qsl(parsed.query))
        if not profile:
            self._send_json(400, {"error": "profile required"})
            return
        if profile == "inject_cue":
            duration = int(qs.get("duration", 30))
            result   = _inject_cue(duration, qs.get("trace_id"))
        else:
            result = apply_profile(profile)
        self._send_json(200 if result["ok"] else 400, result)


if __name__ == "__main__":
    port = int(os.environ.get("IMPAIR_PORT", 8090))
    print(f"[impair] listening on :{port}")
    print(f"[impair] netem targets: {TARGETS}")
    print(f"[impair] manifest-proxy: {MANIFEST_PROXY_URL}")

    for t in TARGETS:
        pid = _pid_of(t)
        if pid:
            print(f"[impair] startup: {t} → pid {pid} OK")
        else:
            print(f"[impair] startup: {t} → pid NOT FOUND")

    server = HTTPServer(("0.0.0.0", port), Handler)
    server.serve_forever()
