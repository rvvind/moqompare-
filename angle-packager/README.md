# angle-packager

Dedicated live HLS packager for the Produce/Program alternate-angle feeds.

## Responsibility

1. Loop a single `.mp4` source from `/videos/alt-angles`
2. Burn in a camera label plus UTC timestamp overlay
3. Encode a single-rendition low-latency fMP4 HLS output
4. Write a MoQ-compatible single-rendition master playlist for `moq-cli publish`

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `ANGLE_VIDEO_FILE` | required | Absolute path to the backing camera file |
| `ANGLE_OUTPUT_DIR` | required | Output directory under `/media/hls/` |
| `ANGLE_STREAM_KEY` | `camera` | Stable identifier for logs and temp files |
| `ANGLE_LABEL` | `Camera` | Overlay label burned into the video |
| `ANGLE_NAMESPACE` | `lab/source/<stream-key>` | Registry namespace for the source |
| `ANGLE_PLAYBACK_STREAM_NAME` | `stream_<stream-key>` | MoQ playback stream registered for preview |
| `ANGLE_SUMMARY` | `Camera alternate-angle feed` | Catalog summary text sent to the registry |
| `ANGLE_TAGS` | `camera,alt-angle` | Comma-separated registry tags |
| `REGISTRY_URL` | unset | Registry base URL; when set, the service self-registers and heartbeats |
| `ANGLE_RESOLUTION` | `1920x1080` | Output resolution |
| `ANGLE_FPS` | `30` | Output frame rate |
| `ANGLE_BITRATE` | `3500k` | Video bitrate |
| `ANGLE_HLS_SEGMENT_DURATION` | `0.5` | Segment duration in seconds for the Produce/Program path |
| `ANGLE_HLS_LIST_SIZE` | `10` | Rolling manifest length for the Produce/Program path |
| `HLS_SEGMENT_DURATION` | `2` | Fallback segment duration when the angle-specific variable is unset |
| `HLS_LIST_SIZE` | `5` | Fallback rolling manifest length when the angle-specific variable is unset |

## Output layout

Each instance writes:

- `master.m3u8`
- `stream.m3u8`
- `init.mp4`
- `seg_*.m4s`

Produce and Program use these HLS outputs as the source of truth for:

- source preview MoQ broadcasts (`stream_cam_a`, `stream_cam_b`)
- stable program republish input for `stream_program`

The default production profile uses 500 ms segments for the alternate-angle
feeds so the MoQ preview/program path can run at a visibly lower latency than
the original 2-second production slice.

When `REGISTRY_URL` is set, each angle-packager instance also:

- registers itself with `/api/streams/register`
- heartbeats every 5 seconds with `/api/streams/heartbeat`
- becomes `stale` in the catalog if heartbeats stop
