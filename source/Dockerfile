FROM alpine:3.19

# ffmpeg with libx264 + freetype (drawtext), dejavu fonts for the overlay
RUN apk add --no-cache ffmpeg ttf-dejavu

COPY source.sh /usr/local/bin/source.sh
RUN chmod +x /usr/local/bin/source.sh

ENTRYPOINT ["/usr/local/bin/source.sh"]
