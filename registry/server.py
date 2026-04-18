#!/usr/bin/env python3
"""
server.py — MoQ production stream registry

Lightweight control-plane service for the production workspace demo.

Responsibilities:
  1. Maintain a discoverable catalog of streams.
  2. Accept publisher registration and heartbeat updates.
  3. Track the current "program" route intent.
  4. Broadcast stream/route events to the UI via Server-Sent Events.

This production slice keeps a seeded standby artifact, while camera-style
production feeds register themselves dynamically with heartbeat updates.
"""

import copy
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Condition
from urllib.parse import parse_qs, urlparse


PORT = int(os.environ.get("REGISTRY_PORT", "8093"))
STREAM_TTL_SECS = int(os.environ.get("REGISTRY_STREAM_TTL_SECS", "15"))

_cv = Condition()


def _now() -> float:
    return time.time()


def _seed_streams() -> dict[str, dict]:
    ts = _now()
    return {
        "cam-a": {
            "id": "cam-a",
            "namespace": "lab/source/cam-a",
            "label": "Camera A",
            "kind": "camera",
            "summary": "Bootstrap entry for the coastal-waves alternate-angle feed. The live camera service overwrites this entry when it registers.",
            "status": "seeded",
            "previewable": True,
            "media_ready": True,
            "dynamic": False,
            "derived_from": [],
            "tags": ["line-cut", "primary", "alt-angle"],
            "playback": {
                "protocol": "moq",
                "stream_name": "stream_cam_a",
                "latency": 500,
                "note": "Published from the dedicated Camera A alternate-angle feed with a small fixed buffer to smooth bursty HLS-to-MoQ delivery.",
            },
            "republish": {
                "protocol": "hls",
                "playlist_url": "http://origin/hls/angles/cam-a/master.m3u8",
                "note": "Republisher ingests the dedicated Camera A HLS feed for the stable program broadcast.",
            },
            "last_seen_at": ts,
        },
        "cam-b": {
            "id": "cam-b",
            "namespace": "lab/source/cam-b",
            "label": "Camera B",
            "kind": "camera",
            "summary": "Bootstrap entry for the island-coast aerial alternate-angle feed. The live camera service overwrites this entry when it registers.",
            "status": "seeded",
            "previewable": True,
            "media_ready": True,
            "dynamic": False,
            "derived_from": [],
            "tags": ["alternate", "secondary", "alt-angle"],
            "playback": {
                "protocol": "moq",
                "stream_name": "stream_cam_b",
                "latency": 500,
                "note": "Published from the dedicated Camera B alternate-angle feed with a small fixed buffer to smooth bursty HLS-to-MoQ delivery.",
            },
            "republish": {
                "protocol": "hls",
                "playlist_url": "http://origin/hls/angles/cam-b/master.m3u8",
                "note": "Republisher ingests the dedicated Camera B HLS feed for the stable program broadcast.",
            },
            "last_seen_at": ts,
        },
        "slate": {
            "id": "slate",
            "namespace": "lab/source/slate",
            "label": "Standby Slate",
            "kind": "slate",
            "summary": "Always-on standby artifact backed by the tropical-ocean-coast file from /videos/alt-angles.",
            "status": "seeded",
            "previewable": True,
            "media_ready": True,
            "dynamic": False,
            "derived_from": [],
            "tags": ["standby", "artifact", "alt-angle"],
            "playback": {
                "protocol": "moq",
                "stream_name": "stream_slate",
                "latency": 500,
                "note": "Publishes the dedicated standby slate feed into the relay for preview and routing with a small fixed buffer to smooth bursty HLS-to-MoQ delivery.",
            },
            "republish": {
                "protocol": "hls",
                "playlist_url": "http://origin/hls/angles/slate/master.m3u8",
                "note": "Republisher ingests the dedicated standby slate HLS feed for the stable program broadcast.",
            },
            "last_seen_at": ts,
        },
    }


