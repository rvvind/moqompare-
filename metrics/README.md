# metrics

Metrics collection for the comparison lab.

## Planned metrics

### Per-player (HLS and MoQ)
- `playback_latency_seconds` — estimated end-to-end latency
- `rebuffer_count_total` — cumulative rebuffer events
- `rebuffer_duration_seconds` — cumulative time spent rebuffering
- `startup_time_seconds` — time from play() to first frame

### Relay
- `relay_subscriber_count` — active WebTransport subscriber sessions
- `relay_queue_depth` — unflushed objects in relay buffer
- `relay_object_delivery_latency_ms` — publish → subscriber delivery time

### Packager
- `packager_segment_count_total` — segments produced
- `packager_fragment_count_total` — fragments produced

### Impairment
- `impairment_active` — 1 if an impairment profile is currently active, else 0
- `impairment_profile` — label: baseline | jitter | squeeze | outage

## Planned implementation

A lightweight metrics sidecar (Python/Go) that:
1. Scrapes player events from the browser via a POST endpoint
2. Exposes a Prometheus `/metrics` endpoint on `METRICS_PORT` (default `9090`)

## Phase status

- **Phase 0** — placeholder (idle loop, no scraping)
- **Phase 1** — basic HLS segment timing logged to stdout
- **Phase 3** — Prometheus endpoint, Grafana dashboard (optional)
