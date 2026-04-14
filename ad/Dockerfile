# ── Stage 1: build moq-cli ────────────────────────────────────────────────────
# Must match the relay version exactly (same protocol version).
FROM rust:1-alpine AS moq-builder

RUN apk add --no-cache musl-dev git

ARG MOQ_VERSION=moq-relay-v0.10.17

RUN git clone --depth 1 --branch "${MOQ_VERSION}" \
      https://github.com/moq-dev/moq /src

WORKDIR /src

RUN cargo build --release \
      --package moq-cli \
      --no-default-features \
      --features quinn,websocket

# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM python:3.12-alpine

RUN apk add --no-cache \
      ffmpeg \
      ca-certificates

COPY --from=moq-builder /src/target/release/moq-cli /usr/local/bin/moq-cli

WORKDIR /app
COPY server.py .

EXPOSE 8092

CMD ["python3", "-u", "server.py"]