def _default_program_route() -> dict:
    ts = _now()
    return {
        "output_namespace": "lab/program/main",
        "output_stream_name": "stream_program",
        "playback": {
            "protocol": "moq",
            "stream_name": "stream_program",
            "latency": 750,
            "note": "Stable backend-owned program broadcast published by the republisher service with a small fixed buffer to smooth bursty HLS-to-MoQ delivery.",
        },
        "route_stream_id": "cam-a",
        "stream_id": "cam-a",
        "source_namespace": "lab/source/cam-a",
        "modifier": {
            "active": False,
            "stream_id": None,
            "type": None,
            "label": None,
            "applied_at": None,
        },
        "updated_at": ts,
        "effective_updated_at": ts,
    }


_state = {
    "streams": _seed_streams(),
    "routes": {
        "program": _default_program_route(),
    },
    "version": 0,
    "last_event": None,
    "events": [],
}


def _log(message: str) -> None:
    print(f"[registry] {message}", flush=True)


def _json_copy(value):
    return json.loads(json.dumps(value))


def _sorted_streams_unlocked() -> list[dict]:
    streams = list(_state["streams"].values())
    streams.sort(key=lambda item: item["id"])
    return [_json_copy(item) for item in streams]


def _effective_program_stream_id_unlocked(program: dict) -> str | None:
    modifier = program.get("modifier") or {}
    if modifier.get("active") and modifier.get("stream_id"):
        return str(modifier["stream_id"])
    return program.get("route_stream_id") or program.get("stream_id")


def _sync_program_state_unlocked(program: dict, *, effective_changed: bool) -> None:
    effective_stream_id = _effective_program_stream_id_unlocked(program)
    effective_stream = _state["streams"].get(effective_stream_id, {})
    program["stream_id"] = effective_stream_id
    program["source_namespace"] = effective_stream.get("namespace", "")
    if effective_changed:
        program["effective_updated_at"] = _now()


def _snapshot_unlocked() -> dict:
    program = copy.deepcopy(_state["routes"]["program"])
    current_stream = copy.deepcopy(_state["streams"].get(program.get("stream_id"), {}))
    route_stream = copy.deepcopy(_state["streams"].get(program.get("route_stream_id"), {}))
    modifier = copy.deepcopy(program.get("modifier") or {})
    modifier_stream = copy.deepcopy(_state["streams"].get(modifier.get("stream_id"), {}))
    return {
        "streams": _sorted_streams_unlocked(),
        "routes": copy.deepcopy(_state["routes"]),
        "program": {
            **program,
            "stream": current_stream,
            "source_label": current_stream.get("label"),
            "source_playback": copy.deepcopy(current_stream.get("playback")),
            "source_republish": copy.deepcopy(current_stream.get("republish")),
            "route_stream": route_stream,
            "route_source_label": route_stream.get("label"),
            "route_source_namespace": route_stream.get("namespace"),
            "route_source_playback": copy.deepcopy(route_stream.get("playback")),
            "route_source_republish": copy.deepcopy(route_stream.get("republish")),
            "modifier_stream": modifier_stream,
            "modifier_label": modifier.get("label"),
        },
        "version": _state["version"],
        "last_event": copy.deepcopy(_state["last_event"]),
        "events": copy.deepcopy(_state["events"]),
        "stream_ttl_secs": STREAM_TTL_SECS,
    }


def _append_event_unlocked(event_type: str, message: str, data: dict | None = None) -> dict:
    _state["version"] += 1
    event = {
        "id": _state["version"],
        "type": event_type,
        "message": message,
        "timestamp": _now(),
        "data": data or {},
    }
    _state["last_event"] = copy.deepcopy(event)
    _state["events"].append(copy.deepcopy(event))
    if len(_state["events"]) > 60:
        _state["events"] = _state["events"][-60:]
    _cv.notify_all()
    return copy.deepcopy(event)


