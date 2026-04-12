# moqompare

**HLS vs MoQ Live Playback Comparison Lab**

A local lab that plays the same live video stream over HLS and MoQ side by side, with controlled network impairments, so you can directly observe protocol-level differences in latency, rebuffering, and recovery.

---

## Current phase: Phase 7 complete

**What works:**
- Live video source: loops `.mp4` files from `/videos/` (or falls back to FFmpeg `testsrc2`) with a visible UTC timestamp overlay, output as MPEG-TS into a named pipe
- Source loops using a pre-expanded concat playlist (5 files × 999 reps) — no FIFO starvation gaps at loop boundaries
- **Dual-rendition fMP4 HLS**: hi @ source resolution/bitrate, lo @ 640×360 / 500 kbps; ABR master playlist served by nginx origin
- **MoQ path**: two moq-cli publishers (hi + lo renditions) ingest HLS → moq-relay (QUIC/WebTransport) → hang-watch browser player with custom ABR logic
- Side-by-side comparison UI at `:3000` with per-player metrics: startup time, live latency, stall count, bitrate, resolution
- **Presentation workspace** at `:3000/present.html`: single-screen live demo with scene flow, shared telemetry, live architecture map, and presenter controls rail
- **Impairment controller**: `tc netem` applied to origin and relay network namespaces via Docker socket + `nsenter`; five profiles including Stale Manifest
- **Manifest proxy** at `:8091`: can freeze the HLS manifest independently of segment delivery to demonstrate manifest-less MoQ advantage
- **Metrics collector**: browser reports every 5 s; Prometheus endpoint at `:9090/metrics`; JSON snapshot at `:9090/snapshot`
- **Fan-out simulation**: N concurrent moq-cli subscribers via Docker Compose `fanout` profile
- `scripts/report.sh` cycles all impairment profiles and generates a Markdown comparison table with HLS vs MoQ deltas

**Known limitations:**
- MoQ playback has ~4–5 s latency due to HLS ingest burst pattern (2 s segments)
- `tc netem` requires a Linux Docker runtime that supports privileged containers, `pid: host`, and network namespace entry
- Metrics are browser-pushed; relay-side metrics not yet instrumented

---

## Architecture

```
  source (FFmpeg: looped /videos/*.mp4 or testsrc2 + UTC timestamp overlay)
      │  MPEG-TS via named pipe (/media/source.pipe)
  packager (FFmpeg: dual-rendition fMP4 HLS → /media/hls/)
      │
      ├────────────────────────────────────────────────────┐
      │  HLS path                                          │  MoQ path
      ▼                                                    ▼
  origin (nginx :8080)                    publisher-hi / publisher-lo (moq-cli)
      │  /hls/master.m3u8                     │  poll master_hi/lo.m3u8
      │  /hls/stream_hi.m3u8                  ▼
      │  /hls/stream_lo.m3u8         relay (moq-relay :4443 QUIC+TCP)
      ▼                                       │  WebTransport
  manifest-proxy (:8091)                      │
      │  can freeze manifest                  │
      ▼                                       │
  web (nginx :3000) ◄─────────────────────────┘
      │  /hls/           → manifest-proxy → origin
      │  /impair/        → impairment (:8090)
      │  /metrics/       → metrics (:9090)
      ▼
  Browser: HLS player (hls.js) │ MoQ player (hang-watch)
           impairment buttons  │ event timeline
           present.html        │ presentation workspace

  impairment (:8090)  — tc netem via nsenter, uses Docker socket
  metrics    (:9090)  — Prometheus endpoint, receives browser reports
```

| Service | Role | Port |
|---------|------|------|
| `source` | FFmpeg: looped mp4 files or testsrc2 + UTC timestamp → named pipe | — |
| `packager` | FFmpeg: MPEG-TS → dual-rendition fMP4 HLS segments + master playlists | — |
| `origin` | nginx: serves `/hls/` over HTTP | 8080 |
| `manifest-proxy` | Go proxy: transparent pass-through or manifest freeze | 8091 |
| `publisher-hi` | moq-cli (built from source): hi-rendition HLS ingest → QUIC publish | — |
| `publisher-lo` | moq-cli (built from source): lo-rendition HLS ingest → QUIC publish | — |
| `relay` | moq-relay (built from source): QUIC relay + HTTP cert endpoint | **4443** |
| `web` | nginx: browser UI, proxies `/hls/`, `/impair/`, `/metrics/` | **3000** |
| `impairment` | Python3: `tc netem` HTTP API via nsenter | 8090 |
| `metrics` | Python3: Prometheus metrics collector (browser-push) | 9090 |

---

## Prerequisites

