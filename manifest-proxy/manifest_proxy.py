#!/usr/bin/env python3
"""
manifest_proxy.py — HLS manifest freeze proxy + SCTE-35 cue injector

Normally proxies all *.m3u8 requests to origin and caches each response.
When frozen (POST /freeze), returns the cached snapshot instead of fetching
a fresh manifest — simulating stale manifests received by HLS players.

MoQ is unaffected: the relay pushes new objects directly; no manifest is polled.

SCTE-35 cue injection: POST /cue_out?duration=<secs> causes the next live
manifest response to include an EXT-X-CUE-OUT tag before the last segment,
simulating an ad break signal. POST /cue_in clears the cue state.

Endpoints:
  GET  /hls/<path>.m3u8        — proxy (or frozen) manifest
  POST /freeze                 — start serving frozen manifests
  POST /unfreeze               — resume live proxying, clear cache
  POST /cue_out?duration=<N>  — inject EXT-X-CUE-OUT into next manifest
  POST /cue_in                 — clear cue state (EXT-X-CUE-IN)
  GET  /status                 — {"frozen": bool, "cached": int, "cue_active": bool, "cue_duration": int}
  GET  /health                 — 200 "ok"
"""

import json
import os
import threading
import time
import urllib.request
import urllib.error
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

ORIGIN_URL = os.environ.get("ORIGIN_URL", "http://origin").rstrip("/")
PORT       = int(os.environ.get("MANIFEST_PROXY_PORT", 8091))

_lock   = threading.Lock()
_frozen = False
_cache: dict[str, bytes] = {}   # path → last live response body

# SCTE-35 cue state
_cue_active:   bool = False
_cue_duration: int  = 30
_cue_injected: bool = False   # True once we've emitted EXT-X-CUE-OUT in a response
_cue_trace_id: str = ""
_cue_armed_at: float | None = None
_cue_injected_at: float | None = None
_cue_injected_path: str = ""


def _inject_cue_out(body: bytes, duration: int) -> bytes:
    """Inject #EXT-X-CUE-OUT:DURATION=<N> before the last #EXTINF line."""
    try:
        text  = body.decode("utf-8")
        lines = text.splitlines()
        # Find the last #EXTINF line index
        last_extinf = -1
        for i, line in enumerate(lines):
            if line.startswith("#EXTINF:"):
                last_extinf = i
        if last_extinf >= 0:
            lines.insert(last_extinf, f"#EXT-X-CUE-OUT:DURATION={duration}")
        return "\n".join(lines).encode("utf-8")
    except Exception as e:
        print(f"[manifest-proxy] cue inject error: {e}", flush=True)
        return body


class Handler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        print(f"[manifest-proxy] {self.address_string()} {fmt % args}", flush=True)

    # ── GET ───────────────────────────────────────────────────────────────────

    def do_GET(self):
        if self.path in ("/health", "/status") or self.path == "":
            if self.path == "/status":
                with _lock:
                    self._json(200, {
                        "frozen":     _frozen,
                        "cached":     len(_cache),
                        "cue_active": _cue_active,
                        "cue_duration": _cue_duration,
                        "cue_injected": _cue_injected,
                        "cue_trace_id": _cue_trace_id,
                        "cue_armed_at": _cue_armed_at,
                        "cue_injected_at": _cue_injected_at,
                        "cue_injected_path": _cue_injected_path,
                    })
            else:
                self._text(200, "ok")
            return

        # All other GETs are manifest proxy requests
        with _lock:
            frozen_now = _frozen
            cached     = _cache.get(self.path)

        if frozen_now and cached is not None:
            print(f"[manifest-proxy] FROZEN  {self.path} ({len(cached)}b)", flush=True)
            self._manifest(200, cached)
        else:
            self._proxy()

    # ── POST ──────────────────────────────────────────────────────────────────

    def do_POST(self):
        global _frozen, _cue_active, _cue_duration, _cue_injected
        global _cue_trace_id, _cue_armed_at, _cue_injected_at, _cue_injected_path
        if self.path == "/freeze":
            with _lock:
                _frozen = True
                n = len(_cache)
            print(f"[manifest-proxy] FREEZE — {n} path(s) cached", flush=True)
            self._json(200, {"ok": True, "frozen": True, "cached": n})

        elif self.path == "/unfreeze":
            with _lock:
                _frozen = False
                _cache.clear()
            print("[manifest-proxy] UNFREEZE — cache cleared", flush=True)
            self._json(200, {"ok": True, "frozen": False})

        elif self.path.startswith("/cue_out"):
            # Parse optional ?duration=N from path query string
            import urllib.parse as _up
            qs  = dict(_up.parse_qsl(_up.urlparse(self.path).query))
            dur = int(qs.get("duration", 30))
            trace_id = qs.get("trace_id", "")
            with _lock:
                _cue_active   = True
                _cue_duration = dur
                _cue_injected = False
                _cue_trace_id = trace_id
                _cue_armed_at = time.time()
                _cue_injected_at = None
                _cue_injected_path = ""
            print(
                f"[manifest-proxy] CUE-OUT armed — duration={dur}s trace_id={trace_id or '-'}",
                flush=True,
            )
            self._json(
                200,
                {
                    "ok": True,
                    "cue_active": True,
                    "duration": dur,
                    "trace_id": trace_id,
                },
            )

        elif self.path == "/cue_in":
            with _lock:
                _cue_active   = False
                _cue_injected = False
                cleared_trace_id = _cue_trace_id
                _cue_trace_id = ""
                _cue_armed_at = None
                _cue_injected_at = None
                _cue_injected_path = ""
            print(
                f"[manifest-proxy] CUE-IN — cue cleared trace_id={cleared_trace_id or '-'}",
                flush=True,
            )
            self._json(200, {"ok": True, "cue_active": False, "trace_id": cleared_trace_id})

        else:
            self._json(404, {"error": "not found"})

    # ── Proxy ─────────────────────────────────────────────────────────────────

    def _proxy(self):
        global _cue_injected, _cue_injected_at, _cue_injected_path
        url = ORIGIN_URL + self.path
        try:
            req = urllib.request.Request(url, headers={"Connection": "close"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                body = resp.read()
            with _lock:
                trace_id = _cue_trace_id
                if (
                    _cue_active
                    and not _cue_injected
                    and self.path.endswith(".m3u8")
                ):
                    injected = _inject_cue_out(body, _cue_duration)
                    if injected != body:
                        body = injected
                        _cue_injected = True
                        _cue_injected_at = time.time()
                        _cue_injected_path = self.path
                        print(
                            "[manifest-proxy] CUE-OUT injected — "
                            f"path={self.path} duration={_cue_duration}s trace_id={trace_id or '-'}",
                            flush=True,
                        )
            with _lock:
                _cache[self.path] = body
            self._manifest(200, body)
        except urllib.error.HTTPError as e:
            body = e.read()
            self._manifest(e.code, body)
        except Exception as exc:
            print(f"[manifest-proxy] proxy error {url}: {exc}", flush=True)
            self.send_response(502)
            self.end_headers()

    # ── Response helpers ──────────────────────────────────────────────────────

    def _manifest(self, status: int, body: bytes):
        self.send_response(status)
        self.send_header("Content-Type", "application/vnd.apple.mpegurl")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache, no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, data: dict):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _text(self, status: int, text: str):
        body = text.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    print(f"[manifest-proxy] listening on :{PORT} → {ORIGIN_URL}", flush=True)
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    server.serve_forever()
