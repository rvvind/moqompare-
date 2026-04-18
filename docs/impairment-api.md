# Impairment API Reference

Concise reference for integrating moqompare's impairment system into an external demo harness.

---

## Services and ports

| Service | Internal host | Default host port | Purpose |
|---|---|---|---|
| `impairment` | `moqompare-impairment:8090` | — (internal only) | tc netem + manifest-freeze controller |
| `manifest-proxy` | `moqompare-manifest-proxy:8091` | — (internal only) | HLS manifest caching proxy |
| `web` (nginx) | — | `3000` | Browser UI; proxies `/hls/*.m3u8` through manifest-proxy |

> **External harness note:** Neither `impairment` nor `manifest-proxy` expose a host port by default. To drive them from outside the compose network, either add `ports:` entries in `docker-compose.yml`, or call them through a sidecar container on the `moqompare` bridge network.

---

## Impairment controller — `POST /impair/<profile>`

Base URL (inside compose network): `http://moqompare-impairment:8090`

All endpoints accept `POST` with no body and return JSON.

### Profiles

#### `baseline` — clear all impairments
```
POST /impair/baseline
```
- Deletes any active `tc netem` qdisc from both the HLS nginx container (`moqompare-web`) and the MoQ relay container (`moqompare-relay`).
- Calls `POST /unfreeze` on the manifest-proxy to resume live manifests and flush the stale cache.
- Always safe to call; idempotent.
- **Both HLS and MoQ**: fully restored.

---

#### `jitter` — network delay + packet loss (both protocols)
```
POST /impair/jitter
```
- Applies `tc netem delay 30ms 20ms distribution normal loss 1%` to both `moqompare-web` and `moqompare-relay` eth0 interfaces.
- Effect: ~10–50 ms of variable per-packet delay plus 1% random loss.
- **HLS**: segment fetch latency increases; player may buffer briefly.
- **MoQ**: object delivery latency increases; QUIC retransmits absorb some loss.

---

#### `squeeze` — bandwidth cap (both protocols)
```
POST /impair/squeeze
```
- Applies `tc netem rate 500kbps` to both containers.
- Effect: hard 500 kbit/s rate limit on outgoing traffic from each container.
- **HLS**: 1080p hi-rendition (~4 Mbps) becomes unplayable; player ABR switches to 360p lo-rendition (~500 kbps).
- **MoQ**: same bandwidth pressure; JS ABR controller switches from `stream_hi` to `stream_lo` broadcast.

---

#### `outage` — total packet loss, auto-clears after 5 s (both protocols)
```
POST /impair/outage
```
- Applies `tc netem loss 100%` to both containers.
- After **5 seconds** the controller automatically calls `baseline` (no manual clear needed).
- **HLS**: player buffers stall immediately; rebuffers on recovery.
- **MoQ**: relay connection drops; player reconnects and resumes from live edge on recovery.
- Response includes `"auto_clear_secs": 5`.

---

