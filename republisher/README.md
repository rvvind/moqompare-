# republisher

Backend-owned program broadcaster for the production workspace.

## Responsibility

1. Poll the registry for the desired `program` route
2. Resolve the selected source's republishable HLS playlist
3. Run `moq-cli publish` against that playlist under a stable MoQ broadcast name
4. Keep the downstream output name stable while the upstream route changes

In the current production slice, those upstream playlists come from the
alternate-angle packagers under `/videos/alt-angles`.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Liveness check |
| `GET` | `/status` | Current source, playlist, restart count, and last error |

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `REPUBLISHER_PORT` | `8094` | HTTP listen port |
| `REGISTRY_URL` | `http://registry:8093` | Registry base URL |
| `RELAY_URL` | `http://relay:4443` | MoQ relay URL for publish |
| `PROGRAM_STREAM_NAME` | `stream_program` | Stable downstream broadcast name |
| `REPUBLISHER_POLL_INTERVAL_SECS` | `1.0` | Registry poll cadence |
