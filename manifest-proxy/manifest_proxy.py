#!/usr/bin/env python3
"""
manifest_proxy.py — HLS manifest freeze proxy

Normally proxies all *.m3u8 requests to origin and caches each response.
When frozen (POST /freeze), returns the cached snapshot instead of fetching
a fresh manifest — simulating stale manifests received by HLS players.

MoQ is unaffected: the relay pushes new objects directly; no manifest is polled.

Endpoints:
  GET  /hls/<path>.m3u8   — proxy (or frozen) manifest
  POST /freeze            — start serving frozen manifests
  POST /unfreeze          — resume live proxying, clear cache
  GET  /status            — {"frozen": bool, "cached": int}
  GET  /health            — 200 "ok"
"""

import json
import os
import threading
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer

ORIGIN_URL = os.environ.get("ORIGIN_URL", "http://origin").rstrip("/")
PORT       = int(os.environ.get("MANIFEST_PROXY_PORT", 8091))

_lock   = threading.Lock()
_frozen = False
_cache: dict[str, bytes] = {}   # path → last live response body


class Handler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        print(f"[manifest-proxy] {self.address_string()} {fmt % args}", flush=True)

    # ── GET ───────────────────────────────────────────────────────────────────

    def do_GET(self):
        if self.path in ("/health", "/status") or self.path == "":
            if self.path == "/status":
                with _lock:
                    self._json(200, {"frozen": _frozen, "cached": len(_cache)})
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
        global _frozen
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

        else:
            self._json(404, {"error": "not found"})

    # ── Proxy ─────────────────────────────────────────────────────────────────

    def _proxy(self):
        url = ORIGIN_URL + self.path
        try:
            req = urllib.request.Request(url, headers={"Connection": "close"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                body = resp.read()
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
