# packager

Shared media pipeline: live source generator + HLS/fragment packager.

## Responsibility

| Component | Role |
|-----------|------|
| **source** | Generates a synthetic live video with a running UTC timestamp overlay |
| **packager** | Receives the source stream, produces a rolling HLS manifest + fMP4 segments and raw media fragments for the MoQ publisher |

## Shared output volume

Both services write into the `/media` Docker volume:

```
/media/
  hls/
    stream.m3u8          ← rolling manifest (HLS_LIST_SIZE segments)
    seg_000001.m4s
    seg_000002.m4s
    ...
  fragments/
    frag_000001.mp4      ← individual fragments consumed by the publisher
    ...
```

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SOURCE_FPS` | `30` | Frame rate of the synthetic source |
| `SOURCE_RESOLUTION` | `1280x720` | Output resolution |
| `COMPARE_HLS_SEGMENT_DURATION` | `0.5` | Seconds per HLS segment on the compare/present/fanout path |
| `COMPARE_HLS_LIST_SIZE` | `120` | Number of segments to keep in the compare-path manifest |
| `HLS_SEGMENT_DURATION` | `2` | Fallback segment duration when the compare-specific variable is unset |
| `HLS_LIST_SIZE` | `5` | Fallback manifest length when the compare-specific variable is unset |
| `LOG_LEVEL` | `info` | Logging verbosity |

## Phase status

- **Phase 0** — placeholder (idle loop, no media)
- **Phase 1** — FFmpeg source + FFmpeg packager writing real HLS + fragments
