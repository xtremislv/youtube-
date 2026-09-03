# Production Roadmap

This is the deployment guide and forward-looking plan for the Competitor
Video Intelligence Dashboard. It covers two deployment paths — a free
split-hosting setup (what you said you're leaning towards) and a
self-hosted Docker/VPS setup — plus the operational things worth knowing
before you rely on this daily, and what's deliberately left for later.

All prices/limits below are as of **September 2026**; free tiers change
without much notice, so treat the numbers as "check the provider's current
pricing page," not gospel.

## Which deployment fits you

| | Free split hosting | Docker on a VPS |
|---|---|---|
| Cost | $0/month (until you outgrow free tiers) | ~$5-12/month (Hetzner/DigitalOcean smallest box) |
| Setup effort | Low — mostly clicking through dashboards | Medium — one `docker compose up`, but you own the box |
| Backend sleeps when idle | Yes (Render free tier) — fine, since scraping is triggered externally, not by an always-on process | No — always on |
| Ops burden | Near zero (managed) | You patch the OS, manage backups yourself |
| Good for | Personal/small-team use, "I don't want a server to think about" | You want everything always-on and under your control |

Both are described below. You can start on the free path and move to a VPS
later without changing any code — only environment variables and where
things run.

---

## Path A: Free split hosting (Vercel + Render + Neon + GitHub Actions)

```
┌─────────────┐      ┌──────────────────┐      ┌─────────────┐
│   Vercel    │ ───▶ │  Render (free)    │ ───▶ │    Neon     │
│  (frontend) │ HTTP │  FastAPI backend  │ SQL  │  (Postgres) │
└─────────────┘      └──────────────────┘      └─────────────┘
                              ▲
                              │ POST /api/scrape/run (HTTPS, daily)
                       ┌──────────────┐
                       │GitHub Actions│
                       │ (free cron)  │
                       └──────────────┘
```

### A1. Database — Neon (free Postgres)

Neon's free plan (as of Sept 2026): 0.5 GB storage/project, 100 compute-
hours/month, compute auto-suspends after 5 minutes idle, no card required,
and it's a permanent free tier (not a trial). That's comfortably enough
for this app's metadata-only storage (no video files, just rows).

1. https://neon.tech → sign up → New Project.
2. Copy the connection string it gives you (starts `postgresql://`).
3. Rewrite it for this app's driver: `postgresql+psycopg://...` (just
   change `postgresql://` to `postgresql+psycopg://`, keep everything
   else including `?sslmode=require`).

*Supabase's free Postgres is a fine alternative if you'd rather use it —
same idea, same env var.*

### A2. Backend — Render (free web service)

1. Push this repo to GitHub if it isn't already.
2. https://render.com → New → Blueprint → point it at your repo. It reads
   `render.yaml` at the repo root and proposes the `competitor-dashboard-api`
   and `competitor-dashboard-frontend` services.
   (No Blueprint UI you like? "New Web Service" → Docker → root directory
   `backend` works the same way, manually.)
3. Before the first deploy, set these environment variables on the
   **competitor-dashboard-api** service (Render dashboard → your service →
   Environment):
   - `DATABASE_URL` — the Neon connection string from A1.
   - `YOUTUBE_API_KEY` — from Google Cloud Console (see root README).
   - `APIFY_API_TOKEN` / `APIFY_INSTAGRAM_ACTOR_ID` — see root README's
     Instagram section, or leave blank to run YouTube-only for now.
   - `SCRAPE_TRIGGER_API_KEY` — generate one:
     `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
   - `CORS_ORIGINS` — your Vercel frontend's URL, once you know it (step A3).
4. Deploy. Render's free web service **sleeps after ~15 minutes idle** and
   cold-starts (10-30s) on the next request — that's fine here: end users
   hitting the dashboard cause a cold start same as any request would, and
   the daily scrape (A4) wakes it deliberately.
5. Check `https://<your-service>.onrender.com/healthz` returns
   `{"status":"ok"}`.

### A3. Frontend — Vercel

1. https://vercel.com → New Project → import the same repo.
2. Vercel should auto-detect Vite (root `vercel.json` pins the build
   command/output dir explicitly regardless).
