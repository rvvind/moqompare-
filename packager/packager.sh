#!/bin/sh
# ─────────────────────────────────────────────
#  packager.sh — HLS packager (dual-rendition)
#
#  Reads MPEG-TS from the source FIFO and muxes
#  it into two fMP4 HLS renditions:
#
#    stream_hi.m3u8  — source resolution & bitrate
#    stream_lo.m3u8  — 640×360 @ ABR_LO_BITRATE
#
#  Outputs to /media/hls/:
#    master.m3u8         ABR master playlist
#    init_hi.mp4         hi-rendition fMP4 init
#    init_lo.mp4         lo-rendition fMP4 init
#    seg_hi_NNNNN.m4s    hi-rendition segments
#    seg_lo_NNNNN.m4s    lo-rendition segments
# ─────────────────────────────────────────────
set -e

PIPE="/media/source.pipe"
HLS_DIR="/media/hls"
SEG_DUR="${HLS_SEGMENT_DURATION:-2}"
LIST_SIZE="${HLS_LIST_SIZE:-5}"

# High rendition: mirrors the source
HI_BITRATE="${SOURCE_BITRATE:-4000k}"
HI_RESOLUTION="${SOURCE_RESOLUTION:-1920x1080}"

# Low rendition: independently tunable
LO_BITRATE="${ABR_LO_BITRATE:-500k}"
LO_RESOLUTION="${ABR_LO_RESOLUTION:-640x360}"

mkdir -p "${HLS_DIR}"

# ── Write master playlist ─────────────────────────────────────────────────
write_master() {
  HI_BPS=$(echo "${HI_BITRATE}" | sed 's/[kK]$/000/;s/[mM]$/000000/')
  LO_BPS=$(echo "${LO_BITRATE}" | sed 's/[kK]$/000/;s/[mM]$/000000/')
  cat > "${HLS_DIR}/master.m3u8" << EOF
#EXTM3U
#EXT-X-VERSION:6
#EXT-X-INDEPENDENT-SEGMENTS

#EXT-X-STREAM-INF:BANDWIDTH=${HI_BPS},RESOLUTION=${HI_RESOLUTION},CODECS="avc1.42c028",NAME="high"
stream_hi.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=${LO_BPS},RESOLUTION=${LO_RESOLUTION},CODECS="avc1.42c028",NAME="low"
stream_lo.m3u8
EOF
  echo "[packager] master.m3u8 written  hi=${HI_RESOLUTION}@${HI_BITRATE}  lo=${LO_RESOLUTION}@${LO_BITRATE}"
}

write_master

# ── Wait for source FIFO ──────────────────────────────────────────────────
echo "[packager] waiting for source FIFO at ${PIPE}..."
while [ ! -p "${PIPE}" ]; do sleep 0.5; done
echo "[packager] FIFO ready — starting dual-rendition HLS packaging"
echo "[packager] seg=${SEG_DUR}s  list=${LIST_SIZE}"

HLS_FLAGS="delete_segments+append_list+independent_segments"
LO_W=$(echo "${LO_RESOLUTION}" | cut -dx -f1)
LO_H=$(echo "${LO_RESOLUTION}" | cut -dx -f2)

while true; do
  ffmpeg \
    -hide_banner \
    -loglevel warning \
    -fflags nobuffer \
    -analyzeduration 1000000 \
    -probesize 1000000 \
    -i "${PIPE}" \
    -filter_complex "[0:v]split=2[vhi][vlo];[vlo]scale=${LO_W}:${LO_H}[vlo_s]" \
    \
    -map "[vhi]" \
    -c:v libx264 -b:v "${HI_BITRATE}" \
    -preset ultrafast -tune zerolatency -profile:v baseline \
    -f hls \
    -hls_time "${SEG_DUR}" -hls_list_size "${LIST_SIZE}" \
    -hls_flags "${HLS_FLAGS}" \
    -hls_segment_type fmp4 \
    -hls_fmp4_init_filename "init_hi.mp4" \
    -hls_segment_filename "${HLS_DIR}/seg_hi_%05d.m4s" \
    "${HLS_DIR}/stream_hi.m3u8" \
    \
    -map "[vlo_s]" \
    -c:v libx264 -b:v "${LO_BITRATE}" \
    -preset ultrafast -tune zerolatency -profile:v baseline \
    -f hls \
    -hls_time "${SEG_DUR}" -hls_list_size "${LIST_SIZE}" \
    -hls_flags "${HLS_FLAGS}" \
    -hls_segment_type fmp4 \
    -hls_fmp4_init_filename "init_lo.mp4" \
    -hls_segment_filename "${HLS_DIR}/seg_lo_%05d.m4s" \
    "${HLS_DIR}/stream_lo.m3u8" \
    2>&1 | sed 's/^/[packager] /'

  echo "[packager] FFmpeg exited — rewriting master.m3u8 and restarting..."
  write_master
  while [ ! -p "${PIPE}" ]; do sleep 0.5; done
  sleep 1
done
