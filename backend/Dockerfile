# Production image for the FastAPI backend. Single stage — psycopg[binary]
# ships prebuilt wheels so there's no compiler toolchain to keep out of the
# final image, and PIP_NO_CACHE_DIR below already stops pip from caching
# wheels on disk.
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# psycopg[binary] ships its own libpq, so no build-essential/libpq-dev needed.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# Applies any pending Alembic migrations, then starts the API. Safe to run
# on every container start — a already-up-to-date DB is a no-op.
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
