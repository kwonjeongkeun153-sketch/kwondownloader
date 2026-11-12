FROM node:22-bookworm-slim AS node
FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=10000
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates && rm -rf /var/lib/apt/lists/*
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY web_requirements.txt ./
RUN pip install --no-cache-dir -r web_requirements.txt
COPY web_app.py pocket_api.py README.md WEB_README.md run_web.ps1 ./
COPY templates ./templates
RUN mkdir -p /app/web_downloads/_frame_previews /tmp/pocket-downloads
EXPOSE 10000
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT} --workers 1 --threads 4 --timeout 120 web_app:app"]
