# moqompare

**HLS vs MoQ Live Playback Comparison Lab**

A local lab that plays the same live video stream over HLS and MoQ side by side, with controlled network impairments, so you can directly observe protocol-level differences in latency, rebuffering, and recovery.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                       Shared Upstream                            │
│                                                                  │
│   source (FFmpeg + timestamp overlay)                            │
│       │                                                          │
│   packager (rolling HLS + fMP4 fragments)                        │
│       │                    │                                     │
│       ▼                    ▼                                     │
│   /media/hls/       /media/fragments/                            │
└──────────┬─────────────────┬────────────────────────────────────┘
           │                 │
    ┌──────▼──────┐   ┌──────▼──────────┐
    │   origin    │   │   publisher     │
    │  (nginx,    │   │  (frag watcher  │
    │   HTTP)     │   │   → MoQ pubish) │
    └──────┬──────┘   └──────┬──────────┘
           │ HTTP             │ QUIC
           │          ┌──────▼──────────┐
           │          │     relay       │
           │          │  (MoQ relay)    │
           │          └──────┬──────────┘
           │                 │ WebTransport
           └────────┬────────┘
                    ▼
               ┌─────────┐
               │   web   │  http://localhost:3000
               │  (UI)   │
               └─────────┘
```

| Service | Role | Port |
|---------|------|------|
| `source` | Synthetic live video with UTC timestamp overlay | — |
| `packager` | FFmpeg → rolling HLS manifest + fMP4 fragments | — |
| `origin` | nginx serving HLS over HTTP | 8080 |
| `publisher` | Watches fragments, publishes into MoQ relay | — |
| `relay` | MoQ relay (QUIC/WebTransport) | 4443 |
| `web` | Browser UI: side-by-side players, metrics, impairment controls | 3000 |
| `metrics` | Metrics collector / Prometheus endpoint | 9090 |

---

## Quick start

```sh
# 1. Copy and review environment variables
cp .env.example .env

# 2. Pull images and start all services
make setup
make up

# 3. Open the comparison UI
open http://localhost:3000

# 4. Stream logs
make logs

# 5. Stop everything
make down
```

Or using the scripts directly:

```sh
scripts/setup.sh
scripts/run.sh
scripts/demo.sh      # full impairment demo cycle (Phase 3+)
scripts/impair.sh jitter   # apply jitter + loss profile
scripts/impair.sh baseline # clear impairments
```

---

## Make targets

| Target | Description |
|--------|-------------|
| `make setup` | Copy `.env.example` → `.env`, pull images |
| `make up` | Start all services (detached) |
| `make down` | Stop all services |
| `make logs` | Stream logs from all services |
| `make ps` | Show container status |
| `make clean` | Stop, remove containers + volumes, prune images |

---

## Impairment profiles

Applied via `scripts/impair.sh <profile>`:

| Profile | Effect |
|---------|--------|
| `baseline` | No impairment |
| `jitter` | 30 ms delay ± 20 ms, 1% packet loss |
| `squeeze` | 500 kbit/s rate cap |
| `outage` | 100% loss for 5 s, then clear |

---

## Phase progression

| Phase | Status | Goal |
|-------|--------|------|
| **0** | ✅ complete | Repo skeleton, Docker Compose, placeholder containers |
| **1** | planned | Live HLS stream in the browser |
| **2** | planned | Same stream via MoQ alongside HLS |
| **3** | planned | Impairment injection and event timeline |
| **4** | planned | Full metrics and observability |

See [`docs/phases.md`](docs/phases.md) for detailed acceptance criteria.  
See [`docs/architecture.md`](docs/architecture.md) for design rationale.

---

## Repository layout

```
infra/       Docker Compose support files (nginx configs, tc scripts)
packager/    Live source and HLS/fragment packager
publisher/   MoQ fragment publisher
relay/       MoQ relay
web/         Browser comparison UI
metrics/     Metrics collector
scripts/     setup, run, demo, impair
docs/        Architecture notes and phase plan
```

---

## License

Apache 2.0 — see [`LICENSE`](LICENSE).
