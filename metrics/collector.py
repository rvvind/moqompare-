#!/usr/bin/env python3
"""
collector.py — moqompare metrics collector

Receives JSON metric reports from the browser and exposes them as:
  GET /metrics   — Prometheus text format
  GET /snapshot  — JSON snapshot (for debugging)

Browser pushes:  POST /report   with JSON body

Prometheus metrics exposed:
  player_latency_seconds{protocol}
  player_startup_ms{protocol}
  player_stalls_total{protocol}
  player_stall_duration_ms{protocol}
  player_bitrate_bps{protocol}
  player_resolution_width{protocol}
  player_resolution_height{protocol}
  impairment_profile_changes_total{profile}
  metrics_last_report_timestamp_seconds{protocol}
"""

import json
import os
import time
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

_lock = threading.Lock()

# Per-protocol gauge values (most-recent report)
_gauges: dict[str, dict] = {
    "hls": {},
    "moq": {},
}

# Counters that only increase
_counters: dict[str, dict] = {
    "impairment_profile_changes": {},   # {profile: count}
}

# Timestamps of last report per protocol
_last_report: dict[str, float] = {}


def _record_report(body: dict) -> None:
    protocol = body.get("protocol", "")
    if protocol not in _gauges:
        return

    with _lock:
        g = _gauges[protocol]

        def _set(key, val):
            if val is not None:
                try:
                    g[key] = float(val)
                except (TypeError, ValueError):
                    pass

        _set("latency_seconds", body.get("latency_seconds"))
        _set("startup_ms",      body.get("startup_ms"))
        _set("stalls_total",    body.get("stalls_total"))
        _set("stall_duration_ms", body.get("stall_duration_ms"))
        _set("bitrate_bps",     body.get("bitrate_bps"))
        _set("resolution_width",  body.get("resolution_width"))
        _set("resolution_height", body.get("resolution_height"))

        _last_report[protocol] = time.time()

        profile = body.get("impairment_profile")
        if profile:
            _counters["impairment_profile_changes"][profile] = \
                _counters["impairment_profile_changes"].get(profile, 0) + 1


def _prometheus_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _render_prometheus() -> str:
    lines = []

    def _gauge(name, help_text, value, labels: dict):
        label_str = ",".join(
            f'{k}="{_prometheus_escape(str(v))}"' for k, v in labels.items()
        )
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} gauge")
        lines.append(f"{name}{{{label_str}}} {value}")

    def _counter(name, help_text, value, labels: dict):
        label_str = ",".join(
            f'{k}="{_prometheus_escape(str(v))}"' for k, v in labels.items()
        )
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} counter")
        lines.append(f"{name}{{{label_str}}} {value}")

    with _lock:
        for proto, g in _gauges.items():
            if not g:
                continue

            if "latency_seconds" in g:
                _gauge("player_latency_seconds",
                       "End-to-end playback latency in seconds",
                       g["latency_seconds"], {"protocol": proto})

            if "startup_ms" in g:
                _gauge("player_startup_ms",
                       "Time from page load to first frame in ms",
                       g["startup_ms"], {"protocol": proto})

            if "stalls_total" in g:
                _gauge("player_stalls_total",
                       "Cumulative number of playback stalls",
                       g["stalls_total"], {"protocol": proto})

            if "stall_duration_ms" in g:
                _gauge("player_stall_duration_ms",
                       "Cumulative rebuffering duration in ms",
                       g["stall_duration_ms"], {"protocol": proto})

            if "bitrate_bps" in g:
                _gauge("player_bitrate_bps",
                       "Most-recent segment bitrate in bits/s",
                       g["bitrate_bps"], {"protocol": proto})

            if "resolution_width" in g:
                _gauge("player_resolution_width",
                       "Decoded video width in pixels",
                       g["resolution_width"], {"protocol": proto})

            if "resolution_height" in g:
                _gauge("player_resolution_height",
                       "Decoded video height in pixels",
                       g["resolution_height"], {"protocol": proto})

        for proto, ts in _last_report.items():
            _gauge("metrics_last_report_timestamp_seconds",
                   "Unix timestamp of the most-recent browser report",
                   ts, {"protocol": proto})

        for profile, count in _counters["impairment_profile_changes"].items():
            _counter("impairment_profile_changes_total",
                     "Total times an impairment profile has been applied",
                     count, {"profile": profile})

    lines.append("")
    return "\n".join(lines)


def _render_snapshot() -> dict:
    with _lock:
        return {
            "gauges": {k: dict(v) for k, v in _gauges.items()},
            "last_report": dict(_last_report),
            "counters": {k: dict(v) for k, v in _counters.items()},
        }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[metrics] {self.address_string()} {fmt % args}")

    def _send(self, code: int, content_type: str, body: bytes):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/metrics":
            body = _render_prometheus().encode()
            self._send(200, "text/plain; version=0.0.4; charset=utf-8", body)
        elif path == "/snapshot":
            body = json.dumps(_render_snapshot(), indent=2).encode()
            self._send(200, "application/json", body)
        elif path in ("/health", "/"):
            self._send(200, "text/plain", b"ok\n")
        else:
            self._send(404, "text/plain", b"not found\n")

    def do_POST(self):
        path = self.path.split("?")[0]
        if path != "/report":
            self._send(404, "text/plain", b"not found\n")
            return

        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw)
        except json.JSONDecodeError as e:
            self._send(400, "application/json",
                       json.dumps({"error": str(e)}).encode())
            return

        _record_report(body)
        self._send(200, "application/json", b'{"ok":true}')


if __name__ == "__main__":
    port = int(os.environ.get("METRICS_PORT", 9090))
    print(f"[metrics] listening on :{port}")
    server = HTTPServer(("0.0.0.0", port), Handler)
    server.serve_forever()
