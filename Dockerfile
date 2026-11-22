FROM ghcr.io/astral-sh/uv:0.8.11-python3.12-bookworm-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
ARG SOURCE_COMMIT=unknown
ENV APP_BUILD_SHA=$SOURCE_COMMIT
WORKDIR /srv/oge-trainer
COPY pyproject.toml uv.lock README.md ./
COPY app ./app
COPY atlas ./atlas
COPY migrations ./migrations
COPY scripts/import_part2.py scripts/init_staging.py ./scripts/
RUN uv sync --frozen --no-dev
USER 10001:10001
EXPOSE 8000
CMD ["sh", "-c", "exec .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