#### `stale_manifest` — frozen HLS manifests, auto-clears after 30 s (HLS only)
```
POST /impair/stale_manifest
```
- **Application-layer impairment — no tc netem involved.**
- Clears any existing netem rules first (network is clean), then calls `POST /freeze` on the manifest-proxy.
- From this point, every `*.m3u8` request served through nginx returns the snapshot that was cached at freeze time — the segment list never advances.
- After **30 seconds** the controller automatically calls `baseline` (unfreezes, flushes cache).
- **HLS**: players poll for new segments several times per second, receive the same stale list each time, and stall once their buffer drains. On recovery, players resume ~30 s behind the live edge and stay there (no automatic seek-to-live — see [Player configuration](#player-configuration)).
- **MoQ**: completely unaffected. The relay pushes new objects directly; no manifest is consulted.
- Response includes `"auto_clear_secs": 30`.

---

### Status endpoint
```
GET /impair/status
→ {"profile": "squeeze"}
```

---

### Response schema (all POST endpoints)

```json
{
  "ok": true,
  "profile": "outage",
  "errors": [],
  "auto_clear_secs": 5
}
```

| Field | Type | Notes |
|---|---|---|
| `ok` | bool | `false` if any target container was unreachable |
| `profile` | string | The profile that was requested |
| `errors` | array | Per-container error strings; empty on success |
| `auto_clear_secs` | int \| null | Non-null only for `outage` (5) and `stale_manifest` (30) |

HTTP status is `200` on success, `400` on error. Paths accept both `/impair/<profile>` and `/<profile>`.

---

## Manifest-proxy — direct control (optional)

Base URL (inside compose network): `http://moqompare-manifest-proxy:8091`

The impairment controller calls these automatically as part of the `stale_manifest` / `baseline` profiles. Your harness can also call them directly if you want finer-grained control (e.g. freeze without the 30 s auto-clear, or hold for a custom duration).

| Endpoint | Method | Effect |
|---|---|---|
| `POST /freeze` | — | Start serving frozen (cached) manifests to all HLS players |
| `POST /unfreeze` | — | Resume live proxying; flush the stale cache |
| `GET /status` | — | `{"frozen": bool, "cached": <path count>}` |
| `GET /health` | — | `200 "ok"` |

**Custom freeze duration example:**
```bash
# Freeze for 60 s instead of the default 30 s
curl -X POST http://manifest-proxy:8091/freeze
sleep 60
curl -X POST http://manifest-proxy:8091/unfreeze
# Or trigger via the impairment controller to also log the event in the browser UI:
curl -X POST http://impairment:8090/impair/baseline
```

---

## Netem targets

The netem rules are applied to two container interfaces, not the host:

| Variable | Default container | What it impairs |
|---|---|---|
| `HLS_CONTAINER` | `moqompare-web` | HLS segment delivery to browsers (nginx proxy egress) |
| `RELAY_CONTAINER` | `moqompare-relay` | MoQ object delivery to browsers (QUIC egress) |

> **Why `moqompare-web` and not `moqompare-origin`?**  
> The origin also serves the publisher→relay ingest path. Impairing origin degrades MoQ ingest too, producing correlated failures. Targeting the web proxy isolates browser-side delivery without touching the packaging pipeline.

---

## Quick reference — curl one-liners

```bash
# Baseline (clear everything)
curl -s -X POST http://localhost:8090/impair/baseline | jq .

# Jitter
curl -s -X POST http://localhost:8090/impair/jitter | jq .

# Squeeze (500 kbps cap)
curl -s -X POST http://localhost:8090/impair/squeeze | jq .

# 5-second outage
curl -s -X POST http://localhost:8090/impair/outage | jq .

# 30-second stale manifest (HLS only)
curl -s -X POST http://localhost:8090/impair/stale_manifest | jq .

# Poll current profile
curl -s http://localhost:8090/impair/status | jq .
```

> Replace `localhost:8090` with your harness's route to the impairment container.

---

## Player configuration notes

These are relevant if your harness re-embeds the player or modifies hls.js config:

| Setting | Value | Reason |
|---|---|---|
| `liveMaxLatencyDurationCount` | `240` (× 0.5 s segments = 120 s) | Prevents hls.js from auto-seeking to live edge after stale manifest recovery |
| `maxLiveSyncPlaybackRate` | `1.0` | Disables playback speed-up catch-up; lag stays visible in the UI |
| `COMPARE_HLS_LIST_SIZE` | `120` (= 60 s of segments at 0.5 s each) | Manifest retains segments from before the freeze so hls.js can resume without a seek |

Without these settings, hls.js will seek back toward the live edge within seconds of falling behind, making the stale manifest lag much less visible.

---

## Suggested demo sequence

A scripted sequence that shows the HLS vs MoQ contrast clearly:

```
1. Steady state (~30 s)      POST /impair/baseline
2. Show jitter               POST /impair/jitter        (manual clear when done)
3. Show squeeze + ABR        POST /impair/squeeze       (manual clear when done)
4. Show 5-s outage           POST /impair/outage        (auto-clears)
5. Show stale manifest       POST /impair/stale_manifest
   → observe HLS stall / MoQ unaffected
   → auto-clears after 30 s
   → observe HLS lag badge showing "Xs behind" while MoQ stays at live head
6. Clear / reset             POST /impair/baseline
```

---

## Composability notes

- All `POST` profiles are **last-write-wins**: calling `squeeze` while `jitter` is active replaces jitter with squeeze.
- `stale_manifest` + any netem profile cannot be active simultaneously. `stale_manifest` clears netem on entry; all other profiles call `/unfreeze` on entry.
- Any pending auto-clear timer is cancelled whenever a new profile is applied.
- The `GET /impair/status` endpoint reflects the last successfully applied profile; check `errors` in the POST response to detect partial failures.
