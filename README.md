# moqompare

**HLS vs MoQ Live Playback Comparison Lab**

A local lab that plays the same live video stream over HLS and MoQ side by side, with controlled network impairments, so you can directly observe protocol-level differences in latency, rebuffering, and recovery.

---

## Current phase: Phase 4 — Metrics & Observability

**What works:**
- Live video source (FFmpeg testsrc2 + UTC timestamp overlay, 1280×720 @ 30 fps)
- Rolling fMP4 HLS manifest served over HTTP; hls.js player with startup, latency, stall, bitrate, and resolution metrics
- **MoQ path**: moq-cli (built from source at moq-relay-v0.10.17) ingests HLS → moq-relay (QUIC/WebTransport) → hang-watch browser player
- Both HLS and MoQ play the same live source with visible timestamp side by side
- Per-player metrics: latency, startup time, stall count, stall duration, bitrate, resolution
- **Impairment controller**: privileged sidecar applies `tc netem` rules to origin and relay network namespaces via `docker inspect` + `nsenter`
- Impairment profile buttons in the UI (Baseline, Jitter+Loss, Bandwidth Squeeze, Burst Outage) wired to HTTP API
- Event timeline showing impairment transitions and player events
- **Metrics collector**: browser reports metrics every 5 s; Prometheus endpoint at `:9090/metrics`
- JSON snapshot at `:9090/snapshot` (also proxied via `:3000/metrics/snapshot`)
- `scripts/demo.sh` cycles through all impairment profiles and prints a final metrics snapshot

**Known limitations:**
- MoQ playback has ~4–5 s latency due to the HLS ingest burst pattern (2 s segments arrive at once)
- `tc netem` with `nsenter` works on Docker Desktop for Mac; untested on rootless Docker on Linux
- Metrics are browser-pushed; relay-side metrics (subscriber count, queue depth) not yet collected
- First `make up` compiles moq-relay and moq-cli from Rust source — allow 5–10 min on first build

---

## Architecture

```
  source (FFmpeg testsrc2 + UTC timestamp overlay)
      │  MPEG-TS via named pipe (/media/source.pipe)
  packager (FFmpeg fMP4 HLS → /media/hls/)
      │
      ├─────────────────────────────────────────────┐
      │  HLS path                                   │  MoQ path
      ▼                                             ▼
  origin (nginx :8080)                    publisher (moq-cli)
      │  /hls/stream.m3u8                     │  polls master.m3u8
      │                                       ▼
      │                               relay (moq-relay :4443 QUIC+TCP)
      │                                       │  WebTransport
      ▼                                       │
  web (nginx :3000) ◄─────────────────────────┘
      │  /hls/ → origin
      │  /impair/ → impairment (:8090)
      │  /metrics/ → metrics (:9090)
      ▼
  Browser: HLS player (hls.js) │ MoQ player (hang-watch)
           impairment buttons  │ event timeline

  impairment (:8090)  — tc netem via nsenter, uses Docker socket
  metrics    (:9090)  — Prometheus endpoint, receives browser reports
```

| Service | Role | Port |
|---------|------|------|
| `source` | FFmpeg: testsrc2 + UTC timestamp → named pipe | — |
| `packager` | FFmpeg: MPEG-TS pipe → fMP4 HLS segments + master playlist | — |
| `origin` | nginx: serves `/hls/` over HTTP | 8080 |
| `publisher` | moq-cli (built from source): HLS ingest → QUIC publish | — |
| `relay` | moq-relay (built from source): QUIC relay + HTTP cert endpoint | **4443** |
| `web` | nginx: browser UI, proxies `/hls/`, `/impair/`, `/metrics/` | **3000** |
| `impairment` | Python3: `tc netem` HTTP API via nsenter | 8090 |
| `metrics` | Python3: Prometheus metrics collector (browser-push) | 9090 |

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

**Expected startup sequence:**

*First run — Rust compilation:* `relay` and `publisher` build from source (~5–10 min). Subsequent runs use the Docker layer cache and start in seconds.

