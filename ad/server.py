#!/usr/bin/env python3
"""
ad/server.py — MoQ Ad Server

Responsibilities:
  1. Creative watcher   — polls /media/ads/creative/ for .mp4 drops;
                          transcodes each to fMP4 HLS on arrival.
  2. Live playlist gen  — serves a rolling live-like HLS playlist so moq-cli
                          publishes the ad at real-time pace (not all-at-once).
  3. VAST XML server    — serves VAST 3.0 XML referencing the prepared creative.
  4. Ad orchestrator    — polls the HLS cue state; on detection fetches own
                          VAST, spawns moq-cli to publish stream_ad during a
                          lead-in window, then flips from armed -> playing
                          when the scheduled cue point is reached.
  5. HTTP API           — status, creatives list, tracking beacons.

Endpoints:
  GET  /health                        — 200 "ok"
  GET  /creatives                     — JSON list of ready creatives
  GET  /vast?creative=<name>          — VAST 3.0 XML
  GET  /hls/<name>/<file>             — serve transcoded ad HLS files
  GET  /hls/<name>/live.m3u8         — live-like rolling playlist (for moq-cli)
  GET  /hls/<name>/live_master.m3u8  — live master pointing at live.m3u8
  GET  /status                        — ad break state (idle|armed|playing)
  POST /trigger?creative=<name>       — manually trigger ad break (for testing)
  GET  /track/impression              — log impression beacon
  GET  /track/start                   — log start beacon
  GET  /track/complete                — log complete beacon
"""

import json
import os
import subprocess
import threading
import time
import urllib.request
import urllib.error
import urllib.parse
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# ── Configuration ─────────────────────────────────────────────────────────────

CREATIVE_DIR       = Path(os.environ.get("CREATIVE_DIR",       "/media/ads/creative"))
HLS_DIR            = Path(os.environ.get("HLS_DIR",            "/media/ads/hls"))
MANIFEST_PROXY_URL = os.environ.get("MANIFEST_PROXY_URL",      "http://manifest-proxy:8091")
RELAY_URL          = os.environ.get("RELAY_URL",               "http://relay:4443")
CONTENT_RESOLUTION = os.environ.get("CONTENT_RESOLUTION",      "1280x720")
CONTENT_BITRATE    = os.environ.get("CONTENT_BITRATE",         "4000k")
SEGMENT_DURATION   = int(os.environ.get("SEGMENT_DURATION",    "2"))
SOURCE_FPS         = int(os.environ.get("SOURCE_FPS",          "30"))
PORT               = int(os.environ.get("AD_PORT",             "8092"))
LOG_LEVEL          = os.environ.get("LOG_LEVEL",               "info")
AD_CUE_LEAD_SECS   = float(os.environ.get("AD_CUE_LEAD_SECS",  "10"))

GOP_SIZE = SEGMENT_DURATION * SOURCE_FPS

# ── Shared state ───────────────────────────────────────────────────────────────

_lock = threading.Lock()

# {name: {name, duration_s, ready, hls_dir, segments: [(filename, dur), ...]}}
_creatives: dict[str, dict] = {}

# Ad break state
_ad_state = {
    "state":         "idle",   # idle | armed | playing
    "creative":      None,
    "duration_s":    0,
    "lead_seconds":  AD_CUE_LEAD_SECS,
    "trace_id":      "",
    "switch_at":     None,     # wall-clock timestamp when playback should flip
    "start_time":    None,     # monotonic timestamp when playback actually starts
}

# moq-cli subprocess handle
_moq_proc: subprocess.Popen | None = None


def _log(msg: str):
    print(f"[ad-server] {msg}", flush=True)


def _trace_tag(trace_id: str | None) -> str:
    return f" trace_id={trace_id}" if trace_id else ""


