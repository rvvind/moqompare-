#!/bin/sh
# ─────────────────────────────────────────────
#  packager.sh — HLS packager
#
#  Reads MPEG-TS from the source FIFO and muxes
#  it into a rolling fMP4 HLS playlist.
#
#  Outputs to /media/hls/:
#    stream.m3u8   rolling manifest
#    init.mp4      fMP4 init segment (written once)
#    seg_NNNNN.m4s media segments
# ─────────────────────────────────────────────
set -e

PIPE="/media/source.pipe"
HLS_DIR="/media/hls"
SEG_DUR="${HLS_SEGMENT_DURATION:-2}"
LIST_SIZE="${HLS_LIST_SIZE:-5}"

mkdir -p "${HLS_DIR}"

# ── Write master playlist (required by moq-cli hls ingest) ───────────────
# moq-cli expects a master playlist with #EXT-X-STREAM-INF variants.
# We write it once; the media playlist (stream.m3u8) is the sole rendition.
BITRATE="${SOURCE_BITRATE:-4000k}"
BITRATE_BPS=$(echo "${BITRATE}" | sed 's/k$/000/;s/M$/000000/')
RESOLUTION="${SOURCE_RESOLUTION:-1920x1080}"
cat > "${HLS_DIR}/master.m3u8" << EOF
#EXTM3U
#EXT-X-VERSION:6
#EXT-X-INDEPENDENT-SEGMENTS
#EXT-X-STREAM-INF:BANDWIDTH=${BITRATE_BPS},RESOLUTION=${RESOLUTION},CODECS="avc1.42c028"
stream.m3u8
EOF
echo "[packager] master playlist written → ${HLS_DIR}/master.m3u8"

# ── Wait for source FIFO ──────────────────────────────────────────────────
echo "[packager] Waiting for source FIFO at ${PIPE}..."
while [ ! -p "${PIPE}" ]; do
  sleep 0.5
done
echo "[packager] Source FIFO ready — starting HLS packaging"
echo "[packager] segment_duration=${SEG_DUR}s  list_size=${LIST_SIZE}  output=${HLS_DIR}"

while true; do
  ffmpeg \
    -hide_banner \
    -loglevel warning \
    -fflags nobuffer \
    -analyzeduration 1000000 \
    -probesize 1000000 \
    -i "${PIPE}" \
    -c:v copy \
    -f hls \
    -hls_time "${SEG_DUR}" \
    -hls_list_size "${LIST_SIZE}" \
    -hls_flags delete_segments+append_list+independent_segments \
    -hls_segment_type fmp4 \
    -hls_fmp4_init_filename "init.mp4" \
    -hls_segment_filename "${HLS_DIR}/seg_%05d.m4s" \
    "${HLS_DIR}/stream.m3u8" 2>&1 | sed 's/^/[packager] /'

  echo "[packager] FFmpeg exited — waiting for FIFO and restarting..."
  while [ ! -p "${PIPE}" ]; do
    sleep 0.5
  done
  sleep 1
done