- Docker Engine 24+
- Docker Compose available as the v2 plugin (`docker compose`) or standalone `docker-compose`
- Docker runtime via Docker Desktop or Colima
- If using Colima: `colima start --runtime docker` before running `make setup` or `make up`
- Internet access during `make setup` (pulls images, downloads hls.js, clones moq-rs)

---

## Quick start

```sh
# 1. Clone and enter the repo
git clone <repo-url> moqompare
cd moqompare

# 2. Bootstrap: copy .env, generate cluster credentials, pull + build images
make setup

# 3. Start all services
make up

# 4. Open the comparison UI
open http://localhost:3000

# 5. Open the presentation workspace
open http://localhost:3000/present.html

# 6. Watch logs
make logs

# 7. Stop everything
make down
```

**Expected startup sequence:**

*First run — Rust compilation:* `relay` and `publisher-hi/lo` build moq-rs from source (~5–10 min). Subsequent runs use the Docker layer cache and start in seconds.

1. `source` starts → creates FIFO and begins encoding → healthcheck passes (~10 s)
2. `packager` reads FIFO → writes first HLS segments → healthcheck passes (~20 s)
3. `origin` starts → serves `/hls/` immediately
4. `relay` starts → generates TLS cert for `localhost,relay` → healthcheck passes
5. `publisher-hi` and `publisher-lo` connect to relay → poll master playlists → start ingesting HLS
6. `manifest-proxy`, `web`, `impairment`, `metrics` start
7. Browser: HLS plays within ~5–10 s; MoQ plays within ~10–15 s

---

## Verification steps

### 1. Check all services are running

```sh
make ps
```

All services should show `healthy` or `running`.

### 2. Verify HLS ABR manifest is updating

```sh
curl http://localhost:8080/hls/master.m3u8
```

Expected: a valid M3U8 master playlist referencing `stream_hi.m3u8` and `stream_lo.m3u8`.

```sh
curl http://localhost:8080/hls/stream_hi.m3u8
```

Run it twice, 3 seconds apart — segment entries should change (rolling manifest).

### 3. Verify HLS browser playback

Open `http://localhost:3000`. Within ~10 s:
- HLS panel: live video with `SRC HH:MM:SS UTC` timestamp visible
- Startup time shown in milliseconds
- Latency estimate updating (typically 6–12 s for HLS with 2 s segments)
- Stall counter stays at 0 under normal conditions

### 4. Verify MoQ playback

Within ~15 s the MoQ panel should also show live video:

```sh
docker-compose logs publisher-hi --tail=20
docker-compose logs relay --tail=20
```

If the MoQ panel shows "Waiting for broadcast" after 30 s, reload the page once.

### 5. Verify metrics collector

After both players have been running for at least 5 seconds:

```sh
curl http://localhost:9090/snapshot
curl http://localhost:3000/metrics/snapshot
```

Expected: `player_latency_seconds`, `player_stalls_total`, and `player_startup_ms` for both `hls` and `moq`.

### 6. Full demo with impairment cycle

```sh
./scripts/demo.sh
```

Opens the browser, cycles through all impairment profiles, prints a metrics snapshot.

### 7. Automated comparison report

```sh
./scripts/report.sh --out report.md
```

Cycles all profiles and writes a Markdown table comparing HLS vs MoQ latency, stalls, and bitrate under each condition.

---

## Make targets

| Target | Description |
|--------|-------------|
| `make setup` | Copy `.env.example` → `.env`, generate cluster credentials, pull + build images |
| `make up` | Start all services (detached) |
| `make down` | Stop all services |
| `make logs` | Stream logs from all services |
| `make ps` | Show container status |
| `make clean` | Stop, remove containers + volumes, prune images |
| `./scripts/demo.sh` | Full impairment demo cycle + metrics snapshot |
| `./scripts/report.sh` | Automated cycle → `report.md` with HLS vs MoQ comparison table |
| `docker-compose --profile fanout up -d fanout` | Start N concurrent MoQ subscribers |

---

## Impairment profiles

Applied via the UI, `scripts/impair.sh <profile>`, or `POST http://localhost:8090/impair/<profile>`:

| Profile | Effect | HLS impact | MoQ impact |
|---------|--------|------------|------------|
| `baseline` | No impairment | Clean reference | Clean reference |
| `jitter` | 30 ms delay ± 20 ms, 1% loss | TCP throughput collapses; hls.js drops to lo rendition | QUIC recovers loss via retransmit; no rendition switch |
| `squeeze` | 500 kbit/s rate cap | hls.js switches to lo rendition at 640×360 | MoQ ABR switches to `stream_lo` once bandwidth < 3.6 Mbps |
| `outage` | 100% loss for 5 s, then clear | Buffer drains; full rebuffer on recovery | QUIC reconnects in ~1 RTT; faster recovery |
| `stale_manifest` | Manifest proxy freezes HLS playlist for 30 s | Player stalls (manifest not advancing); segments and bandwidth healthy | No effect — MoQ is manifest-less |