# ── Live playlist state ────────────────────────────────────────────────────────
# Per-creative sequential playlist state. Keyed by creative name.
#
# The initial live window is sized per creative so the player has enough
# runway to survive moq-cli's HLS poll cadence. Once the cue point is reached,
# the ticker still advances one segment per tick, and moq-cli's subsequent
# polls pick up exactly 1 new segment with overlap over the already-published
# trailing entries — no PTS discontinuity.
#
# No looping — once the last segment is reached the window holds there.
#
# {name: {segments, idx, media_seq, seg_duration, window_size, stop_event}}

_live: dict[str, dict] = {}
_live_lock = threading.Lock()

MIN_LIVE_WINDOW = 3


def _recommended_live_window(segments: list[tuple[str, float]]) -> tuple[int, int, float, float]:
    """Choose an initial window large enough to cover publish cadence deficit."""
    if not segments:
        return MIN_LIVE_WINDOW, 1, 0.0, 0.0

    durations = [duration for _, duration in segments]
    target_dur = int(max(durations)) + 1
    total_duration = sum(durations)
    prefix_duration = 0.0
    suffix_duration = total_duration

    for idx, duration in enumerate(durations, start=1):
        prefix_duration += duration
        suffix_duration -= duration
        remaining = len(durations) - idx
        remaining_deficit = max(0.0, remaining * target_dur - suffix_duration)
        if prefix_duration >= remaining_deficit:
            window_size = max(MIN_LIVE_WINDOW, idx)
            return min(len(segments), window_size), target_dur, prefix_duration, remaining_deficit

    return len(segments), target_dur, total_duration, 0.0


def _parse_static_playlist(out_dir: Path) -> list[tuple[str, float]]:
    """Parse stream.m3u8; return [(seg_filename, duration_s), ...]."""
    playlist = out_dir / "stream.m3u8"
    if not playlist.exists():
        return []
    segments: list[tuple[str, float]] = []
    lines = playlist.read_text().splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("#EXTINF:"):
            try:
                dur = float(line[8:].split(",")[0])
            except ValueError:
                dur = float(SEGMENT_DURATION)
            # next non-empty, non-comment line is the segment filename
            i += 1
            while i < len(lines) and (not lines[i].strip() or lines[i].startswith("#")):
                i += 1
            if i < len(lines) and lines[i].strip():
                seg = lines[i].strip()
                # strip any path prefix — keep basename only
                seg = seg.rsplit("/", 1)[-1]
                segments.append((seg, dur))
        i += 1
    return segments


def _start_live_playlist(
    name: str,
    segments: list[tuple[str, float]],
    start_delay: float = 0.0,
):
    """Start the ticker that exposes one new segment per seg_duration seconds.

    Window size is 2: on first connect moq-cli sees two segments, which gives
    the downstream player enough runway to cover the HLS poll gap when the
    segment duration (~2.4 s) is shorter than EXT-X-TARGETDURATION (3 s).
    If start_delay > 0, the initial window is exposed immediately so stream_ad
    can be established ahead of time, but the ticker does not start advancing
    until the cue point. After the cue point, the playlist slides forward one
    segment per tick, so each subsequent poll exposes exactly one new segment
    with one overlapping tail segment. Segments play through 0→n-1 in order;
    after the last segment the window holds on the tail until the ad break ends
    and moq-cli is torn down.
    """
    if not segments:
        return
    seg_dur = segments[0][1] if segments else float(SEGMENT_DURATION)
    stop_ev = threading.Event()
    start_at = time.monotonic() + max(0.0, start_delay)
    window_size, target_dur, prebuffer_s, needed_s = _recommended_live_window(segments)

    with _live_lock:
        _live[name] = {
            "segments":     segments,
            "idx":          0,
            "media_seq":    1000,
            "seg_duration": seg_dur,
            "window_size":  window_size,
            "start_at":     start_at,
            "stop_event":   stop_ev,
        }

    def _tick():
        n = len(segments)
        next_advance_at = start_at + seg_dur
        # Advance one segment per seg_duration once the cue point is reached.
        # Stop advancing once we reach the last segment so moq-cli drains
        # without a loop.
        while not stop_ev.is_set():
            now = time.monotonic()
            if now < next_advance_at:
                stop_ev.wait(timeout=min(0.25, next_advance_at - now))
                continue
            with _live_lock:
                st = _live.get(name)
                if st is None:
                    return
                if st["idx"] < n - 1:
                    st["idx"]       += 1
                    st["media_seq"] += 1
                    next_advance_at += seg_dur
                else:
                    next_advance_at = time.monotonic() + 0.25

    threading.Thread(target=_tick, daemon=True).start()
    _log(
        f"live playlist ticker started for {name} "
        f"({len(segments)} segs, {seg_dur:.2f}s each, delay={start_delay:.1f}s, "
        f"window={window_size}, target_dur={target_dur}s, "
        f"prebuffer={prebuffer_s:.1f}s, required={needed_s:.1f}s)"
    )


