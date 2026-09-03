# Backend — Competitor Video Intelligence API

FastAPI + PostgreSQL service that scrapes YouTube (official Data API v3)
and Instagram (via an Apify actor), stores it, computes an
"overperformance ratio" per video, and serves it to the dashboard
frontend. See the root [README.md](../README.md) for the whole project and
[PRODUCTION_ROADMAP.md](../PRODUCTION_ROADMAP.md) for deployment.

Every module below has a docstring at the top explaining what it does and
why it's built the way it is — this file is the map; the code is the
reference.

## Project layout

```
backend/
  app/
    main.py             FastAPI app: CORS, routers, scheduler startup
    config.py            All settings (env vars) — see .env.example
    database.py           SQLAlchemy engine/session
    models.py               ORM: Channel, Video, ScrapeRun
    schemas.py               Pydantic API request/response shapes
    formatting.py             format_count/format_duration/etc — pure helpers
    overperformance.py         The baseline/ratio math (see its docstring)
    channel_service.py          Shared "add a channel" logic (API + CLI)
    scrape_service.py            Orchestrates a scrape run (API + CLI + scheduler)
    scheduler.py                 Optional in-process daily cron (APScheduler)
    deps.py                       Auth dependency for the scrape-trigger endpoint
    routers/
      channels.py                /api/channels — roster CRUD
      videos.py                   /api/videos — the main filtered/sorted feed
      scrape.py                    /api/scrape — manual trigger + run history
      system.py                     /api/system/status — quota/badge widget data
      health.py                      /healthz
    scrapers/
      youtube.py                  YouTube Data API v3 client + parsing
      instagram.py                  Apify client + parsing
      duration.py                    ISO 8601 duration parsing
  scripts/
    seed_channels.py             Bulk-add channels from a JSON file
    run_scrape.py                  CLI scrape trigger (alternative to HTTP)
  alembic/                       Database migrations
  tests/                         53 tests, no network/DB server required
  requirements.txt               Pinned dependencies
  requirements.in.txt             Unpinned — regenerate requirements.txt from this
  Dockerfile / docker-entrypoint.sh
  .env.example                   Every setting, documented
  channels.seed.example.json     Example input for seed_channels.py
```

## 1. Local setup (no Docker)

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# edit .env: at minimum set DATABASE_URL to a Postgres instance you have
# (a local `postgres` via Homebrew/apt, or a free Neon/Supabase database —
# see PRODUCTION_ROADMAP.md). YOUTUBE_API_KEY / APIFY_API_TOKEN can stay
# blank for now — the API and roster still work, scraping just won't.

alembic upgrade head              # creates the tables
uvicorn app.main:app --reload --port 8000
```

Visit http://localhost:8000/docs for interactive API docs (Swagger UI),
generated automatically from the Pydantic schemas.

Don't have a Postgres handy yet? You can point `DATABASE_URL` at
`sqlite:///./dev.db` to poke around locally — the ORM only uses portable
column types, so SQLite works for development. Use real Postgres before
deploying (see PRODUCTION_ROADMAP.md for a free option).

## 2. Running the test suite

```bash
source .venv/bin/activate
pytest -q          # 53 tests, in-memory SQLite, no network, <2s
```

What's tested and how (see each test file's own docstring for more):
- `test_formatting.py`, `test_duration.py`, `test_overperformance.py` — pure
  functions, no I/O. This is where the "overperformance ratio" math itself
  is verified (trailing window, format-bucketing, missing-baseline
  handling).
