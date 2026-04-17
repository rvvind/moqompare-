FROM alpine:3.19

# ffmpeg + fonts for source labels and UTC overlay
RUN apk add --no-cache curl ffmpeg ttf-dejavu

COPY packager.sh /usr/local/bin/angle-packager.sh
RUN chmod +x /usr/local/bin/angle-packager.sh

ENTRYPOINT ["/usr/local/bin/angle-packager.sh"]