def _stop_live_playlist(name: str):
    with _live_lock:
        st = _live.pop(name, None)
    if st:
        st["stop_event"].set()
        _log(f"live playlist ticker stopped for {name}")


def _build_live_m3u8(name: str) -> str | None:
    """Return the current live HLS window for the ad publisher."""
    with _live_lock:
        st = _live.get(name)
        if st is None:
            return None
        segments  = st["segments"]
        idx       = st["idx"]
        media_seq = st["media_seq"]
        window_size = st["window_size"]

    if not segments:
        return None

    window_end = min(len(segments), idx + window_size)
    window = segments[idx:window_end]
    if not window:
        return None

    target_dur = int(max(duration for _, duration in window)) + 1

    lines = [
        "#EXTM3U",
        "#EXT-X-VERSION:6",
        f"#EXT-X-TARGETDURATION:{target_dur}",
        f"#EXT-X-MEDIA-SEQUENCE:{media_seq}",
        '#EXT-X-MAP:URI="init.mp4"',
    ]

    for seg_name, seg_actual_dur in window:
        lines.extend([
            f"#EXTINF:{seg_actual_dur:.6f},",
            seg_name,
        ])

    return "\n".join(lines) + "\n"


# ── FFmpeg helpers ─────────────────────────────────────────────────────────────

def _probe_duration(path: Path) -> float | None:
    """Return video duration in seconds using ffprobe."""
    try:
        r = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True, text=True, timeout=15,
        )
        if r.returncode == 0:
            return float(r.stdout.strip())
    except Exception as e:
        _log(f"ffprobe error for {path}: {e}")
    return None


def _bitrate_to_int(bitrate: str) -> int:
    """Convert '4000k' → 4000000."""
    b = bitrate.lower().strip()
    if b.endswith("k"):
        return int(b[:-1]) * 1000
    if b.endswith("m"):
        return int(b[:-1]) * 1_000_000
    return int(b)