def _mark_stale_streams_unlocked() -> None:
    now = _now()
    stale_ids: list[str] = []
    for stream_id, stream in _state["streams"].items():
        if not stream.get("dynamic"):
            continue
        if stream.get("status") == "stale":
            continue
        if now - float(stream.get("last_seen_at", 0)) > STREAM_TTL_SECS:
            stream["status"] = "stale"
            stale_ids.append(stream_id)

    for stream_id in stale_ids:
        stream = _state["streams"][stream_id]
        _append_event_unlocked(
            "stream_stale",
            f"{stream['label']} marked stale after {STREAM_TTL_SECS}s without a heartbeat",
            {
                "stream_id": stream_id,
                "namespace": stream["namespace"],
                "status": stream["status"],
            },
        )
        _log(
            f"stream stale id={stream_id} namespace={stream['namespace']} ttl={STREAM_TTL_SECS}s"
        )


def _normalize_stream_payload(payload: dict, *, dynamic: bool) -> dict:
    stream_id = str(payload.get("id", "")).strip()
    namespace = str(payload.get("namespace", "")).strip()
    label = str(payload.get("label", "")).strip()

    if not stream_id or not namespace or not label:
        raise ValueError("fields 'id', 'namespace', and 'label' are required")

    tags = payload.get("tags") or []
    if not isinstance(tags, list):
        raise ValueError("field 'tags' must be a list when provided")
    playback = payload.get("playback")
    if playback is not None and not isinstance(playback, dict):
        raise ValueError("field 'playback' must be an object when provided")
    republish = payload.get("republish")
    if republish is not None and not isinstance(republish, dict):
        raise ValueError("field 'republish' must be an object when provided")

    now = _now()
    return {
        "id": stream_id,
        "namespace": namespace,
        "label": label,
        "kind": str(payload.get("kind", "source")).strip() or "source",
        "summary": str(payload.get("summary", "")).strip(),
        "status": str(payload.get("status", "healthy")).strip() or "healthy",
        "previewable": bool(payload.get("previewable", False)),
        "media_ready": bool(payload.get("media_ready", False)),
        "dynamic": dynamic,
        "derived_from": payload.get("derived_from") or [],
        "tags": [str(tag) for tag in tags if str(tag).strip()],
        "playback": playback or None,
        "republish": republish or None,
        "last_seen_at": now,
    }


def _merge_stream_registration_unlocked(payload: dict) -> dict:
    stream = _normalize_stream_payload(payload, dynamic=True)
    previous = _state["streams"].get(stream["id"])
    if previous:
        previous.update(stream)
        result = previous
        action = "updated"
    else:
        _state["streams"][stream["id"]] = stream
        result = _state["streams"][stream["id"]]
        action = "registered"

    _append_event_unlocked(
        "stream_registered",
        f"{result['label']} {action} in catalog",
        {
            "stream_id": result["id"],
            "namespace": result["namespace"],
            "kind": result["kind"],
            "status": result["status"],
        },
    )
    _log(
        f"stream {action} id={result['id']} namespace={result['namespace']} status={result['status']}"
    )
    return copy.deepcopy(result)


def _heartbeat_stream_unlocked(payload: dict) -> dict:
    stream_id = str(payload.get("id", "")).strip()
    if not stream_id:
        raise ValueError("field 'id' is required")
    stream = _state["streams"].get(stream_id)
    if not stream:
        raise KeyError(stream_id)

    stream["last_seen_at"] = _now()
    if payload.get("status"):
        stream["status"] = str(payload["status"]).strip()
    elif stream.get("dynamic"):
        stream["status"] = "healthy"

    event = _append_event_unlocked(
        "stream_heartbeat",
        f"heartbeat received from {stream['label']}",
        {
            "stream_id": stream["id"],
            "namespace": stream["namespace"],
            "status": stream["status"],
        },
    )
    _log(
        f"stream heartbeat id={stream['id']} namespace={stream['namespace']} status={stream['status']}"
    )
    return event


