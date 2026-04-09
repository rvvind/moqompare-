FROM alpine:3.19
RUN apk add --no-cache iproute2 python3
COPY impair.py /impair.py
EXPOSE 8090
CMD ["python3", "/impair.py"]
