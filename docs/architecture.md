# Architecture

## Overview

moqompare is a local lab that plays the same live video stream over two protocols simultaneously, so protocol-level differences in latency, rebuffering, and impairment recovery are directly observable.

```
┌─────────────────────────────────────────────────────────────────┐
│                        Shared Upstream                          │
│                                                                 │
│  ┌──────────────┐        ┌──────────────────────────────────┐   │
│  │    source    │──────► │           packager               │   │
│  │  (FFmpeg     │        │  HLS rolling manifest + segments  │   │
│  │  timestamp   │        │  fMP4 fragments for MoQ           │   │
│  │  overlay)    │        └─────────────┬────────────────────┘   │
│  └──────────────┘                      │ /media volume           │
└───────────────────────────────────────┼─────────────────────────┘
                                        │
                    ┌───────────────────┴────────────────────┐
                    │                                        │
                    ▼                                        ▼
         ┌─────────────────┐                   ┌─────────────────────┐
         │     origin      │                   │      publisher      │
         │  (nginx, HTTP)  │                   │ (fragment watcher → │
         │  /hls/*.m3u8    │                   │  MoQ publish)       │
         └────────┬────────┘                   └──────────┬──────────┘
                  │ HTTP                                   │ QUIC
                  │                             ┌──────────▼──────────┐
                  │                             │        relay        │
                  │                             │   (MoQ relay,       │
                  │                             │    QUIC/WT)         │
                  │                             └──────────┬──────────┘
                  │                                        │ WebTransport
                  └──────────────┐         ┌──────────────┘
                                 ▼         ▼
                          ┌──────────────────────┐
                          │         web          │
                          │  HLS player (hls.js) │
                          │  MoQ player (custom) │
                          │  metrics overlay     │
                          │  impairment controls │
                          │  event timeline      │
                          └──────────────────────┘
```

## Key design decisions

| Decision | Rationale |
|----------|-----------|
| Single shared source | Ensures bit-identical media on both paths; removes encoding differences as a variable |
| fMP4 segments | Compatible with both HLS and MoQ object mapping |
| Single rendition | Eliminates ABR as a variable in early phases |
| Docker Compose | Simple local orchestration, no Kubernetes overhead |
| Named `media` volume | Low-overhead IPC between packager, origin, and publisher |
| Explicit env vars | Every tunable is visible; no hidden defaults |

## Network paths

| Path | Transport | Port |
|------|-----------|------|
| HLS origin → browser | HTTP/1.1 TCP | 8080 |
| MoQ relay ↔ publisher | QUIC | 4443 |
| MoQ relay → browser | WebTransport (QUIC) | 4443 |
| Browser UI | HTTP | 3000 |
| Metrics | HTTP (Prometheus) | 9090 |

## Impairment injection (Phase 3+)

Traffic impairments are applied at the Linux network level using `tc netem` on the compose bridge interface. The same impairment applies to both HLS and MoQ paths unless selectively targeted by IP/port.

Profiles:

| Profile | tc settings |
|---------|-------------|
| baseline | no impairment |
| jitter | delay 30ms ±20ms, loss 1% |
| squeeze | rate 500kbit |
| outage | loss 100% for 5 seconds, then clear |
