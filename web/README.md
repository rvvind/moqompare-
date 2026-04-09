# web

Browser-based comparison UI served by nginx.

## Layout

```
web/
  static/
    index.html    ← single-page app (plain HTML/JS, no build step in early phases)
```

## UI panels

| Panel | Content |
|-------|---------|
| HLS player | `<video>` element fed by hls.js |
| MoQ player | Custom MoQ WebTransport player |
| Per-player metrics | Current latency estimate, rebuffer count |
| Impairment controls | Buttons to apply/remove impairment profiles |
| Event timeline | Timestamped log of induced impairments and player events |

## Port

The UI is served on `WEB_PORT` (default `3000`). Open `http://localhost:3000` in a browser.

## Phase status

- **Phase 0** — static placeholder page with UI skeleton, no live data
- **Phase 1** — HLS player wired to origin, real latency/rebuffer metrics
- **Phase 2** — MoQ player connected to relay
- **Phase 3** — impairment controls functional, event timeline live
