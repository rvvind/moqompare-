# publisher

MoQ fragment publisher — watches the packager output and publishes each media fragment into the MoQ relay.

## Responsibility

1. Watch `/media/fragments/` for new fragment files written by the packager
2. For each fragment, open a MoQ publish session to the relay
3. Map each fragment to a MoQ **object** with appropriate track/group/object IDs
4. Publish the fragment bytes and close the object

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `RELAY_HOST` | `relay` | Hostname of the MoQ relay (compose service name) |
| `RELAY_PORT` | `4443` | Port of the MoQ relay (QUIC/WebTransport) |
| `LOG_LEVEL` | `info` | Logging verbosity |

## MoQ track layout (planned)

```
namespace : moqompare
track     : video/main
group     : <segment sequence number>
object    : <fragment index within segment>
```

## Phase status

- **Phase 0** — placeholder (idle loop, no publishing)
- **Phase 2** — real MoQ publish using moq-rs or equivalent
