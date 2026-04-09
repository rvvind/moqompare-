# CLAUDE.md

## Project

**moqompare-** — HLS vs MoQ Live Playback Comparison Lab

A small-scale local lab that demonstrates side-by-side live video playback over:
1. **HLS** using a rolling manifest served over HTTP
2. **MoQ** using the same packaged media fragments converted into MoQ objects and delivered through a relay

The system supports controlled impairment injection and side-by-side playback observation.

## Primary Outcome

A browser-based comparison page showing:
- HLS player
- MoQ player
- Visible source timestamp overlay
- Protocol-specific metrics
- Current impairment profile
- Event timeline of induced impairments

## Non-Goals

- Production hardening
- Large-scale subscriber simulation (initial phases)
- Full ABR ladder optimization (initial phases)
- Distributed cloud deployment
- Statistically rigorous benchmarking (initial phases)

## Repository Layout

```
/infra        # Docker Compose, network configs, impairment tooling
/packager     # Live source generator, timestamp overlay, HLS + fragment packager
/publisher    # MoQ fragment watcher and publisher
/relay        # MoQ relay server
/web          # Browser UI: side-by-side players, metrics overlay, impairment controls
/metrics      # Metrics collection and event logging
/scripts      # setup, run, test, demo scripts
/docs         # Architecture notes, phase summaries, protocol references
```

## Architecture

```
Live Source Generator (with timestamp overlay)
        |
    Packager
   /         \
HLS path    MoQ path
   |              |
HTTP origin   Fragment Watcher/Publisher
   |              |
HLS Player    MoQ Relay
                  |
             MoQ Player
```

**Key constraint:** One shared upstream media source. Encoded media must be identical across HLS and MoQ paths.

## Build Principles

- Keep the encoded media identical across HLS and MoQ paths
- Ship in small, testable increments — each phase must end in a demonstrable output
- Prefer simple local tooling over elegance
- Avoid introducing multiple moving parts at once
- Do not add ABR until the single-rendition path is stable
- Instrument before optimizing
- Prefer Docker Compose for local orchestration
- Prefer explicit environment variables over hidden defaults
- Add logging for all critical transitions

## Development Conventions

### General Rules
- Do not refactor unrelated code when implementing a feature or fix
- Keep `README.md` updated at the end of each phase
- Add scripts for setup, run, test, and demo under `/scripts`
- When blocked, leave a short `BLOCKERS.md` note with the exact issue and next step
- Do not mark a phase complete unless its acceptance test passes

### Environment Variables
- Use explicit environment variables — no hidden defaults
- Document all variables in the relevant component's README or `.env.example`

### Logging
- Add structured logging for all critical state transitions (stream start/stop, relay connect/disconnect, impairment apply/remove, player events)

### Scripts
Each component should have scripts covering:
- `setup` — install dependencies, pull images
- `run` — start the component
- `test` — run component-level tests
- `demo` — end-to-end demo entry point

## Deliverables Per Phase

For each completed phase, produce:
1. Working code
2. Updated `README.md` with current phase status
3. Runnable scripts
4. Verification notes (what was tested, how)
5. Short summary: what works and what does not

## Success Criteria

The project is successful when:
1. HLS and MoQ both play the same live source
2. Source timestamp is visible in both players
3. Impairment profiles can be triggered on demand
4. Playback differences are visible and measurable
5. Metrics reflect what is observed visually
6. Each phase leaves the repo in a runnable state

## License

Apache 2.0 — see `LICENSE`.
