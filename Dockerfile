FROM node:24-alpine AS frontend-builder
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM ghcr.io/astral-sh/uv:0.11.3 AS uv

FROM python:3.12-slim AS application
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    BSA_STATIC_FILES_PATH=/app/static
WORKDIR /app
COPY --from=uv /uv /uvx /bin/
COPY pyproject.toml uv.lock README.md ./
COPY src/ ./src/
RUN uv sync --locked --no-dev --no-editable
RUN uv run playwright install --with-deps chromium
COPY alembic.ini ./
COPY migrations/ ./migrations/
COPY --from=frontend-builder /build/frontend/dist/ ./static/
RUN groupadd --system --gid 10001 bsa \
    && useradd --system --uid 10001 --gid bsa --home-dir /app bsa \
    && mkdir -p /var/lib/bank-statement-assistant/statements \
    && chown -R bsa:bsa /app /ms-playwright /var/lib/bank-statement-assistant
USER 10001:10001
EXPOSE 8000
CMD ["bsa-api"]
