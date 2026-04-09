# moqompare

**HLS vs MoQ Live Playback Comparison Lab**

A local lab that plays the same live video stream over HLS and MoQ side by side, with controlled network impairments, so you can directly observe protocol-level differences in latency, rebuffering, and recovery.

---

## Current phase: Phase 1 — HLS baseline

**What works:**
- Live video source (FFmpeg testsrc2, 1280×720 @ 30 fps)
- Visible UTC timestamp overlay ("SRC HH:MM:SS UTC")
- Rolling fMP4 HLS manifest served over HTTP
- Browser HLS player (hls.js) with startup time, latency, and stall count
- MoQ path: placeholder (Phase 2)

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                       Shared Upstream                            │
│                                                                  │
│   source (FFmpeg testsrc2 + timestamp overlay)                   │
│       │  MPEG-TS via named pipe (/media/source.pipe)             │
│   packager (fMP4 HLS @ /media/hls/)                              │
│       │                    │                                     │
│       ▼                    ▼                                     │
│   /media/hls/       /media/fragments/ (Phase 2)                  │
└──────────┬─────────────────┬────────────────────────────────────┘
           │                 │
    ┌──────▼──────┐   ┌──────▼──────────┐
    │   origin    │   │   publisher     │
    │  (nginx,    │   │  (placeholder)  │
    │   :8080)    │   └─────────────────┘
    └──────┬──────┘
           │
    ┌──────▼──────────────────────────────┐
    │   web (:3000)                        │
    │   /hls/ → proxied to origin          │
    │   HLS player + metrics + UI          │
    └──────────────────────────────────────┘
```

| Service | Role | Port |
|---------|------|------|
| `source` | FFmpeg: testsrc2 + timestamp → named pipe | — |
| `packager` | FFmpeg: MPEG-TS pipe → fMP4 HLS segments | — |
| `origin` | nginx: serves HLS over HTTP | 8080 |
| `publisher` | placeholder | — |
| `relay` | placeholder | 4443 |
| `web` | nginx: UI + HLS proxy | **3000** |
| `metrics` | placeholder | 9090 |

---

## Prerequisites

- Docker Engine 24+
- Docker Compose v2 plugin (`docker compose` not `docker-compose`)
- Internet access during `make setup` (pulls images, downloads hls.js)

---

## Quick start

```sh
# 1. Clone and enter the repo
git clone <repo-url> moqompare
cd moqompare

# 2. Bootstrap: copy .env, pull base images, build custom images
make setup

# 3. Start all services
make up

# 4. Open the comparison UI
open http://localhost:3000
# (or visit http://localhost:3000 in any browser)

# 5. Watch logs
make logs

# 6. Stop everything
make down
```

**Expected startup sequence (first run: ~30–60 s):**

1. `source` builds FFmpeg image → starts → creates FIFO → healthcheck passes (~10 s)
2. `packager` starts → reads FIFO → writes first segments → healthcheck passes (~15–20 s)
3. `origin` starts → serves HLS immediately
4. `web` builds (downloads hls.js) → starts → proxies `/hls/` to origin
5. Browser opens → hls.js connects → video plays within ~5–10 s

---

## Verification steps

### 1. Check all services are running

```sh
make ps
```

All 7 services should show `healthy` or `running` (publisher/relay/metrics show `running`).

### 2. Verify HLS manifest is updating

```sh
curl http://localhost:8080/hls/stream.m3u8
```

Expected: a valid M3U8 playlist with `#EXT-X-MAP` (fMP4 init) and several `.m4s` segment entries.

Run it twice, 3 seconds apart — segment entries should change (rolling manifest).

### 3. Verify segments are downloadable

```sh
curl -o /dev/null -w "%{http_code} %{size_download} bytes\n" \
  http://localhost:8080/hls/init.mp4
```

Expected: `200 <some size> bytes`

### 4. Verify browser playback

Open `http://localhost:3000`. Within ~10 s you should see:
- Live video playing with the `SRC HH:MM:SS UTC` timestamp visible
- Startup time shown in milliseconds
- Latency estimate updating (typically 6–12 s for HLS with 2 s segments)
- Stall counter stays at 0 under normal conditions

### 5. Acceptance test (3-minute stability)

Leave the browser tab open and observe:
- Timestamp advances in real time (no freezes)
- Stall counter stays at 0
- Latency stays roughly constant

---

## Make targets

| Target | Description |
|--------|-------------|
| `make setup` | Copy `.env.example` → `.env`, pull + build images |
| `make up` | Start all services (detached) |
| `make down` | Stop all services |
| `make logs` | Stream logs from all services |
| `make ps` | Show container status |
| `make clean` | Stop, remove containers + volumes, prune images |

---

## Impairment profiles (Phase 3)

Applied via `scripts/impair.sh <profile>`:

| Profile | Effect |
|---------|--------|
| `baseline` | No impairment |
| `jitter` | 30 ms delay ± 20 ms, 1% packet loss |
| `squeeze` | 500 kbit/s rate cap |
| `outage` | 100% loss for 5 s, then clear |

---

## Environment variables

Edit `.env` (copied from `.env.example`) to tune:

| Variable | Default | Description |
|----------|---------|-------------|
| `SOURCE_FPS` | `30` | Frame rate |
| `SOURCE_RESOLUTION` | `1280x720` | Video resolution |
| `SOURCE_BITRATE` | `1500k` | x264 target bitrate |
| `HLS_SEGMENT_DURATION` | `2` | Seconds per segment |
| `HLS_LIST_SIZE` | `5` | Segments kept in manifest |
| `ORIGIN_PORT` | `8080` | Host port for HLS origin |
| `WEB_PORT` | `3000` | Host port for browser UI |

---

## Phase progression

| Phase | Status | Goal |
|-------|--------|------|
| **0** | ✅ | Repo skeleton, Docker Compose, placeholder containers |
| **1** | ✅ | Live HLS stream in the browser with metrics |
| **2** | planned | Same stream via MoQ alongside HLS |
| **3** | planned | Impairment injection and event timeline |
| **4** | planned | Full metrics and observability |

See [`docs/phases.md`](docs/phases.md) for detailed acceptance criteria.  
See [`docs/architecture.md`](docs/architecture.md) for design rationale.

---

## Repository layout

```
infra/       nginx configs, future tc impairment scripts
packager/    HLS packager (FFmpeg fMP4 HLS output)
publisher/   MoQ fragment publisher (Phase 2)
relay/       MoQ relay (Phase 2)
source/      Live source generator (FFmpeg testsrc2 + drawtext)
web/         Browser UI: hls.js player, metrics, impairment controls
metrics/     Metrics collector (Phase 4)
scripts/     setup, run, demo, impair scripts
docs/        Architecture notes and phase plan
```

---

## Troubleshooting

**`source` container stuck in starting:**  
The source creates a named FIFO and FFmpeg blocks until the packager opens it. This is normal — the packager starts after source is healthy.

**No video in browser after 30 s:**  
```sh
# Check packager logs
docker compose logs packager

# Check if manifest exists
docker compose exec origin ls /usr/share/nginx/html/hls/
```

**`make setup` fails on image pull:**  
Check internet connectivity. The `web` image build downloads hls.js from jsDelivr CDN.

**Latency > 20 s:**  
This is unusual. Check `docker compose logs packager` for segment write errors. Restart with `make down && make up`.

---

## License

Apache 2.0 — see [`LICENSE`](LICENSE).
