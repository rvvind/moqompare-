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
SEG_DUR="${COMPARE_HLS_SEGMENT_DURATION:-${HLS_SEGMENT_DURATION:-2}}"
LIST_SIZE="${COMPARE_HLS_LIST_SIZE:-${HLS_LIST_SIZE:-5}}"
SOURCE_FPS="${SOURCE_FPS:-30}"
GOP_SIZE=$(
  awk -v seg="${SEG_DUR}" -v fps="${SOURCE_FPS}" '
    BEGIN {
      value = seg * fps
      if (value < 1) value = 1
      if (value == int(value)) {
        printf "%d", value
      } else {
        printf "%d", int(value + 0.5)
      }
    }
  '
)

# High rendition: mirrors the source
HI_BITRATE="${SOURCE_BITRATE:-4000k}"
HI_RESOLUTION="${SOURCE_RESOLUTION:-1920x1080}"

# Low rendition: independently tunable
LO_BITRATE="${ABR_LO_BITRATE:-500k}"
LO_RESOLUTION="${ABR_LO_RESOLUTION:-640x360}"

mkdir -p "${HLS_DIR}"

# ── HLS state management ──────────────────────────────────────────────────
next_start_number() {
  LAST_NUM=$(
    find "${HLS_DIR}" -maxdepth 1 -type f -name '*.m4s' -print 2>/dev/null \
      | sed -n 's|.*_\([0-9][0-9]*\)\.m4s$|\1|p' \
      | awk '
          {
            sub(/^0+/, "", $0)
            if ($0 == "") $0 = 0
            if ($0 > max) max = $0
          }
          END { print max + 0 }
        '
  )

  if [ -n "${LAST_NUM}" ]; then
    echo $((LAST_NUM + 1))
  else
    echo 0
  fi
}

clear_hls_state() {
  STALE_FILES=$(
    find "${HLS_DIR}" -maxdepth 1 -type f \
      \( -name '*.m3u8' -o -name '*.mp4' -o -name '*.m4s' -o -name '*.cmfv' \) \
      | wc -l | tr -d ' '
  )

  find "${HLS_DIR}" -maxdepth 1 -type f \
    \( -name '*.m3u8' -o -name '*.mp4' -o -name '*.m4s' -o -name '*.cmfv' \) \
    -delete

  echo "[packager] cleared ${STALE_FILES} stale HLS file(s)"
}

# ── Write master playlist ─────────────────────────────────────────────────
write_master() {
  HI_BPS=$(echo "${HI_BITRATE}" | sed 's/[kK]$/000/;s/[mM]$/000000/')
  LO_BPS=$(echo "${LO_BITRATE}" | sed 's/[kK]$/000/;s/[mM]$/000000/')

  # ABR master playlist (used by HLS player)
  cat > "${HLS_DIR}/master.m3u8" << EOF
#EXTM3U
#EXT-X-VERSION:6
#EXT-X-INDEPENDENT-SEGMENTS

#EXT-X-STREAM-INF:BANDWIDTH=${HI_BPS},RESOLUTION=${HI_RESOLUTION},CODECS="avc1.42c028",NAME="high"
stream_hi.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=${LO_BPS},RESOLUTION=${LO_RESOLUTION},CODECS="avc1.42c028",NAME="low"
stream_lo.m3u8
EOF

  # Single-rendition masters for MoQ publishers (moq-cli requires a master
  # playlist with EXT-X-STREAM-INF; it cannot read media playlists directly)
  cat > "${HLS_DIR}/master_hi.m3u8" << EOF
#EXTM3U
#EXT-X-VERSION:6
#EXT-X-INDEPENDENT-SEGMENTS

#EXT-X-STREAM-INF:BANDWIDTH=${HI_BPS},RESOLUTION=${HI_RESOLUTION},CODECS="avc1.42c028",NAME="high"
stream_hi.m3u8
EOF

  cat > "${HLS_DIR}/master_lo.m3u8" << EOF
#EXTM3U
#EXT-X-VERSION:6
#EXT-X-INDEPENDENT-SEGMENTS

#EXT-X-STREAM-INF:BANDWIDTH=${LO_BPS},RESOLUTION=${LO_RESOLUTION},CODECS="avc1.42c028",NAME="low"
stream_lo.m3u8
EOF

  echo "[packager] master playlists written  hi=${HI_RESOLUTION}@${HI_BITRATE}  lo=${LO_RESOLUTION}@${LO_BITRATE}"
}

HLS_FLAGS="delete_segments+append_list+independent_segments"
LO_W=$(echo "${LO_RESOLUTION}" | cut -dx -f1)
LO_H=$(echo "${LO_RESOLUTION}" | cut -dx -f2)

while true; do
  START_NUMBER=$(next_start_number)
  clear_hls_state

  # ── Wait for source FIFO ────────────────────────────────────────────────
  echo "[packager] waiting for source FIFO at ${PIPE}..."
  while [ ! -p "${PIPE}" ]; do sleep 0.5; done

  write_master
  echo "[packager] FIFO ready — starting dual-rendition HLS packaging"
  echo "[packager] seg=${SEG_DUR}s  list=${LIST_SIZE}  gop=${GOP_SIZE}  start=${START_NUMBER}"

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
    -g "${GOP_SIZE}" -keyint_min "${GOP_SIZE}" -sc_threshold 0 \
    -f hls \
    -hls_time "${SEG_DUR}" -hls_list_size "${LIST_SIZE}" \
    -hls_flags "${HLS_FLAGS}" \
    -start_number "${START_NUMBER}" \
    -hls_segment_type fmp4 \
    -hls_fmp4_init_filename "init_hi.mp4" \
    -hls_segment_filename "${HLS_DIR}/seg_hi_%05d.m4s" \
    "${HLS_DIR}/stream_hi.m3u8" \
    \
    -map "[vlo_s]" \
    -c:v libx264 -b:v "${LO_BITRATE}" \
    -preset ultrafast -tune zerolatency -profile:v baseline \
    -g "${GOP_SIZE}" -keyint_min "${GOP_SIZE}" -sc_threshold 0 \
    -f hls \
    -hls_time "${SEG_DUR}" -hls_list_size "${LIST_SIZE}" \
    -hls_flags "${HLS_FLAGS}" \
    -start_number "${START_NUMBER}" \
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
