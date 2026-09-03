# Vortex.ai — Competitor Video Intelligence Dashboard

An interactive dashboard for tracking YouTube and Instagram competitors:
pick a platform (or both), pick one or more channels, set a date range, and
optionally set a minimum-views benchmark — the grid shows every video that
crossed it, ranked by how far it overperformed that channel's normal view
count.

- **Frontend**: React 19 + Vite + Tailwind CSS v4 (the original Figma Make
  export, now wired to a real API instead of hardcoded mock data).
- **Backend**: FastAPI + PostgreSQL (`backend/`) — scrapes YouTube's
  official Data API and Instagram (via an Apify actor), stores it, computes
  the overperformance ratio, and serves it to the frontend.
- **Scheduling**: a daily scrape, either as an in-process job (always-on
  hosts) or triggered by a free GitHub Actions cron workflow (hosts that
  sleep/scale to zero) — see [PRODUCTION_ROADMAP.md](./PRODUCTION_ROADMAP.md).

If you just want to get it running, follow **Quick start** below. For
everything about the backend specifically (module-by-module docs, quota
math, testing) see [backend/README.md](./backend/README.md). For deploying
it for real — Render/Vercel/Neon setup, Docker/VPS setup, costs, and a
phased roadmap of what to build next — see
[PRODUCTION_ROADMAP.md](./PRODUCTION_ROADMAP.md).

## Quick start (Docker Compose — easiest)

Requires [Docker](https://docs.docker.com/get-docker/).

```bash
cp backend/.env.example backend/.env
# open backend/.env and fill in YOUTUBE_API_KEY (see step 1 below) —
# everything else has a working default for local use.

docker compose up -d --build
docker compose exec api python scripts/seed_channels.py channels.seed.example.json
docker compose exec api python scripts/run_scrape.py
```

Open **http://localhost:8080** — that's the dashboard. The API itself is at
http://localhost:8000/docs if you want to poke at it directly. This stack
runs Postgres, the API, and the built frontend together, with a daily
scrape scheduled inside the API container (06:00 server time — change
`DAILY_SCRAPE_HOUR`/`DAILY_SCRAPE_MINUTE` in `backend/.env`).

## Quick start (without Docker)

**1. Get a free YouTube Data API key** (takes ~3 minutes):
   1. https://console.cloud.google.com/ → create a project (or pick one you have).
   2. APIs & Services → Library → search "YouTube Data API v3" → Enable.
   3. APIs & Services → Credentials → Create Credentials → API key.
   4. Copy the key.

**2. Backend:**

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env: paste your YOUTUBE_API_KEY; set DATABASE_URL to a Postgres
# you have (or a free Neon one — see PRODUCTION_ROADMAP.md; or
# sqlite:///./dev.db just to try things out locally)
alembic upgrade head
python scripts/seed_channels.py channels.seed.example.json
python scripts/run_scrape.py --platform youtube
uvicorn app.main:app --reload --port 8000
```

**3. Frontend**, in a second terminal:

```bash
pnpm install
pnpm run dev
```

Open the URL Vite prints (defaults to http://localhost:8443, or set
`PORT`). Requests to `/api/*` are proxied to `http://localhost:8000`
automatically in dev (see `vite.config.ts`) — no CORS setup needed.

## Adding your real competitor list

You mentioned you'd share the actual channel list later — when you have
it, either:

- **Through the UI**: open the dashboard, click **Competitor Roster** in
  the sidebar, and add each one (platform + handle, optional cohort tag to
  group them).
- **In bulk**: edit `backend/channels.seed.example.json` (or make a copy)
  and run `python scripts/seed_channels.py your_list.json` — safe to
  re-run, already-tracked channels are skipped rather than duplicated.

Either way, a channel's videos show up after the next scrape run (manual:
`python scripts/run_scrape.py`; or wait for the daily schedule).

## Instagram scraping needs one more thing

YouTube works out of the box with just the API key above. Instagram has no
equivalent free official API for pulling an arbitrary public competitor's
posts, so this project uses [Apify](https://apify.com) (free plan: $5/month
usage credit, no card required) to run a managed scraper actor. To enable
it:

1. Sign up at apify.com, grab an API token from
   https://console.apify.com/settings/integrations.
2. Paste it into `backend/.env` as `APIFY_API_TOKEN`.
3. Rent an Instagram scraper actor from the Apify Store (search
   "Instagram") and put its id in `APIFY_INSTAGRAM_ACTOR_ID` — the default
   in `.env.example` (`apify/instagram-scraper`) is a commonly used one.
4. Open one item of that actor's sample dataset in the Apify console and
   compare its field names against `backend/app/scrapers/instagram.py`'s
   docstring — different actors name fields slightly differently, and that
   file's `normalize_instagram_item()` is the one place to adjust if so.

## Testing

```bash
cd backend && source .venv/bin/activate && pytest -q   # 53 tests, <2s, no network
cd .. && npx tsc --noEmit -p tsconfig.json               # frontend typecheck
pnpm run build                                             # production build
```

See [backend/README.md](./backend/README.md) section 2 for what's covered
by the automated suite (all the filtering/sorting/overperformance-math
logic, plus scraper response parsing against realistic sample API JSON)
versus what needs a manual run with real credentials (an actual live
YouTube/Apify call).

## Project structure

```
.
├── src/                    Frontend (React/Vite/Tailwind)
│   ├── App.tsx               Main dashboard UI
│   └── lib/api.ts             Fetch wrapper for the backend API
├── backend/                 FastAPI + PostgreSQL backend — see backend/README.md
├── docker-compose.yml       Full self-host stack (Postgres + API + frontend)
├── Dockerfile.frontend       Builds+serves the dashboard via nginx
├── nginx.conf                 nginx config used by the frontend image
├── render.yaml                Render "Blueprint" for a one-click free deploy
├── vercel.json                 Vercel config for hosting just the frontend
├── .github/workflows/
│   ├── daily-scrape.yml        Free cron trigger for hosts that sleep
│   └── backend-tests.yml         Runs pytest on every push
└── PRODUCTION_ROADMAP.md    Deployment guide + what to build next
```

## Design decisions worth knowing about

- **Filtering happens server-side** (`GET /api/videos` — see
  `backend/app/routers/videos.py`), not in the browser. The original Figma
  mock filtered a hardcoded 12-video array client-side; that stops making
  sense once you're tracking real channels with real history.
- **Overperformance is a trailing baseline, computed per channel *and*
  format** — a channel's Shorts aren't compared against its long-form
  videos. Full reasoning in `backend/app/overperformance.py`.
- **The scraper never calls YouTube's `search.list`** (100 quota units/call)
  — it walks each channel's uploads playlist instead (1 unit/page). See
  `backend/README.md`'s quota section for the full budget math.
- **Adding a channel doesn't scrape it immediately** — YouTube identity
  resolution happens synchronously (cheap, 1 API call) so the roster isn't
  blank, but full video scraping waits for the next scrape run, since an
  Apify actor run can take a minute or more and would make "add 10
  competitors" painfully slow if done synchronously.
