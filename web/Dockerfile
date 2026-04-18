# ── Stage 1: download hls.js ──────────────────────────────────────────────
FROM alpine:3.19 AS fetcher

ARG HLS_JS_VERSION=1.5.15

RUN apk add --no-cache wget && \
    wget -q -O /hls.min.js \
      "https://cdn.jsdelivr.net/npm/hls.js@${HLS_JS_VERSION}/dist/hls.min.js" && \
    echo "hls.js ${HLS_JS_VERSION} downloaded ($(wc -c < /hls.min.js) bytes)"

# ── Stage 2: bundle MoQ watch player ─────────────────────────────────────
FROM node:20-alpine AS moq-builder

WORKDIR /build

COPY package.json ./
RUN npm install --silent

COPY moq-player.js build.mjs ./
RUN npm run build && \
    echo "hang.js bundled ($(wc -c < static/hang.js) bytes)"

# ── Stage 3: nginx serving static files ──────────────────────────────────
FROM nginx:alpine

COPY --from=fetcher     /hls.min.js              /usr/share/nginx/html/hls.min.js
COPY --from=moq-builder /build/static/hang.js    /usr/share/nginx/html/hang.js
COPY static/                                      /usr/share/nginx/html/

# nginx config is volume-mounted at runtime (see docker-compose.yml)