3. Set one environment variable: `VITE_API_BASE_URL` =
   `https://<your-render-service>.onrender.com` (no trailing slash).
4. Deploy. Once it's live, go back to Render (A2 step 3) and set
   `CORS_ORIGINS` to this Vercel URL, then redeploy the backend so it
   actually accepts requests from it.

### A4. Scheduled scrape — GitHub Actions

Render's free tier doesn't include cron jobs, and an in-process scheduler
would never fire on a service that sleeps — so the trigger lives outside
both, as a scheduled GitHub Actions workflow that just wakes the backend
with an HTTPS request.

1. Repo → Settings → Secrets and variables → Actions → New repository secret:
   - `BACKEND_URL` = your Render backend URL (same as A3 step 3, no `/api`).
   - `SCRAPE_TRIGGER_API_KEY` = the same value you put in Render (A2 step 3).
2. That's it — `.github/workflows/daily-scrape.yml` runs 6 times a day
   (10:00, 12:30, 15:00, 17:30, 20:00 and 22:00 IST) and on-demand any time
   from the Actions tab ("Competitor scrape" → Run workflow) — no redeploy
   needed to get fresh data on demand. Edit the `cron:` lines in that file
   to change the times (each is UTC — the file's comments show the IST
   conversion) or how many runs/day there are.
3. `ENABLE_INTERNAL_SCHEDULER` should stay `false` on Render — it's the
   default in `render.yaml`.

### A5. Seed your channel list

Render's dashboard has a shell (your service → "Shell" tab):

```bash
python scripts/seed_channels.py channels.seed.example.json
# or upload your own list and point the script at it
```

Or add channels one at a time through the dashboard's Competitor Roster
page — same result.

### Free-tier limits to watch

- **Neon**: 100 compute-hours/month. This app's queries are quick and
  infrequent (a handful of dashboard loads + one daily scrape), so you'd
  need heavy dashboard traffic to approach this — but if you do, Neon
  suspends the database until next month rather than deleting data.
- **Render free web service**: 750 hours/month shared across all your free
  services (a single service running 24/7 uses ~730 hours — cutting it
  close if you add a second free service). It also sleeps when idle, which
  is a feature here, not a bug.
- **Apify**: $5/month credit, no rollover. `APIFY_MAX_POSTS_PER_CHANNEL`
  (`.env`, default 30) caps how much one channel's scrape can spend —
  lower it if you're tracking many Instagram accounts and want to stretch
  the credit further.
- **GitHub Actions**: scheduled workflows are free on public repos, and
  private repos get a generous free monthly minutes allowance (this
  workflow uses well under a minute per day either way).

---

## Path B: Docker on a VPS (self-hosted, always-on)

1. Get a small VPS (Hetzner CX22, DigitalOcean Basic, or similar — 1-2 GB
   RAM is plenty) with Docker + Docker Compose installed.
2. Clone the repo onto it.
3. `cp backend/.env.example backend/.env` and fill in `YOUTUBE_API_KEY`,
   `APIFY_API_TOKEN`, `SCRAPE_TRIGGER_API_KEY`. Leave `DATABASE_URL` as-is —
   `docker-compose.yml` overrides it to point at the `db` container.
4. `docker compose up -d --build`
5. `docker compose exec api python scripts/seed_channels.py channels.seed.example.json`
6. Point a domain at the box and put a reverse proxy with TLS in front of
   port 8080 (Caddy is the least fiddly option — a two-line Caddyfile gets
   you automatic HTTPS) — or use Render/Vercel's built-in TLS if you go
   with Path A instead.
7. `ENABLE_INTERNAL_SCHEDULER=true` is already set for you in
   `docker-compose.yml`'s `api` service — the daily scrape runs inside the
   container itself, no external cron needed, since this host never sleeps.
8. Back up the `db_data` Docker volume regularly (`docker compose exec db
   pg_dump -U dashboard dashboard > backup.sql`, on a cron job on the host
   itself — this is genuinely just Postgres, so any standard Postgres
   backup approach works).

---

## Security checklist