def _set_program_route_unlocked(payload: dict) -> dict:
    stream_id = str(payload.get("stream_id", "")).strip()
    if not stream_id:
        raise ValueError("field 'stream_id' is required")
    stream = _state["streams"].get(stream_id)
    if not stream:
        raise KeyError(stream_id)

    program = _state["routes"]["program"]
    if program.get("route_stream_id") == stream_id:
        program["updated_at"] = _now()
        return {
            "changed": False,
            "program": copy.deepcopy(program),
            "stream": copy.deepcopy(stream),
        }

    program["route_stream_id"] = stream_id
    program["updated_at"] = _now()
    effective_changed = not (program.get("modifier") or {}).get("active")
    _sync_program_state_unlocked(program, effective_changed=effective_changed)
    event = _append_event_unlocked(
        "program_route_changed",
        f"Program routed to {stream['label']}",
        {
            "route_stream_id": stream_id,
            "route_source_namespace": stream["namespace"],
            "effective_stream_id": program.get("stream_id"),
            "output_namespace": program["output_namespace"],
        },
    )
    _log(
        "program route changed "
        f"route_stream_id={stream_id} effective_stream_id={program.get('stream_id')} "
        f"source={stream['namespace']} output={program['output_namespace']}"
    )
    return {
        "changed": True,
        "program": copy.deepcopy(program),
        "stream": copy.deepcopy(_state["streams"].get(program.get("stream_id"), {})),
        "route_stream": copy.deepcopy(stream),
        "event": event,
    }


