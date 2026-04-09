# Phase Plan

Each phase ends with the repo in a runnable, testable state.

---

## Phase 0 — Skeleton ✅

**Goal:** Repo structure, local orchestration, placeholder containers.

Deliverables:
- Directory skeleton
- `docker-compose.yml` with all services (placeholder images)
- `.env.example`
- `Makefile`
- Placeholder browser UI
- This documentation

Acceptance test: `docker compose up` — all services start, no fatal errors.

---

## Phase 1 — HLS Path

**Goal:** Live HLS stream plays in the browser.

Deliverables:
- FFmpeg source container generating 1280×720 @ 30fps with UTC timestamp overlay
- FFmpeg packager producing rolling HLS (fMP4 segments) into the `media` volume
- nginx origin serving `/hls/stream.m3u8`
- Browser: hls.js player connected to the origin
- Visible timestamp in the HLS player
- Latency estimate (wall clock − segment timestamp)
- Rebuffer counter

Acceptance test: open `http://localhost:3000`, see live HLS stream with timestamp.

---

## Phase 2 — MoQ Path

**Goal:** Same live stream plays via MoQ alongside HLS.

Deliverables:
- Publisher watches `media/fragments/`, publishes each fragment to relay
- moq-rs (or equivalent) relay running on port 4443
- Browser: WebTransport MoQ player, same stream as HLS player
- Visible timestamp in the MoQ player
- Latency estimate and rebuffer counter for MoQ

Acceptance test: both HLS and MoQ players show the same running timestamp simultaneously.

---

## Phase 3 — Impairment Injection

**Goal:** Controlled network impairments can be applied and observed.

Deliverables:
- `scripts/impair.sh` applying tc netem profiles to the compose network
- Impairment profile buttons in the browser UI wired to the backend
- Event timeline showing impairment start/end
- Metrics visible for both players during impairment

Acceptance test: apply "jitter + loss" profile, observe divergent behaviour between HLS and MoQ players.

---

## Phase 4 — Metrics & Observability

**Goal:** All key metrics are visible and logged.

Deliverables:
- Metrics sidecar exporting Prometheus metrics
- Per-player: latency, rebuffer count, rebuffer duration, startup time
- Relay: subscriber count, queue depth, delivery latency
- Optional: Grafana dashboard
- `scripts/demo.sh` — end-to-end demo script

Acceptance test: metrics reflect what is observed visually during impairment cycles.

---

## Future (post-Phase 4)

- ABR ladder (multiple renditions)
- Subscriber fan-out simulation
- Automated impairment cycle with report generation
