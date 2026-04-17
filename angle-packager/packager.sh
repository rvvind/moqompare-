#!/bin/sh
# ─────────────────────────────────────────────
#  angle-packager.sh — dedicated alternate-angle HLS packager
#
#  Loops a single file from /videos/alt-angles, burns in a source label
#  plus UTC timestamp, and emits a single-rendition fMP4 HLS output:
#
#    master.m3u8  — single-rendition master for moq-cli publish
#    stream.m3u8  — media playlist
#    init.mp4     — fMP4 init segment
#    seg_NNNNN.m4s
# ─────────────────────────────────────────────
set -e

VIDEO_FILE="${ANGLE_VIDEO_FILE:-}"
OUTPUT_DIR="${ANGLE_OUTPUT_DIR:-}"
STREAM_KEY="${ANGLE_STREAM_KEY:-camera}"
ANGLE_LABEL="${ANGLE_LABEL:-Camera}"
STREAM_NAMESPACE="${ANGLE_NAMESPACE:-lab/source/${STREAM_KEY}}"
PLAYBACK_STREAM_NAME="${ANGLE_PLAYBACK_STREAM_NAME:-stream_${STREAM_KEY}}"
REGISTRY_URL="${REGISTRY_URL:-}"
STREAM_SUMMARY="${ANGLE_SUMMARY:-${ANGLE_LABEL} alternate-angle feed}"
STREAM_TAGS="${ANGLE_TAGS:-camera,alt-angle}"
RESOLUTION="${ANGLE_RESOLUTION:-1920x1080}"
FPS="${ANGLE_FPS:-30}"
BITRATE="${ANGLE_BITRATE:-3500k}"
SEG_DUR="${HLS_SEGMENT_DURATION:-2}"
LIST_SIZE="${HLS_LIST_SIZE:-5}"
FONTFILE="/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"
PLAYLIST="/tmp/${STREAM_KEY}_source_playlist.txt"
GOP_SIZE=$(( SEG_DUR * FPS ))
HLS_FLAGS="delete_segments+append_list+independent_segments"
HEARTBEAT_PID=""

if [ -z "${VIDEO_FILE}" ]; then
  echo "[angle-packager:${STREAM_KEY}] ERROR: ANGLE_VIDEO_FILE is required"
  exit 1
fi

if [ ! -f "${VIDEO_FILE}" ]; then
  echo "[angle-packager:${STREAM_KEY}] ERROR: video file not found: ${VIDEO_FILE}"
  exit 1
fi

if [ -z "${OUTPUT_DIR}" ]; then
  echo "[angle-packager:${STREAM_KEY}] ERROR: ANGLE_OUTPUT_DIR is required"
  exit 1
fi

PLAYLIST_URL="http://origin/hls/angles/${STREAM_KEY}/master.m3u8"

