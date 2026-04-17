# registry

Stream discovery and route-state service for the production workspace.

## Responsibility

1. Maintain a discoverable catalog of streams and their metadata
2. Accept publisher registration and heartbeat updates
3. Track the current `program` route target
4. Broadcast stream and route events to the UI via Server-Sent Events

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Liveness check |
| `GET` | `/api/status` | Full snapshot: streams, routes, recent events |
| `GET` | `/api/streams` | Current catalog |
| `GET` | `/api/streams/<id>` | Single stream metadata |
| `POST` | `/api/streams/register` | Register or update a publisher-owned stream |
| `POST` | `/api/streams/heartbeat` | Refresh `last_seen_at` for a stream |
| `GET` | `/api/routes` | Current route state |
| `POST` | `/api/routes/program` | Set the current `program` source |
| `POST` | `/api/routes/program/modifier` | Apply or clear a program modifier such as `slate` |
| `GET` | `/api/events` | SSE stream for catalog and route updates |

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `REGISTRY_PORT` | `8093` | HTTP listen port |
| `REGISTRY_STREAM_TTL_SECS` | `15` | Heartbeat timeout before dynamic streams become `stale` |

## Current behavior

This slice mixes:

- bootstrap camera entries for `cam-a` and `cam-b`
- self-registering live camera services that overwrite those bootstrap entries
- one seeded standby artifact (`slate`)

Current production feeds:

- `cam-a` → seeded at startup, then dynamically refreshed by `angle-packager-cam-a`
- `cam-b` → seeded at startup, then dynamically refreshed by `angle-packager-cam-b`
- `slate` → seeded as an always-on standby artifact

The two camera feeds are backed by dedicated alternate-angle files in
`/videos/alt-angles`:

- `cam-a` → `stream_cam_a` → `http://origin/hls/angles/cam-a/master.m3u8`
- `cam-b` → `stream_cam_b` → `http://origin/hls/angles/cam-b/master.m3u8`
- `slate` → `stream_slate` → `http://origin/hls/angles/slate/master.m3u8`

The backend republisher uses those angle-specific HLS playlists to keep the
downstream `stream_program` broadcast stable while the selected source changes.

This bootstrap-plus-registration model keeps discovery usable even during
partial rebuilds, while still allowing live services to advertise health via
registration and heartbeat once they are updated.

The current `program` route model tracks:

- routed source (`route_stream_id`)
- effective source (`stream_id`)
- optional modifier state (`modifier`)

This lets the UI and republisher distinguish between:

- the camera the operator has routed
- the artifact currently overriding it, if any
