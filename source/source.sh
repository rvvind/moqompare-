#!/bin/sh
# ─────────────────────────────────────────────
#  source.sh — live video source generator
#
#  Produces a synthetic 1280×720 @ 30 fps test
#  stream with a visible UTC wall-clock overlay
#  and writes it as MPEG-TS into a named pipe
#  that the packager service reads.
# ─────────────────────────────────────────────
set -e

RESOLUTION="${SOURCE_RESOLUTION:-1280x720}"
FPS="${SOURCE_FPS:-30}"
BITRATE="${SOURCE_BITRATE:-1500k}"
PIPE="/media/source.pipe"
FONTFILE="/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"

# keyframe every segment_duration seconds (default 2 s)
SEG_DUR="${HLS_SEGMENT_DURATION:-2}"
KEYINT=$(( FPS * SEG_DUR ))

mkdir -p /media

# ── Font sanity check ─────────────────────────────────────────────────────
if [ ! -f "$FONTFILE" ]; then
  FONTFILE=$(find /usr/share/fonts -name "*.ttf" 2>/dev/null | head -1)
  echo "[source] default font not found, using: ${FONTFILE:-NONE}"
  if [ -z "$FONTFILE" ]; then
    echo "[source] ERROR: no TTF font found — install ttf-dejavu in the image"
    exit 1
  fi
fi

# ── Named pipe lifecycle ──────────────────────────────────────────────────
# The packager opens this pipe for reading.  FFmpeg blocks on the open()
# call until the packager is ready.  On container restart we recreate the
# FIFO so the Docker healthcheck fires again quickly.
while true; do
  rm -f "$PIPE"
  mkfifo "$PIPE"
  echo "[source] FIFO ready at ${PIPE}"
  echo "[source] stream: ${RESOLUTION} @ ${FPS}fps  bitrate=${BITRATE}  keyint=${KEYINT}"

  ffmpeg \
    -hide_banner \
    -loglevel warning \
    -re \
    -f lavfi \
    -i "testsrc2=size=${RESOLUTION}:rate=${FPS}" \
    -vf "drawtext=fontfile=${FONTFILE}:\
text='SRC %{localtime\:%T} UTC':\
fontsize=42:fontcolor=white:\
box=1:boxcolor=black@0.65:\
x=20:y=20" \
    -c:v libx264 \
    -preset ultrafast \
    -tune zerolatency \
    -profile:v baseline \
    -g "${KEYINT}" \
    -keyint_min "${KEYINT}" \
    -sc_threshold 0 \
    -b:v "${BITRATE}" \
    -f mpegts \
    -y \
    "${PIPE}" 2>&1 | sed 's/^/[source] /'

  echo "[source] FFmpeg exited — restarting in 2 s..."
  sleep 2
done
