#!/usr/bin/env python3
"""
collector.py — moqompare metrics + presentation state collector

Receives browser metric reports and exposes them as:
  GET /metrics                — Prometheus text format
  GET /snapshot               — JSON snapshot (for debugging)
  POST /report                — per-protocol metric reports

Presentation mode adds:
  GET /presentation/snapshot  — combined state + audience telemetry
  GET /presentation/state     — presenter-controlled audience state
  POST /presentation/state    — shallow-merge presenter state
  GET /presentation/telemetry — most-recent audience telemetry
  POST /presentation/telemetry— audience telemetry push
  GET /presentation/events    — SSE stream for state/telemetry changes
"""

import copy
import json
import os
import time
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_lock = threading.Lock()
_presentation_cv = threading.Condition(_lock)


def _deep_merge(target: dict, patch: dict) -> dict:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_merge(target[key], value)
        else:
            target[key] = value
    return target


def _json_copy(value):
    return json.loads(json.dumps(value))


def _presentation_default_state() -> dict:
    return {
        "sceneId": "opening",
        "headline": "One live source, two delivery paths",
        "subhead": (
            "The same live video moves through HLS and MoQ so an executive audience "
            "can see how delivery behavior changes under stress."
        ),
        "activeImpairment": "baseline",
        "focus": "split",
        "showVideos": True,
        "showSharedTelemetry": True,
        "showTelemetry": True,
        "overlay": {
            "title": "Ready for baseline comparison",
            "body": "Both protocols are healthy. Use the presenter console to guide the story.",
            "tone": "good",
        },
        "spotlight": {
            "nodes": ["source", "packager", "origin", "manifest-proxy", "relay", "viewer-hls", "viewer-moq"],
            "edges": ["hls", "moq"],
        },
        "promotedMetrics": ["liveLatency", "stallCount", "bitrate"],
        "updatedAt": 0,
    }


def _presentation_default_telemetry() -> dict:
    return {
        "protocols": {
            "hls": {},
            "moq": {},
        },
        "comparison": {
            "drift_seconds": None,
            "experience_gap_label": "measuring…",
        },
        "status": {
            "audience_connected": False,
            "last_report_ts": 0,
        },
        "updatedAt": 0,
    }


# Per-protocol gauge values (most-recent report)
_gauges: dict[str, dict] = {
    "hls": {},
    "moq": {},
}

# Counters that only increase
_counters: dict[str, dict] = {
    "impairment_profile_changes": {},
}

_last_report: dict[str, float] = {}

_presentation = {
    "state": _presentation_default_state(),
    "telemetry": _presentation_default_telemetry(),
    "version": 0,
    "event": "init",
}


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
        _set("startup_ms", body.get("startup_ms"))
        _set("stalls_total", body.get("stalls_total"))
        _set("stall_duration_ms", body.get("stall_duration_ms"))
        _set("bitrate_bps", body.get("bitrate_bps"))
        _set("resolution_width", body.get("resolution_width"))
        _set("resolution_height", body.get("resolution_height"))

        _last_report[protocol] = time.time()

        profile = body.get("impairment_profile")
        if profile:
            _counters["impairment_profile_changes"][profile] = (
                _counters["impairment_profile_changes"].get(profile, 0) + 1
            )


def _presentation_snapshot_unlocked() -> dict:
    return {
        "state": copy.deepcopy(_presentation["state"]),
        "telemetry": copy.deepcopy(_presentation["telemetry"]),
        "version": _presentation["version"],
        "event": _presentation["event"],
    }


def _publish_presentation_update(event_name: str) -> dict:
    _presentation["version"] += 1
    _presentation["event"] = event_name
    snapshot = _presentation_snapshot_unlocked()
    _presentation_cv.notify_all()
    return snapshot


def _update_presentation_state(patch: dict) -> dict:
    with _presentation_cv:
        _deep_merge(_presentation["state"], patch)
        _presentation["state"]["updatedAt"] = time.time()
        return _publish_presentation_update("state")


def _update_presentation_telemetry(payload: dict) -> dict:
    with _presentation_cv:
        protocols = payload.get("protocols", {})
        for proto in ("hls", "moq"):
            data = protocols.get(proto)
            if isinstance(data, dict):
                _presentation["telemetry"]["protocols"][proto] = data

        comparison = payload.get("comparison")
        if isinstance(comparison, dict):
            _deep_merge(_presentation["telemetry"]["comparison"], comparison)

        status = payload.get("status")
        if isinstance(status, dict):
            _deep_merge(_presentation["telemetry"]["status"], status)

        _presentation["telemetry"]["status"]["audience_connected"] = True
        _presentation["telemetry"]["status"]["last_report_ts"] = time.time()
        _presentation["telemetry"]["updatedAt"] = time.time()
        return _publish_presentation_update("telemetry")


