# relay

MoQ relay — receives published tracks from the publisher and fans them out to subscribed players.

## Responsibility

- Accept incoming QUIC/WebTransport connections
- Handle MoQ publisher sessions (ANNOUNCE + SUBSCRIBE_OK)
- Forward subscribed objects to connected players
- Expose a metrics endpoint for relay queue depth, subscriber count, and delivery latency

## Planned implementation

[moq-rs](https://github.com/kixelated/moq-rs) relay binary, or equivalent Go/Rust MoQ relay.

The relay listens on port `4443` (QUIC). A self-signed TLS certificate is generated at startup for local use.

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `RELAY_PORT` | `4443` | QUIC listen port |
| `LOG_LEVEL` | `info` | Logging verbosity |

## Phase status

- **Phase 0** — placeholder (idle loop, port not actually listening)
- **Phase 2** — real MoQ relay with QUIC transport