def _transcode(name: str, src: Path):
    """Transcode a dropped MP4 to fMP4 HLS segments."""
    out_dir   = HLS_DIR / name
    out_dir.mkdir(parents=True, exist_ok=True)
    playlist  = out_dir / "stream.m3u8"
    seg_tmpl  = str(out_dir / "seg_%05d.m4s")

    _log(f"transcoding {src.name} → {out_dir}")

    cmd = [
        "ffmpeg", "-y",
        "-i", str(src),
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-tune", "zerolatency",
        "-vf", f"scale={CONTENT_RESOLUTION}",
        "-b:v", CONTENT_BITRATE,
        "-g", str(GOP_SIZE),
        "-keyint_min", str(GOP_SIZE),
        "-sc_threshold", "0",
        "-hls_time", str(SEGMENT_DURATION),
        "-hls_list_size", "0",
        "-hls_playlist_type", "vod",
        "-hls_segment_type", "fmp4",
        "-hls_fmp4_init_filename", "init.mp4",
        "-hls_flags", "independent_segments",
        "-hls_segment_filename", seg_tmpl,
        str(playlist),
    ]

    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            _log(f"ffmpeg failed for {name}: {r.stderr[-500:]}")
            return
    except Exception as e:
        _log(f"ffmpeg exception for {name}: {e}")
        return

    duration = _probe_duration(src) or 30.0
    segments = _parse_static_playlist(out_dir)
    playlist_duration = round(sum(seg_dur for _, seg_dur in segments), 3)

    # Static master (for direct browser playback via HLS if needed)
    (out_dir / "master.m3u8").write_text(
        "#EXTM3U\n"
        "#EXT-X-VERSION:6\n"
        f"#EXT-X-STREAM-INF:BANDWIDTH={_bitrate_to_int(CONTENT_BITRATE)},"
        f"RESOLUTION={CONTENT_RESOLUTION}\n"
        "stream.m3u8\n"
    )

    # Live master → used by moq-cli; references the rolling live.m3u8 endpoint.
    # CODECS and EXT-X-INDEPENDENT-SEGMENTS are required by moq-cli's HLS parser.
    (out_dir / "live_master.m3u8").write_text(
        "#EXTM3U\n"
        "#EXT-X-VERSION:6\n"
        "#EXT-X-INDEPENDENT-SEGMENTS\n"
        "\n"
        f"#EXT-X-STREAM-INF:BANDWIDTH={_bitrate_to_int(CONTENT_BITRATE)},"
        f"RESOLUTION={CONTENT_RESOLUTION},"
        'CODECS="avc1.42c028",NAME="ad"\n'
        "live.m3u8\n"
    )

    with _lock:
        _creatives[name] = {
            "name":       name,
            "duration_s": round(duration, 3),
            "ready":      True,
            "hls_dir":    str(out_dir),
            "segments":   segments,
        }

    _log(
        f"creative ready: {name} ({duration:.1f}s, {len(segments)} segments, "
        f"playlist_duration={playlist_duration:.1f}s)"
    )
    if segments and abs(playlist_duration - duration) > max(1.0, SEGMENT_DURATION):
        _log(
            f"WARNING: parsed playlist duration mismatch for {name}: "
            f"playlist={playlist_duration:.1f}s probe={duration:.1f}s"
        )


# ── Creative watcher thread ────────────────────────────────────────────────────

def _watch_creatives():
    CREATIVE_DIR.mkdir(parents=True, exist_ok=True)
    HLS_DIR.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    _log(f"watching {CREATIVE_DIR} for .mp4 drops")
    while True:
        try:
            for entry in os.scandir(CREATIVE_DIR):
                if not entry.name.lower().endswith(".mp4"):
                    continue
                stem = Path(entry.name).stem
                if stem in seen:
                    continue
                seen.add(stem)
                _log(f"new creative detected: {entry.name}")
                threading.Thread(
                    target=_transcode,
                    args=(stem, Path(entry.path)),
                    daemon=True,
                ).start()
        except Exception as e:
            _log(f"watcher error: {e}")
        time.sleep(2)


# ── VAST builder ───────────────────────────────────────────────────────────────

def _seconds_to_hhmmss(secs: float) -> str:
    s = int(secs)
    h, rem = divmod(s, 3600)
    m, sc  = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{sc:02d}"