1. `source` starts → creates FIFO → healthcheck passes (~10 s)
2. `packager` reads FIFO → writes first HLS segments → healthcheck passes (~20 s)
3. `origin` starts → serves `/hls/` immediately
4. `relay` starts → generates TLS cert for `localhost,relay` → healthcheck passes
5. `publisher` connects to relay → polls `master.m3u8` → starts ingesting HLS
6. `web` starts → proxies `/hls/`, `/impair/`, `/metrics/`
7. `impairment` + `metrics` start
8. Browser: HLS plays within ~5–10 s; MoQ plays within ~10–15 s

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

### 4. Verify HLS browser playback

Open `http://localhost:3000`. Within ~10 s you should see:
- HLS panel: live video with `SRC HH:MM:SS UTC` timestamp visible
- Startup time shown in milliseconds
- Latency estimate updating (typically 6–12 s for HLS with 2 s segments)
- Stall counter stays at 0 under normal conditions

### 5. Verify MoQ playback

Within ~15 s the MoQ panel should also show live video:

```sh
# Check publisher is ingesting and publishing
docker compose logs publisher --tail=20

# Check relay is receiving the broadcast
docker compose logs relay --tail=20
# Look for: negotiated version=moq-lite-03 and subscribe started track=0.hang
```

If the MoQ panel shows "Waiting for broadcast" after 30 s, reload the page once.

### 6. Acceptance test (3-minute stability)

Leave the browser tab open and observe:
- Timestamp advances in real time (no freezes)
- Stall counter stays at 0
- Latency stays roughly constant

### 7. Verify metrics collector

After both players have been running for at least 5 seconds, the browser begins pushing metrics:

```sh
# JSON snapshot
curl http://localhost:9090/snapshot

# Prometheus format
curl http://localhost:9090/metrics
```

Or via the web proxy:
```sh
curl http://localhost:3000/metrics/snapshot
```

Expected output includes `player_latency_seconds`, `player_stalls_total`, and `player_startup_ms` for both `hls` and `moq` protocols.

### 8. Full demo with impairment cycle

```sh
./scripts/demo.sh
```

This opens the browser, cycles through all impairment profiles, and prints a metrics snapshot at the end.

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
| `./scripts/demo.sh` | Full impairment demo cycle + metrics snapshot |

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
| **2** | ✅ | Same stream via MoQ alongside HLS |
| **3** | ✅ | Impairment injection and event timeline |
| **4** | ✅ | Full metrics and observability |

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
The source creates a named FIFO; FFmpeg blocks until the packager opens it. This is normal — the packager starts after source is healthy.

**No HLS video in browser after 30 s:**  
```sh
docker compose logs packager          # look for ffmpeg errors
docker compose exec origin ls /usr/share/nginx/html/hls/  # should list stream.m3u8
```

**MoQ panel shows "Waiting for broadcast" indefinitely:**  
```sh
docker compose logs publisher --tail=30   # should show HLS segments being published
docker compose logs relay --tail=30       # look for negotiated version=moq-lite-03
```
If the publisher logs show `catalog.json err=not found`, the publisher image is the wrong version — rebuild with `docker compose up -d --build publisher`.  
If the relay logs only show `moq-lite-01` connections, the relay image is stale — rebuild with `docker compose up -d --build relay`.

**Impairment buttons return "pid not found":**  
The impairment container uses the Docker socket to find container PIDs. Check:
```sh
docker compose logs impairment | head -10   # startup smoke-test shows pid OK or NOT FOUND
docker compose exec impairment docker inspect --format '{{.State.Pid}}' moqompare-origin
```
If `docker inspect` fails, the socket bind may need `DOCKER_HOST` set — check Docker Desktop settings.

**`make setup` fails on image pull:**  
Check internet connectivity. The `web` build downloads hls.js from jsDelivr CDN; `relay` and `publisher` builds clone from GitHub.

**First `make up` hangs for minutes:**  
Normal — Rust compiles `moq-relay` and `moq-cli` from source. Subsequent starts use the build cache.

**Latency > 20 s on HLS:**  
Check `docker compose logs packager` for segment write errors. Restart with `make down && make up`.

---

## License

Apache 2.0 — see [`LICENSE`](LICENSE).