---

## Environment variables

Edit `.env` (copied from `.env.example`) to tune:

| Variable | Default | Description |
|----------|---------|-------------|
| `SOURCE_FPS` | `30` | Frame rate |
| `SOURCE_RESOLUTION` | `1920x1080` | Video resolution |
| `SOURCE_BITRATE` | `4000k` | x264 target bitrate for hi rendition |
| `HLS_SEGMENT_DURATION` | `2` | Seconds per segment |
| `HLS_LIST_SIZE` | `5` | Segments kept in rolling manifest |
| `ABR_LO_BITRATE` | `500k` | Lo-rendition bitrate |
| `ABR_LO_RESOLUTION` | `640x360` | Lo-rendition resolution |
| `ORIGIN_PORT` | `8080` | Host port for HLS origin |
| `RELAY_PORT` | `4443` | Host port for MoQ relay (QUIC + TCP) |
| `WEB_PORT` | `3000` | Host port for browser UI |
| `VIDEOS_DIR` | `./videos` | Directory of `.mp4` files to loop as live source |

---

## Phase progression

| Phase | Status | Goal |
|-------|--------|------|
| **0** | ✅ | Repo skeleton, Docker Compose, placeholder containers |
| **1** | ✅ | Live HLS stream in the browser with metrics |
| **2** | ✅ | Same stream via MoQ alongside HLS |
| **3** | ✅ | Impairment injection and event timeline |
| **4** | ✅ | Full metrics and observability |
| **5** | ✅ | ABR ladder — dual rendition, observable level switching |
| **6** | ✅ | Subscriber fan-out simulation |
| **7** | ✅ | Automated impairment report |
| **8** | ✅ | Presentation workspace with scene flow and live architecture map |

See [`docs/phases.md`](docs/phases.md) for detailed acceptance criteria.  
See [`docs/architecture.md`](docs/architecture.md) for design rationale.

---

## Repository layout

```
infra/            nginx configs (origin, web), future impairment scripts
packager/         FFmpeg dual-rendition fMP4 HLS packager
publisher/        moq-cli publisher (hi + lo renditions)
relay/            moq-relay (QUIC/WebTransport)
manifest-proxy/   Go HLS manifest proxy (supports freeze for Stale Manifest impairment)
source/           Live source generator (looped mp4 or FFmpeg testsrc2 + drawtext)
web/              Browser UI: hls.js player, hang-watch MoQ player, presentation workspace
  static/
    index.html              Side-by-side comparison UI
    present.html            Presentation workspace
    present-control.html    Presenter control panel
    presentation/           Shared CSS + JS modules for presentation mode
metrics/          Prometheus metrics collector (browser-push model)
impairment/       tc netem HTTP API (Python, privileged)
fanout/           Concurrent MoQ subscriber simulation
scripts/          setup, run, demo, impair, report scripts
docs/             Architecture notes and phase plan
```

---

## Troubleshooting

**`source` container stuck in starting:**  
The source creates a named FIFO; FFmpeg blocks until the packager opens it. This is normal — packager starts after source is healthy.

**No HLS video in browser after 30 s:**  
```sh
docker-compose logs packager          # look for ffmpeg errors
docker-compose exec origin ls /usr/share/nginx/html/hls/
# should list master.m3u8, stream_hi.m3u8, stream_lo.m3u8, init_hi.mp4, init_lo.mp4
```

**MoQ panel shows "Waiting for broadcast" indefinitely:**  
```sh
docker-compose logs publisher-hi --tail=30   # should show HLS segments being published
docker-compose logs relay --tail=30          # look for negotiated version=moq-lite-03
```
If publisher logs show `catalog.json err=not found`, rebuild: `docker-compose up -d --build publisher-hi publisher-lo`.

**Impairment buttons return "pid not found":**  
```sh
docker-compose logs impairment | head -10
docker-compose exec impairment docker inspect --format '{{.State.Pid}}' moqompare-origin
```
If `docker inspect` fails, the socket bind may need `DOCKER_HOST` set — check Docker Desktop / Colima settings.

**Playback stalls periodically (video looping):**  
Ensure the source container is running the updated image. The old `‑stream_loop ‑1` flag caused FFmpeg to rescan all input files at each loop boundary, starving the FIFO. The current image uses a pre-expanded 999-repetition playlist so FFmpeg runs for hours without restarting.

**`make setup` / `make up` says Docker daemon is not reachable:**  
```sh
colima start --runtime docker
```

**First `make up` hangs for minutes:**  
Normal — Rust compiles `moq-relay` and `moq-cli` from source. Subsequent starts use the build cache.

---

## License

Apache 2.0 — see [`LICENSE`](LICENSE).