register_stream() {
  if [ -z "${REGISTRY_URL}" ]; then
    return 0
  fi

  TAGS_JSON=$(printf '%s' "${STREAM_TAGS}" | awk -F',' '
    BEGIN { printf "[" }
    {
      for (i = 1; i <= NF; i++) {
        gsub(/^[[:space:]]+|[[:space:]]+$/, "", $i)
        if ($i == "") continue
        if (count > 0) printf ","
        gsub(/"/, "\\\"", $i)
        printf "\"%s\"", $i
        count++
      }
    }
    END { printf "]" }
  ')

  PAYLOAD=$(cat <<EOF
{"id":"${STREAM_KEY}","namespace":"${STREAM_NAMESPACE}","label":"${ANGLE_LABEL}","kind":"camera","summary":"${STREAM_SUMMARY}","status":"healthy","previewable":true,"media_ready":true,"derived_from":["${VIDEO_FILE}"],"tags":${TAGS_JSON},"playback":{"protocol":"moq","stream_name":"${PLAYBACK_STREAM_NAME}","latency_ms":2000,"note":"Published from the dedicated ${ANGLE_LABEL} alternate-angle feed."},"republish":{"protocol":"hls","playlist_url":"${PLAYLIST_URL}","note":"Republisher ingests the dedicated ${ANGLE_LABEL} HLS feed for the stable program broadcast."}}
EOF
)

  until curl -fsS \
    -H "Content-Type: application/json" \
    -d "${PAYLOAD}" \
    "${REGISTRY_URL}/api/streams/register" >/dev/null; do
    echo "[angle-packager:${STREAM_KEY}] waiting for registry registration endpoint at ${REGISTRY_URL}"
    sleep 2
  done

  echo "[angle-packager:${STREAM_KEY}] registered stream ${STREAM_KEY} in registry"
}

heartbeat_loop() {
  if [ -z "${REGISTRY_URL}" ]; then
    return 0
  fi

  while true; do
    curl -fsS \
      -H "Content-Type: application/json" \
      -d "{\"id\":\"${STREAM_KEY}\",\"status\":\"healthy\"}" \
      "${REGISTRY_URL}/api/streams/heartbeat" >/dev/null || \
      echo "[angle-packager:${STREAM_KEY}] heartbeat failed"
    sleep 5
  done
}

cleanup() {
  if [ -n "${HEARTBEAT_PID}" ]; then
    kill "${HEARTBEAT_PID}" 2>/dev/null || true
  fi
}

trap cleanup EXIT INT TERM

mkdir -p "${OUTPUT_DIR}"

if [ ! -f "${FONTFILE}" ]; then
  FONTFILE=$(find /usr/share/fonts -name "*.ttf" 2>/dev/null | head -1)
  if [ -z "${FONTFILE}" ]; then
    echo "[angle-packager:${STREAM_KEY}] ERROR: no TTF font found"
    exit 1
  fi
fi

build_playlist() {
  LOOP_REPS=999
  : > "${PLAYLIST}"
  i=0
  while [ "${i}" -lt "${LOOP_REPS}" ]; do
    printf "file '%s'\n" "${VIDEO_FILE}" >> "${PLAYLIST}"
    i=$((i + 1))
  done
}

clear_state() {
  find "${OUTPUT_DIR}" -maxdepth 1 -type f \
    \( -name '*.m3u8' -o -name '*.mp4' -o -name '*.m4s' \) \
    -delete
}

write_master() {
  BANDWIDTH=$(echo "${BITRATE}" | sed 's/[kK]$/000/;s/[mM]$/000000/')
  cat > "${OUTPUT_DIR}/master.m3u8" << EOF
#EXTM3U
#EXT-X-VERSION:6
#EXT-X-INDEPENDENT-SEGMENTS

#EXT-X-STREAM-INF:BANDWIDTH=${BANDWIDTH},RESOLUTION=${RESOLUTION},CODECS="avc1.42c028",NAME="${STREAM_KEY}"
stream.m3u8
EOF
}

build_playlist

echo "[angle-packager:${STREAM_KEY}] source=${VIDEO_FILE}"
echo "[angle-packager:${STREAM_KEY}] out=${OUTPUT_DIR} res=${RESOLUTION} fps=${FPS} bitrate=${BITRATE}"

register_stream
heartbeat_loop &
HEARTBEAT_PID=$!

while true; do
  clear_state
  write_master

  ffmpeg \
    -hide_banner \
    -loglevel warning \
    -re \
    -f concat \
    -safe 0 \
    -i "${PLAYLIST}" \
    -vf "scale=${RESOLUTION},fps=${FPS},\
drawtext=fontfile=${FONTFILE}:\
text='${ANGLE_LABEL}  %{localtime\\:%T} UTC':\
fontsize=48:fontcolor=white:\
box=1:boxcolor=black@0.65:\
x=20:y=20" \
    -c:v libx264 \
    -preset ultrafast \
    -tune zerolatency \
    -profile:v baseline \
    -g "${GOP_SIZE}" \
    -keyint_min "${GOP_SIZE}" \
    -sc_threshold 0 \
    -b:v "${BITRATE}" \
    -an \
    -f hls \
    -hls_time "${SEG_DUR}" \
    -hls_list_size "${LIST_SIZE}" \
    -hls_flags "${HLS_FLAGS}" \
    -start_number 0 \
    -hls_segment_type fmp4 \
    -hls_fmp4_init_filename "init.mp4" \
    -hls_segment_filename "${OUTPUT_DIR}/seg_%05d.m4s" \
    "${OUTPUT_DIR}/stream.m3u8" 2>&1 | sed "s/^/[angle-packager:${STREAM_KEY}] /"

  echo "[angle-packager:${STREAM_KEY}] FFmpeg exited — restarting..."
  sleep 1
done