def _render_presentation_snapshot() -> dict:
    with _lock:
        return _presentation_snapshot_unlocked()


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
                _gauge(
                    "player_latency_seconds",
                    "End-to-end playback latency in seconds",
                    g["latency_seconds"],
                    {"protocol": proto},
                )

            if "startup_ms" in g:
                _gauge(
                    "player_startup_ms",
                    "Time from page load to first frame in ms",
                    g["startup_ms"],
                    {"protocol": proto},
                )

            if "stalls_total" in g:
                _gauge(
                    "player_stalls_total",
                    "Cumulative number of playback stalls",
                    g["stalls_total"],
                    {"protocol": proto},
                )

            if "stall_duration_ms" in g:
                _gauge(
                    "player_stall_duration_ms",
                    "Cumulative rebuffering duration in ms",
                    g["stall_duration_ms"],
                    {"protocol": proto},
                )

            if "bitrate_bps" in g:
                _gauge(
                    "player_bitrate_bps",
                    "Most-recent segment bitrate in bits/s",
                    g["bitrate_bps"],
                    {"protocol": proto},
                )

            if "resolution_width" in g:
                _gauge(
                    "player_resolution_width",
                    "Decoded video width in pixels",
                    g["resolution_width"],
                    {"protocol": proto},
                )

            if "resolution_height" in g:
                _gauge(
                    "player_resolution_height",
                    "Decoded video height in pixels",
                    g["resolution_height"],
                    {"protocol": proto},
                )

        for proto, ts in _last_report.items():
            _gauge(
                "metrics_last_report_timestamp_seconds",
                "Unix timestamp of the most-recent browser report",
                ts,
                {"protocol": proto},
            )

        for profile, count in _counters["impairment_profile_changes"].items():
            _counter(
                "impairment_profile_changes_total",
                "Total times an impairment profile has been applied",
                count,
                {"profile": profile},
            )

        presentation_ts = _presentation["telemetry"]["status"].get("last_report_ts", 0)
        _gauge(
            "presentation_audience_last_report_timestamp_seconds",
            "Unix timestamp of the most-recent presentation audience telemetry push",
            presentation_ts,
            {},
        )

    lines.append("")
    return "\n".join(lines)


def _render_snapshot() -> dict:
    with _lock:
        return {
            "gauges": {k: dict(v) for k, v in _gauges.items()},
            "last_report": dict(_last_report),
            "counters": {k: dict(v) for k, v in _counters.items()},
            "presentation": _presentation_snapshot_unlocked(),
        }


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        print(f"[metrics] {self.address_string()} {fmt % args}")

    def _send(self, code: int, content_type: str, body: bytes):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, code: int, payload: dict):
        self._send(code, "application/json", json.dumps(payload, indent=2).encode())

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        try:
            return json.loads(raw) if raw else {}
        except json.JSONDecodeError as e:
            self._send_json(400, {"error": str(e)})
            return None

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
            self._send_json(200, _render_snapshot())
        elif path == "/presentation/snapshot":
            self._send_json(200, _render_presentation_snapshot())
        elif path == "/presentation/state":
            self._send_json(200, _render_presentation_snapshot()["state"])
        elif path == "/presentation/telemetry":
            self._send_json(200, _render_presentation_snapshot()["telemetry"])
        elif path == "/presentation/events":
            self._handle_presentation_events()
        elif path in ("/health", "/"):
            self._send(200, "text/plain", b"ok\n")
        else:
            self._send(404, "text/plain", b"not found\n")

    def _handle_presentation_events(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        with _presentation_cv:
            snapshot = _presentation_snapshot_unlocked()
            version = snapshot["version"]

        try:
            self.wfile.write(f"event: update\ndata: {json.dumps(snapshot)}\n\n".encode())
            self.wfile.flush()
            while True:
                with _presentation_cv:
                    changed = _presentation_cv.wait_for(
                        lambda: _presentation["version"] != version,
                        timeout=15.0,
                    )
                    if changed:
                        snapshot = _presentation_snapshot_unlocked()
                        version = snapshot["version"]
                        payload = f"event: update\ndata: {json.dumps(snapshot)}\n\n"
                    else:
                        payload = ": keep-alive\n\n"
                self.wfile.write(payload.encode())
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return

    def do_POST(self):
        path = self.path.split("?")[0]
        if path == "/report":
            body = self._read_json_body()
            if body is None:
                return
            _record_report(body)
            self._send(200, "application/json", b'{"ok":true}')
            return

        if path == "/presentation/state":
            body = self._read_json_body()
            if body is None or not isinstance(body, dict):
                return
            patch = body.get("state") if isinstance(body.get("state"), dict) else body
            snapshot = _update_presentation_state(patch)
            self._send_json(200, snapshot)
            return

        if path == "/presentation/telemetry":
            body = self._read_json_body()
            if body is None or not isinstance(body, dict):
                return
            snapshot = _update_presentation_telemetry(body)
            self._send_json(200, snapshot)
            return

        self._send(404, "text/plain", b"not found\n")


if __name__ == "__main__":
    port = int(os.environ.get("METRICS_PORT", 9090))
    print(f"[metrics] listening on :{port}")
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    server.serve_forever()
