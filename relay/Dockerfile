# ── Stage 1: build moq-relay from source (no jemalloc) ───────────────────
# The published moqdev/moq-relay image is compiled with --features jemalloc,
# which crashes on Docker Desktop / macOS due to kernel profiling unavailability.
# We build from source with only the features we need.
FROM rust:1-alpine AS builder

RUN apk add --no-cache musl-dev git

# Pin to the same release as the moqdev/moq-cli image we use (0.10.17)
ARG MOQ_VERSION=moq-relay-v0.10.17

RUN git clone --depth 1 --branch "${MOQ_VERSION}" \
      https://github.com/moq-dev/moq /src

WORKDIR /src

# Build only moq-relay, without iroh and jemalloc
RUN cargo build --release \
      --package moq-relay \
      --no-default-features \
      --features quinn,websocket

# ── Stage 2: minimal runtime image ───────────────────────────────────────
FROM alpine:3.19

RUN apk add --no-cache ca-certificates

COPY --from=builder /src/target/release/moq-relay /usr/local/bin/moq-relay

ENTRYPOINT ["moq-relay"]
