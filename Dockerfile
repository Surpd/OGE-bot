FROM ghcr.io/astral-sh/uv:0.8.11-python3.12-bookworm-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /srv/oge-trainer
COPY pyproject.toml uv.lock README.md ./
COPY app ./app
COPY migrations ./migrations
RUN uv sync --frozen --no-dev
USER 10001:10001
EXPOSE 8000
CMD [".venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