def _build_vast(name: str, duration_s: float, base_url: str) -> str:
    dur_str   = _seconds_to_hhmmss(duration_s)
    media_url = f"{base_url}/hls/{urllib.parse.quote(name)}/stream.m3u8"
    imp_url   = f"{base_url}/track/impression?creative={urllib.parse.quote(name)}"
    start_url = f"{base_url}/track/start?creative={urllib.parse.quote(name)}"
    end_url   = f"{base_url}/track/complete?creative={urllib.parse.quote(name)}"

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<VAST version="3.0">
  <Ad id="1"><InLine>
    <AdSystem>moqompare-ad-server</AdSystem>
    <AdTitle>{name}</AdTitle>
    <Impression><![CDATA[{imp_url}]]></Impression>
    <Creatives>
      <Creative>
        <Linear>
          <Duration>{dur_str}</Duration>
          <TrackingEvents>
            <Tracking event="start"><![CDATA[{start_url}]]></Tracking>
            <Tracking event="complete"><![CDATA[{end_url}]]></Tracking>
          </TrackingEvents>
          <MediaFiles>
            <MediaFile type="application/x-mpegURL" delivery="streaming"
                       width="{CONTENT_RESOLUTION.split('x')[0]}"
                       height="{CONTENT_RESOLUTION.split('x')[1]}">
              <![CDATA[{media_url}]]>
            </MediaFile>
          </MediaFiles>
        </Linear>
      </Creative>
    </Creatives>
  </InLine></Ad>
