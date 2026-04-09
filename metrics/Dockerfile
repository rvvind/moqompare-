FROM alpine:3.19
RUN apk add --no-cache python3
COPY collector.py /collector.py
EXPOSE 9090
HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
  CMD wget -q -O- http://127.0.0.1:9090/health | grep -q ok
CMD ["python3", "/collector.py"]