def _set_program_modifier_unlocked(payload: dict) -> dict:
    modifier_stream_id = str(payload.get("stream_id", "")).strip()
    program = _state["routes"]["program"]
    modifier = program.setdefault(
        "modifier",
        {
            "active": False,
            "stream_id": None,
            "type": None,
            "label": None,
            "applied_at": None,
        },
    )

    if not modifier_stream_id:
        if not modifier.get("active"):
            program["updated_at"] = _now()
            return {
                "changed": False,
                "program": copy.deepcopy(program),
                "stream": copy.deepcopy(_state["streams"].get(program.get("stream_id"), {})),
            }

        route_stream = _state["streams"].get(program.get("route_stream_id"), {})
        modifier.update(
            {
                "active": False,
                "stream_id": None,
                "type": None,
                "label": None,
                "applied_at": None,
            }
        )
        program["updated_at"] = _now()
        _sync_program_state_unlocked(program, effective_changed=True)
        event = _append_event_unlocked(
            "program_modifier_cleared",
            f"Program modifier cleared; returning to {route_stream.get('label', 'the routed source')}",
            {
                "route_stream_id": program.get("route_stream_id"),
                "effective_stream_id": program.get("stream_id"),
                "output_namespace": program["output_namespace"],
            },
        )
        _log(
            "program modifier cleared "
            f"effective_stream_id={program.get('stream_id')} output={program['output_namespace']}"
        )
        return {
            "changed": True,
            "program": copy.deepcopy(program),
            "stream": copy.deepcopy(_state["streams"].get(program.get("stream_id"), {})),
            "route_stream": copy.deepcopy(route_stream),
            "event": event,
        }

    stream = _state["streams"].get(modifier_stream_id)
    if not stream:
        raise KeyError(modifier_stream_id)

    if modifier.get("active") and modifier.get("stream_id") == modifier_stream_id:
        program["updated_at"] = _now()
        return {
            "changed": False,
            "program": copy.deepcopy(program),
            "stream": copy.deepcopy(stream),
        }

    modifier.update(
        {
            "active": True,
            "stream_id": modifier_stream_id,
            "type": "standby" if modifier_stream_id == "slate" else stream.get("kind"),
            "label": stream.get("label"),
            "applied_at": _now(),
        }
    )
    program["updated_at"] = _now()
    _sync_program_state_unlocked(program, effective_changed=True)
    event = _append_event_unlocked(
        "program_modifier_applied",
        f"Program modifier applied: {stream['label']}",
        {
            "modifier_stream_id": modifier_stream_id,
            "effective_stream_id": program.get("stream_id"),
            "output_namespace": program["output_namespace"],
        },
    )
    _log(
        "program modifier applied "
        f"modifier_stream_id={modifier_stream_id} effective_stream_id={program.get('stream_id')} "
        f"output={program['output_namespace']}"
    )
    return {
        "changed": True,
        "program": copy.deepcopy(program),
        "stream": copy.deepcopy(stream),
        "route_stream": copy.deepcopy(_state["streams"].get(program.get("route_stream_id"), {})),
        "event": event,
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "moqompare-registry/0.1"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        _log(f"{self.address_string()} {fmt % args}")

    def do_OPTIONS(self):
        self.send_response(204)
        self._set_common_headers()
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        with _cv:
            _mark_stale_streams_unlocked()

            if path == "/health":
                self._text(200, "ok\n")
                return

            if path == "/api/status":
                self._json(200, _snapshot_unlocked())
                return

            if path == "/api/streams":
                self._json(
                    200,
                    {
                        "streams": _sorted_streams_unlocked(),
                        "count": len(_state["streams"]),
                    },
                )
                return

            if path.startswith("/api/streams/") and len(path.split("/")) == 4:
                stream_id = path.rsplit("/", 1)[-1]
                stream = _state["streams"].get(stream_id)
                if not stream:
                    self._json(404, {"error": "stream not found", "stream_id": stream_id})
                    return
                self._json(200, {"stream": copy.deepcopy(stream)})
                return

            if path == "/api/routes":
                self._json(200, {"routes": copy.deepcopy(_state["routes"])})
                return

            if path == "/api/events":
                snapshot = _snapshot_unlocked()
                self._sse(snapshot)
                return

        self._json(404, {"error": "not found"})

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        try:
            body = self._read_json()
        except ValueError as exc:
            self._json(400, {"error": str(exc)})
            return

        with _cv:
            _mark_stale_streams_unlocked()

            try:
                if path == "/api/streams/register":
                    stream = _merge_stream_registration_unlocked(body)
                    self._json(200, {"ok": True, "stream": stream})
                    return

                if path == "/api/streams/heartbeat":
                    event = _heartbeat_stream_unlocked(body)
                    self._json(200, {"ok": True, "event": event})
                    return

                if path == "/api/routes/program":
                    if not body and query.get("stream_id"):
                        body = {"stream_id": query["stream_id"][-1]}
                    result = _set_program_route_unlocked(body)
                    self._json(200, {"ok": True, **result})
                    return

                if path == "/api/routes/program/modifier":
                    result = _set_program_modifier_unlocked(body)
                    self._json(200, {"ok": True, **result})
                    return
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
                return
            except KeyError as exc:
                self._json(404, {"error": "stream not found", "stream_id": str(exc)})
                return

        self._json(404, {"error": "not found"})

    def _read_json(self) -> dict:
        raw_len = self.headers.get("Content-Length", "0").strip() or "0"
        try:
            content_len = int(raw_len)
        except ValueError as exc:
            raise ValueError("invalid Content-Length") from exc

        if content_len == 0:
            return {}
        payload = self.rfile.read(content_len)
        if not payload:
            return {}
        try:
            value = json.loads(payload.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("request body must be valid JSON") from exc
        if not isinstance(value, dict):
            raise ValueError("request body must be a JSON object")
        return value

    def _set_common_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache, no-store")

    def _json(self, status: int, data: dict):
        encoded = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self._set_common_headers()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _text(self, status: int, body: str):
        encoded = body.encode("utf-8")
        self.send_response(status)
        self._set_common_headers()
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _sse(self, snapshot: dict):
        self.send_response(200)
        self._set_common_headers()
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        sent_version = -1

        def _send(event_name: str, payload: dict):
            blob = json.dumps(payload)
            self.wfile.write(f"event: {event_name}\n".encode("utf-8"))
            self.wfile.write(f"data: {blob}\n\n".encode("utf-8"))
            self.wfile.flush()

        try:
            _send("snapshot", snapshot)
            sent_version = snapshot["version"]
            while True:
                with _cv:
                    _mark_stale_streams_unlocked()
                    if _state["version"] != sent_version:
                        snapshot = _snapshot_unlocked()
                    else:
                        _cv.wait(timeout=15)
                        snapshot = _snapshot_unlocked()
                if snapshot["version"] != sent_version:
                    _send("snapshot", snapshot)
                    sent_version = snapshot["version"]
                else:
                    _send("keepalive", {"timestamp": _now()})
        except (BrokenPipeError, ConnectionResetError):
            return


def main():
    _log(f"starting stream registry on :{PORT} (ttl={STREAM_TTL_SECS}s)")
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
