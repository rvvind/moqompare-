FROM alpine:3.19

# ffmpeg for remuxing MPEG-TS → fMP4 HLS; no encoder needed (copy codec)
RUN apk add --no-cache ffmpeg

COPY packager.sh /usr/local/bin/packager.sh
RUN chmod +x /usr/local/bin/packager.sh

ENTRYPOINT ["/usr/local/bin/packager.sh"]