- `test_youtube_parsing.py`, `test_instagram_parsing.py` — feed the
  scrapers' pure `parse_*`/`normalize_*` functions realistic sample API
  JSON and check the normalized output. No API key or network needed;
  these are the tests to extend if you rent a different Apify actor (see
  `app/scrapers/instagram.py`'s docstring) or Google changes a field name.
- `test_api_*.py` — full HTTP requests through FastAPI's TestClient against
  an in-memory SQLite database, covering filtering/sorting/pagination,
  channel CRUD, cohorts, the scrape-trigger auth gate, and the system
  status widget.

What's **not** covered by the automated suite, on purpose: an actual live
call to YouTube or Apify. Those need real credentials and real quota/credit
spend, so they're a manual step — see "3. Testing against live APIs" below.

## 3. Testing against live APIs (manual)

Once you have a `YOUTUBE_API_KEY` in `.env`:

```bash
python scripts/seed_channels.py channels.seed.example.json
python scripts/run_scrape.py --platform youtube
curl http://localhost:8000/api/videos | python -m json.tool
```

The first line adds a handful of well-known channels (MKBHD, LTT, etc.) so
you have something to scrape immediately. The second actually calls
YouTube; watch the printed `youtube_quota=` number — a fresh add-then-scrape
of ~8 channels should cost well under 50 quota units total (see "Quota
budget" below for the math).

Once you have an `APIFY_API_TOKEN`:

```bash
python scripts/run_scrape.py --platform instagram
```

This is the point where you should double-check
`app/scrapers/instagram.py`'s field-name assumptions actually match
whichever Apify actor you rented — open one item in the actor's dataset in
the Apify console and compare. If the run finishes with 0 videos upserted
despite the actor reporting results, that's the most likely cause; the
module's docstring says exactly what to adjust.

## 4. Quota budget (why this scraper is cheap)

YouTube's Data API v3 free tier is 10,000 units/day per Google Cloud
project. This scraper deliberately never calls `search.list` (100 units/
call) — see `app/scrapers/youtube.py`'s docstring for the full reasoning.
Per channel, per day:

| Call | Cost | When |
|---|---|---|
| `channels.list` | 1 unit | every scrape (refresh name/avatar/subs) |
| `playlistItems.list` | 1 unit/page | 1 page/day normally (only more on a channel's very first scrape, or if it posts >50 videos/day) |
| `videos.list` | 1 unit per 50 video IDs | refreshes view/like/comment counts for the channel's *entire* tracked history, not just new uploads |

A channel with 200 tracked videos costs roughly `1 + 1 + ceil(200/50) = 6`
units/day. Twenty such channels: ~120 units/day — about 1% of the free
budget. The sidebar's "API Quota" widget (`GET /api/system/status`) sums
`ScrapeRun.youtube_quota_units_used` for the current day so you can watch
this in the dashboard itself rather than trust the math.

Apify has no quota in the same sense — it's metered by actor compute
("Compute Units"), and the free plan is $5/month of credit (see
PRODUCTION_ROADMAP.md for what that buys and how `APIFY_MAX_POSTS_PER_CHANNEL`
caps a runaway run).

## 5. The overperformance methodology, briefly

Full explanation lives in `app/overperformance.py`'s docstring — short
version: each video's baseline is the trailing average of up to
`BASELINE_WINDOW_VIDEOS` (default 10) of that *same channel's* previous
videos of the *same format* (long-form YouTube, YouTube Shorts, and
Instagram Reels are never averaged together). A video needs
`BASELINE_MIN_VIDEOS` (default 3) prior videos before a baseline exists at
all — a channel's first few tracked videos show "New" in the UI instead of
a fabricated ratio. `overperform_ratio = views / baseline`; the dashboard's
"overperforms" badge/notification threshold is `>= OVERPERFORM_RATIO_DEFAULT`
(2.0x by default). Both numbers are env vars — tune them in `.env` without
touching code.

## 6. Database migrations

```bash
# after changing app/models.py:
alembic revision --autogenerate -m "describe the change"
# review the generated file in alembic/versions/ before committing —
# autogenerate is a good first draft, not infallible, especially for
# renames (it sees a rename as a drop + add unless you edit it by hand)
alembic upgrade head
```

## 7. API reference

Full interactive reference: run the server and visit `/docs` (Swagger) or
`/redoc`. Summary:

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/channels` | List tracked channels (`?platform=youtube\|instagram`, `?include_inactive=true`) |
| POST | `/api/channels` | Track a new channel `{platform, handle, cohort?}` |
| PATCH | `/api/channels/{id}` | Update `{cohort?, isActive?, notes?}` |
| DELETE | `/api/channels/{id}` | Stop tracking (deletes its videos too) |
| GET | `/api/channels/cohorts` | Cohort label -> channel count |
| GET | `/api/videos` | The main feed — see `app/routers/videos.py` for every query param |
| GET | `/api/scrape/runs` | Recent scrape run history |
| POST | `/api/scrape/run` | Trigger a scrape now — requires `X-API-Key` header (`SCRAPE_TRIGGER_API_KEY`) |
| GET | `/api/system/status` | Quota widget, badge counts, workspace name |
| GET | `/healthz` | Liveness probe |