- [ ] `SCRAPE_TRIGGER_API_KEY` is a long random value (not left as the
      placeholder from `.env.example`) — anyone who can guess it can spend
      your YouTube quota and Apify credit.
- [ ] `.env` (or your host's secret manager) is never committed —
      `.gitignore` already excludes `backend/.env`, keep it that way.
- [ ] `CORS_ORIGINS` lists only your actual frontend URL(s), not `*`.
- [ ] If you ever expose this beyond yourself/your team, add real user
      authentication in front of it (see Phase 2 below) — right now
      anyone who can reach the API can read all tracked data and manage
      the channel roster; only the scrape trigger is protected.
- [ ] Rotate `YOUTUBE_API_KEY`/`APIFY_API_TOKEN` if a repo or host was ever
      misconfigured to leak them (check your Git history before your first
      push if you developed with real keys in `.env` — again, it's
      gitignored, but double-check).

## Operations

- **Health check**: `GET /healthz` — wire this into whatever uptime
  monitor you use (Render/most hosts do this automatically).
- **Did today's scrape run?** `GET /api/scrape/runs` (or the sidebar's API
  Quota widget, which is driven by the same data) — each run records
  status, channels processed, videos upserted, and any error message.
- **A channel stopped updating**: check `/api/scrape/runs` for its
  platform's most recent run's `errorMessage` — most often a channel
  handle changed, a video was deleted, or (Instagram) the actor's output
  schema shifted (see backend/README.md section 3).
- **Logs**: Render's dashboard streams container logs; on a VPS,
  `docker compose logs -f api`.

## Cost summary

| Scale | Monthly cost |
|---|---|
| Personal / small team, Path A | $0 (until Neon/Render free limits, which this app's usage pattern is very unlikely to hit) |
| Path B on the cheapest VPS | ~$5-6/month |
| Heavier use (large team, many channels, dashboard hit constantly) | Render's paid web service starts around $7/month (removes sleep + adds more RAM); Neon's paid tier starts around $19/month if you outgrow the free compute-hours |

---

## Phase 2 — what's deliberately not built yet

The dashboard ships with six nav sections; only **Overperformance** and
**Competitor Roster** have real views behind them right now (see
`src/App.tsx`'s `ComingSoon` component for the other four). Each is a
reasonable next project, and the API already has the data they'd need:

- **Trend & Velocity** — chart view-count/engagement acceleration over
  time per channel. Data's already there (`published_at`, `views` history
  per video); needs a new `/api/channels/{id}/trend` aggregation endpoint
  and a chart component.
- **Format Matrix** — overperformance broken down by format (long-form vs.
  Shorts vs. Reels) per channel, as a small grid/heatmap. Same underlying
  data as the main feed, grouped differently.
- **Comparison** — pick two channels or cohorts, compare metrics side by
  side.
- **Alert Rules** — real notifications (email/Slack/webhook) when a video
  crosses a custom per-channel/cohort threshold, instead of only the
  in-app bell. Would build on `ScrapeRun` — after each scrape, diff newly
  above-threshold videos against what the last run had, and fire a
  webhook.

Other things worth doing before this scales beyond a personal tool:

- **Authentication** — currently anyone who can reach the API can read/
  write everything. Fine for solo/trusted-team use; add real auth
  (even simple HTTP Basic in front of nginx, or a proper login) before
  wider sharing.
- **Rate limiting** on the public endpoints, if the dashboard is ever
  exposed beyond a trusted network.
- **Thumbnail caching/proxying** — right now `thumbnail_url` points
  directly at YouTube's/Instagram's CDN, which is fine, but those URLs can
  expire for Instagram; caching them (e.g., to S3-compatible storage) would
  make the roster more durable.
- **Multi-workspace support** — `WORKSPACE_NAME` is currently a single env
  var; the DB schema has no workspace/tenant concept, since this was built
  for one team's use.
- **Smarter overperformance baselines** — the current method (trailing
  N-video average, per format) is deliberately simple and explainable.
  Options to explore later: day-of-week seasonality, exponential
  weighting toward recent videos, or accounting for a channel's growth
  trend rather than treating the baseline as flat.
