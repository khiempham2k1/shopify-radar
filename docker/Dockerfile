# Backend image for both the API and the worker.
FROM python:3.12-slim

# ffmpeg: cut audio for Groq Whisper. deno: JS runtime yt-dlp needs for YouTube
# (works without extra yt-dlp config, unlike Node). git: install pinned CLIs.
COPY --from=denoland/deno:bin-2.4.5 /deno /usr/local/bin/deno
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml alembic.ini ./
COPY radar ./radar
COPY api ./api
COPY migrations ./migrations
RUN pip install --no-cache-dir -e . \
    # Free collection tools chosen by Agent Reach, pinned (see docs/PLAN.md).
    && pip install --no-cache-dir \
        "twitter-cli @ git+https://github.com/jackwener/twitter-cli.git@7c634e0d396b1e7af9f63315b414925fe4f29ae7" \
        "rdt-cli @ git+https://github.com/public-clis/rdt-cli.git@5e4fb3720d5c174e976cd425ccc3b879d52cac66" \
        "agent-reach @ git+https://github.com/Panniantong/agent-reach.git@94f06c1969dfc1834001269d79d3ad0972d9dee6"
COPY config ./config

ENV RADAR_CONFIG_DIR=/app/config \
    RADAR_WORK_DIR=/data/work \
    PYTHONUNBUFFERED=1

EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
