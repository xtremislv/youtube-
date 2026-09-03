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

from app.config import get_settings
from app.routers import channels, health, scrape, system, videos
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
    description="Backend for the Vortex.ai competitor dashboard: tracked channels, scraped videos, and overperformance analytics.",
    version="1.0.0",
    lifespan=lifespan,
)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(channels.router)
app.include_router(videos.router)
app.include_router(scrape.router)
app.include_router(system.router)


@app.get("/")
def root() -> dict:
    return {"service": "competitor-dashboard-api", "docs": "/docs"}