</VAST>
"""


# ── Ad orchestrator ────────────────────────────────────────────────────────────

def _parse_vast_duration(vast_xml: str) -> float | None:
    """Parse HH:MM:SS duration from VAST XML."""
    try:
        root = ET.fromstring(vast_xml)
        dur_el = root.find(".//{*}Duration")
        if dur_el is None or not dur_el.text:
            return None
        parts = dur_el.text.strip().split(":")
        if len(parts) == 3:
            h, m, s = parts
            return int(h) * 3600 + int(m) * 60 + float(s)
    except Exception as e:
        _log(f"VAST parse error: {e}")
    return None


def _start_ad_publisher(name: str, segments: list, lead_seconds: float = 0.0):
    """Start live playlist ticker + spawn moq-cli to publish stream_ad."""
    global _moq_proc

    # Start the live rolling playlist FIRST so moq-cli can establish stream_ad
    # immediately. When lead_seconds > 0 the first playlist window is exposed
    # right away, but timeline advancement is held until the cue point.
    _start_live_playlist(name, segments, start_delay=lead_seconds)

    playlist_url = f"http://localhost:{PORT}/hls/{urllib.parse.quote(name)}/live_master.m3u8"
    cmd = [
        "moq-cli", "publish",
        "--url", RELAY_URL,
        "--name", "stream_ad",
        "hls",
        "--playlist", playlist_url,
    ]
    _log(f"starting stream_ad publisher: {' '.join(cmd)}")
    try:
        _moq_proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        # Log moq-cli output in background
        threading.Thread(
            target=_drain_moq_output,
            args=(_moq_proc,),
            daemon=True,
        ).start()
    except Exception as e:
        _log(f"failed to start moq-cli: {e}")
        _moq_proc = None
        _stop_live_playlist(name)


def _drain_moq_output(proc: subprocess.Popen):
    """Log moq-cli stdout/stderr for debugging."""
    try:
        for line in proc.stdout:
            _log(f"moq-cli: {line.decode(errors='replace').rstrip()}")
    except Exception:
        pass


def _stop_ad_publisher():
    global _moq_proc

    # Stop live playlist ticker first
    with _lock:
        creative_name = _ad_state.get("creative")
    if creative_name:
        _stop_live_playlist(creative_name)

    if _moq_proc is not None:
        _log("stopping stream_ad publisher")
        try:
            _moq_proc.terminate()
            _moq_proc.wait(timeout=5)
        except Exception as e:
            _log(f"moq-cli stop error: {e}")
            try:
                _moq_proc.kill()
            except Exception:
                pass
        _moq_proc = None


def _call_manifest_proxy(path: str):
    try:
        req = urllib.request.Request(
            f"{MANIFEST_PROXY_URL}{path}",
            method="POST",
            headers={"Content-Length": "0"},
        )
        with urllib.request.urlopen(req, timeout=5):
            pass
    except Exception as e:
        _log(f"manifest-proxy {path} error: {e}")


def _fetch_cue_status() -> dict[str, object]:
    """Return cue state from manifest-proxy /status."""
    try:
        url = f"{MANIFEST_PROXY_URL}/status"
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read())
            return {
                "cue_active": bool(data.get("cue_active", False)),
                "cue_duration": int(data.get("cue_duration", 30)),
                "cue_injected": bool(data.get("cue_injected", False)),
                "cue_trace_id": str(data.get("cue_trace_id", "") or ""),
                "cue_injected_path": str(data.get("cue_injected_path", "") or ""),
            }
    except Exception:
        return {
            "cue_active": False,
            "cue_duration": 30,
            "cue_injected": False,
            "cue_trace_id": "",
            "cue_injected_path": "",
        }


def _trigger_ad_break(
    creative_name: str | None = None,
    lead_seconds: float = AD_CUE_LEAD_SECS,
    duration_override: float | None = None,
    trace_id: str | None = None,
    source: str = "manual",
):
    """Arm an ad break: resolve creative, pre-publish, and schedule playback."""
    global _ad_state

    requested = max(0.5, float(duration_override)) if duration_override is not None else None

    with _lock:
        if _ad_state["state"] != "idle":
            _log(
                "ad break already in progress, ignoring trigger"
                f"{_trace_tag(trace_id)} source={source}"
            )
            return
        if creative_name:
            creative = _creatives.get(creative_name)
        else:
            ready = [c for c in _creatives.values() if c["ready"]]
            if requested is not None:
                long_enough = sorted(
                    (c for c in ready if c["duration_s"] >= requested),
                    key=lambda c: c["duration_s"],
                )
                creative = long_enough[0] if long_enough else (
                    max(ready, key=lambda c: c["duration_s"]) if ready else None
                )
            else:
                creative = ready[0] if ready else None
        if not creative:
            _log(f"no ready creative available for ad break{_trace_tag(trace_id)} source={source}")
            return
        _ad_state["state"]        = "armed"
        _ad_state["creative"]     = creative["name"]
        _ad_state["lead_seconds"] = lead_seconds
        _ad_state["trace_id"]     = trace_id or ""

    name       = creative["name"]
    duration_s = creative["duration_s"]
    segments   = creative.get("segments", [])

    # Fetch VAST from self to confirm duration
    try:
        vast_url = f"http://localhost:{PORT}/vast?creative={urllib.parse.quote(name)}"
        with urllib.request.urlopen(vast_url, timeout=5) as resp:
            vast_xml = resp.read().decode()
        parsed_dur = _parse_vast_duration(vast_xml)
        if parsed_dur is not None:
            duration_s = parsed_dur
    except Exception as e:
        _log(f"VAST self-fetch error: {e}")

    if requested is not None:
        if requested > duration_s:
            _log(
                f"requested ad duration {requested:.1f}s exceeds creative length "
                f"{duration_s:.1f}s; clamping"
            )
        duration_s = min(duration_s, requested)

    _log(
        f"arming ad break: creative={name}, duration={duration_s:.1f}s, "
        f"lead={lead_seconds:.1f}s, source={source}{_trace_tag(trace_id)}"
    )

    _start_ad_publisher(name, segments, lead_seconds=lead_seconds)

    if _moq_proc is None:
        with _lock:
            _ad_state = {
                "state":         "idle",
                "creative":      None,
                "duration_s":    0,
                "lead_seconds":  AD_CUE_LEAD_SECS,
                "trace_id":      "",
                "switch_at":     None,
                "start_time":    None,
            }
        _log(f"failed to arm ad break: stream_ad publisher did not start{_trace_tag(trace_id)}")
        return

    with _lock:
        _ad_state["duration_s"] = duration_s
        _ad_state["switch_at"]  = time.time() + max(0.0, lead_seconds)
        _ad_state["start_time"] = None
    _log(
        "ad armed"
        f"{_trace_tag(trace_id)} switch_at={_ad_state['switch_at']:.3f}"
        f" lead={lead_seconds:.1f}s"
    )


def _poll_manifest_for_cue():
    """Background thread: poll cue state and drive armed/playback transitions."""
    _log(f"manifest cue poller started → {MANIFEST_PROXY_URL}/status")
    cue_seen = False
    last_cue_sig = ""

    while True:
        time.sleep(0.5)

        with _lock:
            current_state = _ad_state["state"]
            creative      = _ad_state["creative"]
            switch_at     = _ad_state["switch_at"]
            start_time    = _ad_state["start_time"]
            duration_s    = _ad_state["duration_s"]
            trace_id      = _ad_state["trace_id"]

        if current_state == "armed" and switch_at is not None:
            if time.time() >= switch_at:
                _log(
                    "cue point reached — switching ad break to playing"
                    f"{_trace_tag(trace_id)} creative={creative}"
                )
                with _lock:
                    _ad_state["state"]      = "playing"
                    _ad_state["start_time"] = time.monotonic()

                if creative:
                    try:
                        imp_url = (
                            f"http://localhost:{PORT}/track/impression"
                            f"?creative={urllib.parse.quote(creative)}"
                        )
                        urllib.request.urlopen(imp_url, timeout=3)
                    except Exception:
                        pass
            continue

        if current_state == "playing" and start_time is not None:
            elapsed = time.monotonic() - start_time
            if elapsed >= duration_s:
                _log(
                    f"ad break complete ({elapsed:.1f}s elapsed)"
                    f"{_trace_tag(trace_id)} creative={creative}"
                )
                _stop_ad_publisher()
                _call_manifest_proxy("/cue_in")
                with _lock:
                    _ad_state["state"]        = "idle"
                    _ad_state["creative"]     = None
                    _ad_state["duration_s"]   = 0
                    _ad_state["lead_seconds"] = AD_CUE_LEAD_SECS
                    _ad_state["trace_id"]     = ""
                    _ad_state["switch_at"]    = None
                    _ad_state["start_time"]   = None
                cue_seen = False
                last_cue_sig = ""
            continue

        if current_state != "idle":
            continue

        cue = _fetch_cue_status()
        cue_sig = (
            f"{int(bool(cue['cue_active']))}|{cue['cue_duration']}|"
            f"{int(bool(cue['cue_injected']))}|{cue['cue_trace_id']}|{cue['cue_injected_path']}"
        )
        if cue_sig != last_cue_sig:
            last_cue_sig = cue_sig
            _log(
                "manifest cue status "
                f"active={cue['cue_active']} injected={cue['cue_injected']} "
                f"duration={cue['cue_duration']} path={cue['cue_injected_path'] or '-'}"
                f"{_trace_tag(str(cue['cue_trace_id'] or ''))}"
            )
        has_cue = bool(cue["cue_active"])
        cue_duration = int(cue["cue_duration"])
        cue_trace_id = str(cue["cue_trace_id"] or "")
        if has_cue and not cue_seen:
            cue_seen = True
            _log(
                "cue_active=true detected via manifest-proxy /status — "
                f"triggering ad break ({cue_duration}s requested)"
                f"{_trace_tag(cue_trace_id)}"
            )
            threading.Thread(
                target=_trigger_ad_break,
                kwargs={
                    "duration_override": cue_duration,
                    "trace_id": cue_trace_id,
                    "source": "cue-poller",
                },
                daemon=True,
            ).start()
        elif not has_cue:
            cue_seen = False


# ── HTTP request handler ───────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        if LOG_LEVEL == "debug":
            print(f"[ad-server] {self.address_string()} {fmt % args}", flush=True)

    def _send_json(self, code: int, data):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, code: int, text: str, content_type: str = "text/plain"):
        body = text.encode()
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path):
        if not path.exists():
            self._send_json(404, {"error": "not found"})
            return
        data = path.read_bytes()
        mime = {
            ".m3u8": "application/vnd.apple.mpegurl",
            ".mp4":  "video/mp4",
            ".m4s":  "video/iso.segment",
        }.get(path.suffix.lower(), "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        self.wfile.write(data)

    def _parse_qs(self) -> dict[str, str]:
        return dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))

    def _path_without_qs(self) -> str:
        return urllib.parse.urlparse(self.path).path

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self):
        path = self._path_without_qs()
        qs   = self._parse_qs()

        if path == "/health":
            self._send_text(200, "ok")

        elif path == "/creatives":
            with _lock:
                lst = [{k: v for k, v in c.items() if k != "segments"}
                       for c in _creatives.values()]
            self._send_json(200, lst)

        elif path == "/vast":
            name = qs.get("creative")
            if not name:
                self._send_json(400, {"error": "creative param required"})
                return
            with _lock:
                creative = _creatives.get(name)
            if not creative or not creative["ready"]:
                self._send_json(404, {"error": "creative not ready"})
                return
            host = self.headers.get("Host", f"localhost:{PORT}")
            vast = _build_vast(name, creative["duration_s"], f"http://{host}")
            self._send_text(200, vast, "application/xml")

        elif path.startswith("/hls/"):
            rel   = path[5:]   # strip leading /hls/
            parts = rel.strip("/").split("/", 1)
            if len(parts) != 2:
                self._send_json(404, {"error": "not found"})
                return
            cname = urllib.parse.unquote(parts[0])
            fname = urllib.parse.unquote(parts[1])

            # Dynamic live playlist — generated in memory, not on disk
            if fname == "live.m3u8":
                content = _build_live_m3u8(cname)
                if content is None:
                    self._send_json(404, {"error": "live playlist not active"})
                else:
                    self._send_text(200, content, "application/vnd.apple.mpegurl")
                return

            self._send_file(HLS_DIR / cname / fname)

        elif path == "/status":
            with _lock:
                state = dict(_ad_state)
            if state["state"] == "playing" and state["start_time"] is not None:
                state["elapsed_s"] = round(time.monotonic() - state["start_time"], 1)
            else:
                state["elapsed_s"] = 0
            if state["state"] == "armed" and state["switch_at"] is not None:
                state["switch_in_s"] = max(0.0, round(state["switch_at"] - time.time(), 1))
            else:
                state["switch_in_s"] = 0
            state.pop("start_time", None)
            self._send_json(200, state)

        elif path.startswith("/track/"):
            event    = path.split("/")[-1]
            creative = qs.get("creative", "unknown")
            _log(f"VAST tracking: {event} creative={creative}")
            self._send_text(200, "ok")

        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        path = self._path_without_qs()
        qs   = self._parse_qs()

        if path == "/trigger":
            duration = qs.get("duration")
            trace_id = qs.get("trace_id")
            try:
                duration_override = float(duration) if duration else None
            except ValueError:
                self._send_json(400, {"error": "invalid duration"})
                return
            _log(
                "manual trigger requested"
                f" duration={duration_override if duration_override is not None else '-'}"
                f" creative={qs.get('creative') or '-'}"
                f"{_trace_tag(trace_id)}"
            )
            threading.Thread(
                target=_trigger_ad_break,
                kwargs={
                    "creative_name": qs.get("creative"),
                    "duration_override": duration_override,
                    "trace_id": trace_id,
                    "source": "ui-trigger",
                },
                daemon=True,
            ).start()
            self._send_json(200, {"ok": True, "trace_id": trace_id})
        else:
            self._send_json(404, {"error": "not found"})


# ── Main ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    _log(f"creative dir  : {CREATIVE_DIR}")
    _log(f"HLS output    : {HLS_DIR}")
    _log(f"manifest-proxy: {MANIFEST_PROXY_URL}")
    _log(f"relay         : {RELAY_URL}")
    _log(f"listening on  : :{PORT}")

    threading.Thread(target=_watch_creatives, daemon=True).start()
    threading.Thread(target=_poll_manifest_for_cue, daemon=True).start()

    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    server.serve_forever()
