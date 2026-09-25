"""
FastAPI application entrypoint. Run locally with:

    uvicorn app.main:app --reload --port 8000

(from inside backend/, with the virtualenv from requirements.txt active).
See backend/README.md for the full setup guide.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.deps import rate_limit_dep
from app.routers import channels, health, scrape, search, settings as settings_router, system, videos
from app.scheduler import start_scheduler, stop_scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def _warn_about_missing_secrets(settings) -> None:
    """
    Every one of these has a graceful, already-correct failure mode at
    request time — a scrape/search returns a clean 503/401 rather than a
    crash (see app/deps.py's require_scrape_api_key and the youtube_api_key
    checks in app/routers/scrape.py and app/routers/search.py). The problem
    this closes isn't correctness, it's visibility: a forgotten secret in
    Render's dashboard currently surfaces only the first time something
    actually tries to use it — which, for SCRAPE_TRIGGER_API_KEY, could be
    hours later when the nightly GitHub Actions cron fires and silently
    fails. Logging it once at boot means it shows up immediately in the
    same place a deploy's other startup logs already do, instead of only
    being discoverable by noticing a scrape never ran.
    """
    if not settings.youtube_api_key:
        logger.warning(
            "YOUTUBE_API_KEY is not set — scraping and topic search will return a clean error until it's configured."
        )
    if not settings.apify_api_token:
        logger.warning("APIFY_API_TOKEN is not set — Instagram scraping will return a clean error until it's configured.")
    if not settings.scrape_trigger_api_key:
        logger.warning(
            "SCRAPE_TRIGGER_API_KEY is not set — POST /api/scrape/run and /api/scrape/check-velocity "
            "(the scheduled GitHub Actions cron calls) will fail closed with a 503 until it's configured."
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    _warn_about_missing_secrets(settings)
    start_scheduler(settings)
    yield
    stop_scheduler()


app = FastAPI(
    title="Competitor Video Intelligence API",
    description="Backend for the TW-DASH competitor dashboard: tracked channels, scraped videos, and overperformance analytics.",
    version="1.0.0",
    lifespan=lifespan,
    # A blanket per-IP rate limit on every route (see app/deps.py's
    # rate_limit_dep and app/rate_limit.py) — applied at the app level
    # rather than per-router so nothing added later can accidentally skip
    # it. /healthz is exempted inside the dependency itself (Render/uptime
    # monitors poll it on their own schedule, not a client this is meant to
    # guard against).
    dependencies=[Depends(rate_limit_dep)],
)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    # No cookie/session auth exists anywhere in this app (see PRODUCTION_
    # ROADMAP.md's Phase 2 — auth isn't built yet) and the frontend's fetch
    # wrapper (src/lib/api.ts) never sets `credentials`, so no request this
    # app makes or receives ever needs cookies/Authorization carried cross-
    # origin. allow_credentials=True was dead configuration that only
    # widened what a misconfigured CORS_ORIGINS (e.g. accidentally listing
    # an untrusted origin) could get away with — turning it off costs
    # nothing today and removes that risk if CORS_ORIGINS is ever loosened.
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Transparent to every client (fetch/browsers negotiate and decompress this
# automatically via Accept-Encoding/Content-Encoding — no frontend change
# needed) and meaningful here specifically because the two heaviest
# responses are JSON arrays of near-identical objects: GET /api/videos can
# return up to 2000 video records and GET /api/channels one per tracked
# channel, both highly repetitive (the same field names and similar string
# values over and over), which is exactly what gzip compresses well.
# minimum_size skips compressing tiny responses (health checks, single-
# object PATCH results) where gzip's own overhead isn't worth paying.
app.add_middleware(GZipMiddleware, minimum_size=500)


@app.middleware("http")
async def security_headers(request, call_next):
    """
    A handful of response headers with no functional cost — none of them
    change what any endpoint returns, only how a browser is allowed to use
    it — that this API previously sent none of:

    - X-Content-Type-Options: nosniff — stops a browser from ever guessing
      a response is something other than the Content-Type this API already
      declares (every response here is application/json).
    - X-Frame-Options / frame-ancestors — this API's JSON responses have no
      legitimate reason to be framed by anyone; blocks clickjacking-style
      embedding.
    - Referrer-Policy: strict-origin-when-cross-origin — avoids leaking full
      request URLs (which can carry filter values as query params) to a
      third party via the Referer header on any outbound link.
    - Permissions-Policy — opts this API's origin out of browser features
      it never uses.
    - Strict-Transport-Security — every documented deployment path (Render,
      or nginx+Caddy per PRODUCTION_ROADMAP.md) serves this over HTTPS only;
      browsers ignore this header entirely when a response arrives over
      plain HTTP (e.g. local `uvicorn --reload` dev), so it's a no-op there
      rather than a way to break local development.
    """
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"
    response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Every route that catches its own expected failure modes already turns
    them into a clean HTTPException with a safe message (see, e.g.,
    app/error_safety.py's safe_error_message for the scrape/search paths).
    This is the backstop for anything that *isn't* expected — a genuine bug,
    a DB error a route didn't anticipate, and so on — which would otherwise
    reach Starlette's own default handler. That default handler already
    doesn't leak a traceback to the client (FastAPI runs with debug=False
    here), but it returns a bare "Internal Server Error" *plain-text* body,
    inconsistent with every other error response in this API (all
    ``{"detail": ...}`` JSON) and something the frontend's fetch wrapper
    (src/lib/api.ts) has to fall back to a generic message for rather than
    reading a real one. This handler unifies that: log the real exception
    server-side (with a traceback, for debugging) and return a fixed,
    generic message — deliberately not ``str(exc)``, since an unanticipated
    exception (unlike the ones safe_error_message specifically targets)
    hasn't been vetted for what it might embed (a raw SQL fragment, an
    internal path, etc.).
    """
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Something went wrong on the server. Please try again."})


app.include_router(health.router)
app.include_router(channels.router)
app.include_router(videos.router)
app.include_router(scrape.router)
app.include_router(system.router)
app.include_router(settings_router.router)
app.include_router(search.router)


@app.get("/")
def root() -> dict:
    return {"service": "competitor-dashboard-api", "docs": "/docs"}
