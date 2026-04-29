# Telegram bridge — minimal Cloud Run container.
# Per DESIGN.v2.md §10.6.

FROM python:3.12-slim

# Install uv for fast dep install + reproducibility from uv.lock.
RUN pip install --no-cache-dir uv==0.8.13

WORKDIR /code

# Cache deps separately from the source so a pyproject change doesn't
# bust the source layer too.
COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen || uv sync

COPY main.py ./

EXPOSE 8080

# Cloud Run sets $PORT; honor it. uvicorn binds 0.0.0.0 because Cloud Run
# routes traffic to the container interface.
CMD ["sh", "-c", "uv run uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"]
