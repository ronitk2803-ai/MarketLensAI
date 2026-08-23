FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY . .
RUN uv sync --frozen --no-dev


FROM python:3.12-slim AS runtime

RUN useradd --create-home --uid 1000 mlai
WORKDIR /app

COPY --from=builder --chown=mlai:mlai /app /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

USER mlai

EXPOSE 8000

# Runs pending Alembic migrations, then starts the API. Fine for a
# single-instance MVP deploy (Render/Fly/Railway) where this container is
# both the only writer and the only thing that runs migrations; a
# multi-instance deploy would need migrations moved to a separate release
# step so N replicas don't race to apply them concurrently.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
