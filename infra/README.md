# infra

Local orchestration and network configuration.

## Contents

```
infra/
  nginx/
    origin.conf   ← nginx config for the HLS HTTP origin
    web.conf      ← nginx config for the browser UI
```

## Docker Compose

The root `docker-compose.yml` defines all services. All services share the `moqompare` bridge network. Media files are exchanged via the `media` named volume.

This stack expects a Linux Docker engine. On macOS, that can be Docker Desktop
or Colima using the Docker runtime.

## Service dependency graph

```
source ──► packager ──► origin
                    └──► publisher ──► relay
                                   web (depends on origin + relay)
metrics (independent)
```

## Planned: impairment via tc/netem

In Phase 3, `infra/` will contain shell scripts that apply Linux traffic control (`tc netem`) rules to the compose network interface to simulate:

- Moderate jitter and packet loss
- Bandwidth cap
- Transient burst outage

These scripts require a Linux Docker runtime that supports privileged
containers, `pid: host`, and namespace entry from the impairment container.
