#!/usr/bin/env python3
"""
server.py — backend-owned MoQ program republisher

Polls the registry for the desired program route and maintains a stable MoQ
broadcast (`stream_program`) by running moq-cli against the selected upstream
HLS playlist.
"""

import json
import os
import subprocess
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


PORT = int(os.environ.get("REPUBLISHER_PORT", "8094"))
REGISTRY_URL = os.environ.get("REGISTRY_URL", "http://registry:8093").rstrip("/")
RELAY_URL = os.environ.get("RELAY_URL", "http://relay:4443")
PROGRAM_STREAM_NAME = os.environ.get("PROGRAM_STREAM_NAME", "stream_program")
POLL_INTERVAL_SECS = float(os.environ.get("REPUBLISHER_POLL_INTERVAL_SECS", "1.0"))

_lock = threading.Lock()
_proc: subprocess.Popen | None = None
_state = {
    "broadcast_name": PROGRAM_STREAM_NAME,
    "running": False,
    "current_source_id": None,
    "current_source_label": None,
    "current_playlist_url": None,
    "desired_source_id": None,
    "desired_playlist_url": None,
    "last_switch_at": None,
    "last_registry_poll_at": 0.0,
    "restart_count": 0,
    "last_error": "",
    "proc_pid": None,
}


def _log(message: str) -> None:
    print(f"[republisher] {message}", flush=True)


def _snapshot() -> dict:
    with _lock:
        return json.loads(json.dumps(_state))


def _set_error(message: str) -> None:
    with _lock:
        _state["last_error"] = message


def _drain_output(proc: subprocess.Popen) -> None:
    try:
        for line in proc.stdout:
            _log(f"moq-cli: {line.decode(errors='replace').rstrip()}")
    except Exception:
        pass


def _stop_process() -> None:
    global _proc
    proc = _proc
    if proc is None:
        with _lock:
            _state["running"] = False
            _state["proc_pid"] = None
        return

    _log("stopping program publisher")
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except Exception as exc:
        _log(f"publisher stop error: {exc}")
        try:
            proc.kill()
        except Exception:
            pass
    _proc = None
    with _lock:
        _state["running"] = False
        _state["proc_pid"] = None


def _start_process(source_id: str, source_label: str, playlist_url: str) -> None:
    global _proc

    cmd = [
        "moq-cli",
        "publish",
        "--url",
        RELAY_URL,
        "--name",
        PROGRAM_STREAM_NAME,
        "hls",
        "--playlist",
        playlist_url,
    ]
    _log(
        "starting program publisher "
        f"source_id={source_id} label={source_label} playlist={playlist_url}"
    )
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
    except Exception as exc:
        _set_error(f"failed to start moq-cli: {exc}")
        _log(_state["last_error"])
        _proc = None
        with _lock:
            _state["running"] = False
            _state["proc_pid"] = None
        return

    _proc = proc
    threading.Thread(target=_drain_output, args=(proc,), daemon=True).start()
    with _lock:
        _state["running"] = True
        _state["current_source_id"] = source_id
        _state["current_source_label"] = source_label
        _state["current_playlist_url"] = playlist_url
        _state["last_switch_at"] = time.time()
        _state["restart_count"] += 1
        _state["last_error"] = ""
        _state["proc_pid"] = proc.pid


def _switch_program(source_id: str, source_label: str, playlist_url: str) -> None:
    _stop_process()
    _start_process(source_id, source_label, playlist_url)


def _fetch_registry_snapshot() -> dict | None:
    try:
        with urllib.request.urlopen(f"{REGISTRY_URL}/api/status", timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        _set_error(f"registry poll failed: {exc}")
        return None
    except Exception as exc:
        _set_error(f"registry poll failed: {exc}")
        return None

    with _lock:
        _state["last_registry_poll_at"] = time.time()
    return payload


def _poll_registry_forever() -> None:
    global _proc

    while True:
        time.sleep(POLL_INTERVAL_SECS)
        snapshot = _fetch_registry_snapshot()
        if snapshot is None:
            continue

        program = snapshot.get("program") or {}
        stream = program.get("stream") or {}
        republish = stream.get("republish") or {}
        source_id = stream.get("id")
        source_label = stream.get("label")
        playlist_url = republish.get("playlist_url")

        with _lock:
            _state["desired_source_id"] = source_id
            _state["desired_playlist_url"] = playlist_url
            proc = _proc
            current_source_id = _state["current_source_id"]
            current_playlist_url = _state["current_playlist_url"]
            if proc is not None and proc.poll() is not None:
                _log(f"program publisher exited rc={proc.returncode}")
                _proc = None
                _state["running"] = False
                _state["proc_pid"] = None
                proc = None

        if not source_id or not playlist_url:
            if proc is not None:
                _log("route has no republishable playlist — stopping program publisher")
                _stop_process()
            continue

        if proc is None:
            _start_process(source_id, source_label or source_id, playlist_url)
            continue

        if (
            current_source_id != source_id
            or current_playlist_url != playlist_url
        ):
            _switch_program(source_id, source_label or source_id, playlist_url)


class Handler(BaseHTTPRequestHandler):
    server_version = "moqompare-republisher/0.1"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        _log(f"{self.address_string()} {fmt % args}")

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        if self.path == "/health":
            self._text(200, "ok\n")
            return
        if self.path == "/status":
            self._json(200, _snapshot())
            return
        self._json(404, {"error": "not found"})

    def _json(self, status: int, data: dict):
        encoded = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache, no-store")
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _text(self, status: int, body: str):
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache, no-store")
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def main() -> None:
    _log(
        "starting program republisher "
        f"broadcast={PROGRAM_STREAM_NAME} registry={REGISTRY_URL} relay={RELAY_URL}"
    )
    threading.Thread(target=_poll_registry_forever, daemon=True).start()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
