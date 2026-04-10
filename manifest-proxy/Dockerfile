FROM python:3.12-alpine
WORKDIR /app
COPY manifest_proxy.py .
ENV ORIGIN_URL=http://origin
ENV MANIFEST_PROXY_PORT=8091
EXPOSE 8091
CMD ["python3", "-u", "manifest_proxy.py"]
