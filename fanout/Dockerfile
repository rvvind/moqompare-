# Build moq-relay at the same tag as relay so protocol versions match.
# Each fanout container runs N moq-relay cluster nodes that connect to the
# main relay and subscribe to its announcement namespace, simulating N
# concurrent subscribers without a dedicated moq-cli watch command.
FROM rust:1-alpine AS builder

RUN apk add --no-cache musl-dev git

ARG MOQ_VERSION=moq-relay-v0.10.17

RUN git clone --depth 1 --branch "${MOQ_VERSION}" \
      https://github.com/moq-dev/moq /src

WORKDIR /src

RUN cargo build --release \
      --package moq-relay \
      --no-default-features \
      --features quinn,websocket

FROM alpine:3.19
RUN apk add --no-cache ca-certificates wget
COPY --from=builder /src/target/release/moq-relay /usr/local/bin/moq-relay
COPY fanout.sh /fanout.sh
RUN chmod +x /fanout.sh
ENTRYPOINT ["/fanout.sh"]
