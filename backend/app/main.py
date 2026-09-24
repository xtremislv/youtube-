"""
FastAPI application entrypoint. Run locally with:

    uvicorn app.main:app --reload --port 8000

(from inside backend/, with the virtualenv from requirements.txt active).
See backend/README.md for the full setup guide.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app.config import get_settings
from app.routers import channels, health, scrape, search, settings as settings_router, system, videos
from app.scheduler import start_scheduler, stop_scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    start_scheduler(settings)
    yield
    stop_scheduler()


app = FastAPI(
    title="Competitor Video Intelligence API",
    description="Backend for the TW-DASH competitor dashboard: tracked channels, scraped videos, and overperformance analytics.",
    version="1.0.0",
    lifespan=lifespan,
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
