# Build moq-cli at the same tag as relay/publisher so protocol versions match.
FROM rust:1-alpine AS builder

RUN apk add --no-cache musl-dev git

ARG MOQ_VERSION=moq-relay-v0.10.17

RUN git clone --depth 1 --branch "${MOQ_VERSION}" \
      https://github.com/moq-dev/moq /src

WORKDIR /src

RUN cargo build --release \
      --package moq-cli \
      --no-default-features \
      --features quinn,websocket

FROM alpine:3.19
RUN apk add --no-cache ca-certificates
COPY --from=builder /src/target/release/moq-cli /usr/local/bin/moq-cli
COPY fanout.sh /fanout.sh
RUN chmod +x /fanout.sh
ENTRYPOINT ["/fanout.sh"]
