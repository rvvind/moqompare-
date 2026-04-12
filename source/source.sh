#!/bin/sh
# ─────────────────────────────────────────────
#  source.sh — live video source generator
#
#  MODE 1 (default): if /videos/ contains any
#    *.mp4 files they are looped end-to-end
#    continuously as the live source.
#
#  MODE 2 (fallback): synthetic testsrc2 when
#    no video files are present.
#
#  In both modes a visible UTC timestamp overlay
#  is burned in and the stream is written as
#  MPEG-TS into a named pipe for the packager.
# ─────────────────────────────────────────────
set -e

RESOLUTION="${SOURCE_RESOLUTION:-1920x1080}"
FPS="${SOURCE_FPS:-30}"
BITRATE="${SOURCE_BITRATE:-4000k}"
PIPE="/media/source.pipe"
VIDEOS_DIR="${VIDEOS_DIR:-/videos}"
FONTFILE="/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"

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

# ── Build concat playlist if video files are present ──────────────────────
PLAYLIST="/tmp/source_playlist.txt"
build_playlist() {
  # Collect mp4 files, sorted by name for deterministic order
  FILES=$(find "$VIDEOS_DIR" -maxdepth 1 -name "*.mp4" 2>/dev/null | sort)
  if [ -z "$FILES" ]; then
    return 1   # no files
  fi
  # Pre-expand the playlist 999 times so FFmpeg runs for hours before the
  # outer loop ever needs to restart.  The concat demuxer advances from one
  # entry to the next with no seek/restart gap, avoiding the FIFO starvation
  # that -stream_loop -1 causes when it internally reseeks the whole list.
  LOOP_REPS=999
  printf "" > "$PLAYLIST"
  i=0
  while [ $i -lt $LOOP_REPS ]; do
    for f in $FILES; do
      printf "file '%s'\n" "$f" >> "$PLAYLIST"
    done
    i=$((i + 1))
  done
  FILE_COUNT=$(echo "$FILES" | wc -l | tr -d ' ')
  echo "[source] playlist: ${FILE_COUNT} file(s) × ${LOOP_REPS} reps = $(wc -l < "$PLAYLIST" | tr -d ' ') entries"
  return 0
}

# ── Named pipe lifecycle ──────────────────────────────────────────────────
while true; do
  rm -f "$PIPE"
  mkfifo "$PIPE"
  echo "[source] FIFO ready at ${PIPE}"

  if build_playlist; then
    # ── Mode 1: real video files ──────────────────────────────────────────
    echo "[source] mode=video  files=$(wc -l < "$PLAYLIST")  bitrate=${BITRATE}  keyint=${KEYINT}"

    ffmpeg \
      -hide_banner \
      -loglevel warning \
      -re \
      -f concat \
      -safe 0 \
      -i "$PLAYLIST" \
      -vf "scale=${RESOLUTION},fps=${FPS},\
drawtext=fontfile=${FONTFILE}:\
text='SRC %{localtime\:%T} UTC':\
fontsize=48:fontcolor=white:\
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
      -an \
      -f mpegts \
      -y \
      "${PIPE}" 2>&1 | sed 's/^/[source] /'

  else
    # ── Mode 2: synthetic test source ────────────────────────────────────
    echo "[source] mode=testsrc2 (no videos found in ${VIDEOS_DIR})"
    echo "[source] stream: ${RESOLUTION} @ ${FPS}fps  bitrate=${BITRATE}  keyint=${KEYINT}"

    ffmpeg \
      -hide_banner \
      -loglevel warning \
      -re \
      -f lavfi \
      -i "testsrc2=size=${RESOLUTION}:rate=${FPS}" \
      -vf "drawtext=fontfile=${FONTFILE}:\
text='SRC %{localtime\:%T} UTC':\
fontsize=48:fontcolor=white:\
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
  fi

  echo "[source] FFmpeg exited — restarting..."
done
