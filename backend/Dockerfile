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

# Runs as an unprivileged user rather than the container default of root —
# this process only ever needs to read its own already-copied-in code and
# talk to the network (Postgres, YouTube, Apify), never to write to the
# filesystem or bind a privileged (<1024) port, so root privileges buy it
# nothing and only widen the blast radius of a future RCE-class bug in this
# app or one of its dependencies. chown up front, before switching, since
# USER must come after any RUN/COPY that still needs root.
RUN groupadd --system app && useradd --system --gid app --no-create-home app \
    && chown -R app:app /app
USER app

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
