# Production-Readiness Audit — Competitor Video Intelligence Dashboard

**Date:** September 24, 2026
**Scope:** Full codebase (backend, frontend, infrastructure/deployment config), live production environment (`https://youtube-phi-blue.vercel.app` + `https://competitor-dashboard-api.onrender.com`)
**Method:** Static review of every backend module, router, and scraper; the full frontend `App.tsx`; all deployment/CI config; live verification of the production API and frontend via direct HTTP requests.
**Status:** Read-only audit. No code was changed. Findings below are the basis for a follow-up fix pass, to be scoped and approved separately.

---

## 0. Live-environment verification (done today, changes the picture from the last debugging session)

Two things were re-checked live before writing this report, since they materially affect severity ratings below:

1. **The previously-diagnosed "/api/search/\* returns 404 in production" incident is currently RESOLVED.** A direct fetch to `https://competitor-dashboard-api.onrender.com/api/search/latest` right now returns `200` with real cached search data (`searchedAt: 2026-09-22`), and `/api/system/status` shows a successful scrape as recently as `2026-09-24T05:35:25Z`. Whatever caused the earlier stale deploy has since cleared (most likely a later successful Render redeploy). **The root cause is not fixed, though** — see CRITICAL-1 below, which is about the deploy pipeline having no safeguard against this recurring.
2. **The live backend has zero security headers, and its interactive API docs are publicly exposed.** Confirmed via direct response-header inspection: neither `https://competitor-dashboard-api.onrender.com` nor `https://youtube-phi-blue.vercel.app` sets `Content-Security-Policy`, `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, or `Permissions-Policy`. `GET /docs` and `GET /openapi.json` both return `200` with the full Swagger UI / OpenAPI schema, unauthenticated. (Note: since both `*.vercel.app` and `*.onrender.com` are on browsers' HSTS preload lists as platform domains, HTTPS itself is enforced regardless of a missing `Strict-Transport-Security` header — that specific gap is lower risk than the others.)

These are folded into the numbered findings below rather than repeated.

---

## 1. Executive summary

The application is functionally solid and unusually well-documented for a project this size — clear module boundaries on the backend, an ORM used consistently with no raw-SQL injection surface, sensible quota/cooldown guards on the two genuinely expensive third-party-API endpoints, and a visually polished, feature-complete frontend. It is **not yet production-ready for anything beyond a small trusted team**, for four concrete reasons that recur across the findings:

- **Most state-changing backend endpoints have no authentication at all.** Only the two scrape-trigger endpoints (called by GitHub Actions) require an API key. `DELETE /api/channels/{id}` (cascades to delete a channel's entire scraped history), `PATCH /api/settings/scraper`, and `POST /api/channels` are wide open to anyone who can reach the API — and the publicly-exposed `/docs` makes them trivial to discover.
- **Failures are swallowed instead of surfaced, on both ends.** The backend can leak the plaintext YouTube API key into an unauthenticated `error_message` field on scrape failures; the frontend silently treats most fetch failures (including a currently-possible `/api/search/*` outage) as "no data yet" rather than an error, which is actively misleading.
- **The deploy pipeline has no safety net.** A single failing `alembic upgrade head` inside `docker-entrypoint.sh` silently leaves Render serving a stale build with no alert — this is exactly what caused the incident described in section 0.
- **The frontend has no automated tests, no error boundary, and almost no responsive design** (one Tailwind breakpoint in the entire ~2,300-line file), and a destructive delete-channel action has no confirmation step.

None of this requires a rewrite. Every finding below has a specific, scoped fix. The prioritized roadmap in section 5 sequences them by risk and effort.

---

## 2. Backend findings

*(FastAPI + SQLAlchemy + PostgreSQL, deployed on Render)*

### CRITICAL

**CRITICAL-1 — Deploy pipeline has no failure safety net (this is what caused the section-0 incident)**
- **File:** `backend/docker-entrypoint.sh` (lines 6–12), `backend/Dockerfile`
- **Problem:** The entrypoint runs under `set -euo pipefail` and executes `alembic upgrade head` before `exec "$@"`, with no retry, timeout, fallback, or alerting. If the migration fails or hangs (a bad migration, a Postgres lock, Neon cold-start latency), the container never starts uvicorn — and Render just keeps serving the previous successful deploy, silently. That's precisely the mechanism behind `/api/search/*` returning 404s in production while `/healthz` stayed green.
- **Why it matters:** A whole route group can vanish from production with zero alert, and nothing distinguishes "route removed on purpose" from "migration failed hours ago."
- **Fix:** Run `alembic upgrade head` as its own pre-deploy step (Render "pre-deploy command" or a separate CI step) that fails the deploy visibly, rather than inline in the same script that starts the app. Add a post-migration smoke check before considering a deploy healthy. Add a Dockerfile `HEALTHCHECK` hitting `/healthz`, and add a non-root `USER` (the container currently runs as root — no `USER` directive anywhere in the Dockerfile).
- **Impact:** Failed migrations become loud, actionable deploy failures instead of invisible partial outages.

**CRITICAL-2 — YouTube API key can leak through an unauthenticated endpoint**
- **File:** `backend/app/routers/scrape.py` (`GET /api/scrape/runs` — no API key required), `backend/app/scrape_service.py` (lines ~82, 115, 137)
- **Problem:** Exceptions from YouTube API calls are captured as raw strings (`f"{channel.id}: {exc}"`) and stored verbatim (truncated to 4000 chars, not scrubbed) on `ScrapeRun.error_message`. `googleapiclient`'s `HttpError.__str__()` embeds the full request URI — including the `key=<YOUTUBE_API_KEY>` query parameter — and this field is returned by `GET /api/scrape/runs`, which has zero authentication.
- **Why it matters:** Any YouTube API error during a scrape (quota exceeded, transient 5xx, malformed response) has a real chance of putting the plaintext API key into a field any anonymous caller can read with one GET request. A leaked key lets someone exhaust the shared daily quota or spend it on unrelated work.
- **Fix:** Strip query-string secrets from any exception message before storing/logging it (a small regex removing `key=[^&"]+`, or catch `HttpError` specifically and use only `exc.resp.status`/`exc.reason`). Separately, require the existing `X-API-Key` dependency on `GET /api/scrape/runs`, or move the dashboard's "last scrape" summary to `/api/system/status` (already public, already redacted) instead.
- **Impact:** Closes a live credential-exfiltration path.

**CRITICAL-3 — No `.dockerignore` anywhere in the repo**
- **File:** repo-wide (confirmed: no `.dockerignore` exists for `backend/` or the root frontend build context)
- **Problem:** `backend/Dockerfile`'s `COPY . .` copies the entire build context unfiltered. `backend/app/config.py` explicitly documents keeping a local `.env` in `backend/` for development — the same directory a `docker build` normally runs from. A single local build from a checkout with a populated `.env` bakes `YOUTUBE_API_KEY`, `APIFY_API_TOKEN`, `SCRAPE_TRIGGER_API_KEY`, and `DATABASE_URL` permanently into an image layer, recoverable by anyone with pull access even after the file is deleted.
- **Fix:** Add `backend/.dockerignore` excluding `.env`, `.venv/`, `.pytest_cache/`, `tests/`, `.git`, `__pycache__/`, `*.pyc`.
- **Impact:** Removes an easy, plausible secret-leak vector; also shrinks every image build.

**CRITICAL-4 — Interactive API docs and full OpenAPI schema are public in production**
- **File:** `backend/app/main.py` (`FastAPI(...)` constructed with no `docs_url=None`/`redoc_url=None`); confirmed live at `https://competitor-dashboard-api.onrender.com/docs` and `/openapi.json` (both return 200, no auth)
- **Problem:** Every route, request/response schema, and parameter is discoverable by anyone, including the unauthenticated write endpoints in HIGH-1 below.
- **Why it matters:** Turns "find the unprotected endpoints" from a guessing exercise into a two-second `/docs` visit.
- **Fix:** Disable `/docs` and `/redoc` in production (`docs_url=None, redoc_url=None` when an env flag like `ENVIRONMENT=production` is set), or gate them behind the same API key used elsewhere.
- **Impact:** Removes a free reconnaissance tool for an attacker.

### HIGH

**HIGH-1 — Destructive and state-changing endpoints have no authentication**
- **File:** `backend/app/routers/channels.py` (`POST /api/channels`, `PATCH /api/channels/{id}`, `DELETE /api/channels/{id}`), `backend/app/routers/settings.py` (`PATCH /api/settings/scraper`)
- **Problem:** Unlike `/api/scrape/run` and `/api/scrape/check-velocity` (both require `X-API-Key`), these have no protection at all. `DELETE` cascades and permanently removes a channel plus its entire video/velocity history in one call.
- **Why it matters:** The app is publicly reachable (Vercel frontend, no IP allowlisting) and, per CRITICAL-4, its full schema is trivially discoverable. Anyone can wipe the competitor roster's history or silently disable Instagram tracking.
- **Fix:** Reuse the existing `require_scrape_api_key` dependency (`app/deps.py`) — or a second, differently-scoped key — on the write/delete routes for channels and settings. Leave read-only `GET`s and the two browser-triggered no-secret-to-keep endpoints (`/run-manual`, `/api/search/topic`) as the documented exceptions.
- **Impact:** Closes the gap between "any internet client" and "trusted team member" without waiting for a full auth system.

**HIGH-2 — Scrape and topic-search triggers have check-then-act races that can double-spend metered quota**
- **File:** `backend/app/routers/scrape.py` (`trigger_manual_scrape`, `trigger_scrape` — the latter has *no* cooldown guard at all), `backend/app/routers/search.py` (lines 142–170), `backend/app/topic_search.py` (`_persist_outcome`)
- **Problem:** Cooldown and quota-budget checks read state, then act — they aren't atomic. Two near-simultaneous requests (double-click, retried GitHub Actions run, two open tabs) can both pass the check before either commits, and both proceed. The single-slot `TopicSearchCache` (fixed `id=1` rows) can also see two concurrent delete/insert transactions race.
- **Why it matters:** Doubles real YouTube quota/Apify credit spend in one event — the exact cost these guards exist to prevent — and can surface as a raw 500 instead of the clean 429/502 the single-request path already handles.
- **Fix:** Enforce the cooldown at the database level (a Postgres advisory lock held for the duration of the scrape/search, or `SELECT ... FOR UPDATE` on the relevant row) instead of in Python.
- **Impact:** Makes the quota-budget guard actually hold under concurrent load.

**HIGH-3 — Unauthenticated, unbounded query on a hot-path endpoint**
- **File:** `backend/app/routers/channels.py` (`_median_views_last_10_by_channel`), no rate-limiting middleware anywhere in `main.py`
- **Problem:** `GET /api/channels` (unauthenticated, called on every dashboard load) loads `(channel_id, views, published_at)` for **every video row in the database**, with no filter or limit, to compute medians in Python.
- **Why it matters:** On Render's free-tier single instance, repeated calls to this endpoint pull the entire video history into memory — a trivial, no-auth-required way to degrade or crash the service, and it only gets worse as scraped history grows.
- **Fix:** Replace with a bounded window query (`ROW_NUMBER() OVER (PARTITION BY channel_id ORDER BY published_at DESC) <= 10`, supported by both Postgres and modern SQLite) instead of pulling every row into Python; add basic rate limiting (even a simple in-memory token bucket) in front of read-only listing endpoints.
- **Impact:** Removes an unbounded, unauthenticated, memory-proportional-to-history query from the hot path.

### MEDIUM

- **CORS is broader than needed:** `allow_credentials=True` combined with `allow_methods=["*"]`/`allow_headers=["*"]` in `main.py`, even though nothing in the app uses cookies — auth (where it exists) is a header sent server-to-server. Set `allow_credentials=False` and scope methods/headers to what's actually used, so a future accidental origin-allowlist widening doesn't also widen method/header exposure.
- **Non-constant-time API-key comparison:** `app/deps.py` uses `x_api_key != settings.scrape_trigger_api_key` (plain `!=`) instead of `hmac.compare_digest`, a minor timing side-channel on the one real secret this app enforces.
- **In-process scheduler and GitHub Actions cron can both run unattended:** `app/scheduler.py`'s APScheduler and the GH Actions workflow both call `run_daily_scrape` with nothing but documentation preventing both from being active at once (`ENABLE_INTERNAL_SCHEDULER` is meant to be mutually exclusive with the Actions cron, but nothing enforces it in code). A future move to an always-on host that forgets to disable the old cron doubles quota spend silently.
- **`GET /api/scrape/runs`'s `limit` has no bound** (`limit: int = 20` with no `Query(ge=1, le=...)`), unlike every other paginated endpoint in the codebase — allows an oversized or negative value on an unauthenticated route.
- **Naive-vs-aware datetime handling copy-pasted in ≥4 modules:** every timestamp column is `DateTime(timezone=True)` but populated with `dt.datetime.utcnow()` (naive), so a "coerce to UTC if naive" snippet is hand-duplicated in `scrape.py`, `search.py`, `sponsorblock.py`, and `velocity.py`. `datetime.utcnow()` is also deprecated as of Python 3.12 (the exact base image pinned). Fix once at the source (`dt.datetime.now(dt.timezone.utc)` everywhere) and delete the repeated coercions.
- **Duplicate-channel creation races to an unhandled 500 instead of a 409:** `channel_service.py`'s duplicate check is check-then-act with no `try/except IntegrityError` around the commit, even though a unique index already exists to catch it at the DB level.
- **`render.yaml` defines a dead `competitor-dashboard-frontend` static service** that isn't actually used (Vercel is the real frontend host per `PRODUCTION_ROADMAP.md`) — stale infrastructure-as-code that risks confusion or accidental duplicate deploys.

### LOW / OPTIONAL

- `get_quota_used_today` (`quota.py`) uses local naive `date.today()` for the day boundary instead of explicit UTC, unlike every other date calculation in the codebase — works today only because the container's timezone happens to default to UTC.
- `Video.views` has no index despite being a supported `sort_by` option in `GET /api/videos`, unlike the other three sort columns.
- Test coverage gaps: no dedicated tests for `deps.py`'s API-key check itself (the one real access-control mechanism in the app), `channel_service.py`'s duplicate-race path, `quota.py`, or `scheduler.py`.
- `TopicSearchRequest.query` and `ChannelCreate.handle` have no `max_length`, so oversized input fails late instead of with a fast 422.
- A query parameter literally named `format` shadows the Python builtin in `routers/videos.py` (cosmetic only).

---

## 3. Frontend findings

*(React 19 + Vite 8 + TypeScript + Tailwind v4, single-file `src/App.tsx`, deployed via Vercel)*

### CRITICAL

**CRITICAL-5 — Deleting a competitor channel has no confirmation and no error handling**
- **File:** `src/App.tsx`, `CompetitorRoster`'s `handleRemove` (~line 1200), wired to `ChannelCard`'s trash icon button
- **Problem:** `onClick` calls `deleteChannel(id)` directly — no confirmation dialog, no try/catch. A rejected promise (network blip, 404, 500) is unhandled: nothing is shown, the row may or may not disappear, and there's no in-flight/disabled state to stop a double-click from firing two overlapping deletes.
- **Why it matters:** One misclick on a small, unlabeled icon button permanently deletes a tracked channel and its entire scraped history, with no undo.
- **Fix:** Add an inline "confirm remove?" step before calling `deleteChannel`; wrap the call in try/catch and surface the error the same way `CompetitorRoster`'s add-channel form already does; disable the control while the request is in flight.
- **Impact:** Eliminates accidental, unrecoverable data loss.

**CRITICAL-6 — No error boundary anywhere in the app**
- **File:** `src/main.tsx`, `src/App.tsx` (confirmed: zero matches for `ErrorBoundary`/`componentDidCatch` in the codebase)
- **Problem:** The entire UI is one ~2,300-line tree rendered under a bare `<React.StrictMode><App /></React.StrictMode>`. Any uncaught render exception anywhere (a null-deref on an unexpected API shape, for instance) unmounts the whole tree and blanks the page, with no recovery short of a manual reload.
- **Fix:** Wrap `<App />` (and ideally the video grid and Trend Analysis results specifically) in an error boundary showing a "Something went wrong — reload" fallback.
- **Impact:** Converts a full-page crash into a contained, recoverable failure.

### HIGH

**HIGH-4 — Backend failures are silently swallowed and disguised as empty states — directly relevant to the section-0 incident class**
- **File:** `src/App.tsx` — `fetchChannels`, `fetchCohorts`, `fetchSystemStatus`, `fetchScraperSettings`, the Trend Analysis tab's initial `fetchLatestTopicSearch` (line ~1575), the notification bell's fetch — all use a bare `.catch(() => {})` with no error state ever set.
- **Why it matters:** When the backend is unreachable or errors, the UI shows "No competitors tracked yet," an empty cohort list, quota stuck at "—", or (specifically for Trend Analysis) "No searches yet — try a topic above" — all of which read as legitimate first-run states, not outages. This is exactly what would have made the section-0 incident invisible to end users as anything other than "the feature doesn't work," with no signal that it was a backend problem. Even now that the search endpoint is back up, the exact same silent-failure pattern will hide the *next* outage just as effectively.
- **Fix:** Track an error flag per fetch (or a shared one) and render a small "Couldn't reach the server — retry" banner wherever these silent catches sit today, mirroring the pattern already correctly used for the main video grid (`videosError`). For the Trend Analysis tab specifically, the `!result` branch should check for an error state before falling back to the friendly "No searches yet" copy.
- **Impact:** Real backend failures become visible and actionable instead of masquerading as empty data.

**HIGH-5 — "Load more" failures destroy already-loaded results**
- **File:** `src/App.tsx`, `handleLoadMore` (~lines 2001–2026) and its render logic (~lines 2222–2272)
- **Problem:** The render logic checks `videosError` first, unconditionally hiding the grid. If a user has already loaded, say, 180 videos and the next page's request fails, the entire grid is replaced by a full-page error screen — the successful results are thrown away, and the only path back is changing a filter (which also resets pagination).
- **Fix:** Give pagination failures their own state (e.g. `loadMoreError`), shown inline near the "Load more" button, without touching the already-rendered grid.
- **Impact:** A transient pagination failure no longer destroys already-loaded results.

**HIGH-6 — Stale-response race in the main video-fetch effect**
- **File:** `src/App.tsx`, main filter-driven video-fetch effect (~lines 1967–1995)
- **Problem:** The effect debounces with a 300ms timeout, but once a request is in flight there's no "is this response still relevant" guard — unlike `ChannelStatCard`'s velocity fetch a few hundred lines away, which correctly uses a `cancelled` flag for exactly this.
- **Why it matters:** Two filter changes spaced more than 300ms apart can have their responses arrive out of order under normal network jitter; a stale response can silently overwrite the correct, newer result, showing data for filters the user no longer has selected.
- **Fix:** Add the same `cancelled`/request-id guard already used in `ChannelStatCard`.
- **Impact:** Removes a real, reproducible "stale filter results" bug in the core view.

**HIGH-7 — Almost no responsive design; the app is effectively unusable on mobile**
- **File:** `src/App.tsx` (exactly one Tailwind breakpoint class — `sm:` — in the entire file), `src/index.css` (`overflow: hidden` on `html, body, #root`, plus scrollbars hidden globally)
- **Why it matters:** The sidebar is a fixed 240px with no auto-collapse; the top bar and filter bar pack many controls in a single non-wrapping row. On a phone-width viewport, combined with `overflow: hidden` at the document root and no visible scrollbars, content is clipped rather than scrollable — there's no way to reach it.
- **Fix:** Collapse the sidebar to an overlay/drawer below a breakpoint, let the top/filter bars wrap or stack on narrow widths, and reconsider the blanket `overflow: hidden`.
- **Impact:** Makes the dashboard usable on tablet/phone widths at all.

**HIGH-8 — Single-file architecture with zero test coverage**
- **File:** `src/App.tsx` (whole file, ~2,300 lines), `package.json` (no test framework in devDependencies)
- **Why it matters:** Every change ships the entire bundle (no code-splitting is even possible without extraction), unrelated edits risk merge conflicts and regressions, and none of the bugs in this report have any automated protection against recurring.
- **Fix:** Split into per-view/per-component files; add Vitest (pairs naturally with the existing Vite setup) with at least coverage for the debounce/race-condition logic and the filter-preset math.
- **Impact:** Safer, more reviewable changes and a place to actually catch regressions.

### MEDIUM

- **Icon-only buttons have no accessible name:** sidebar toggle, notification bell, channel-card trash button, notification-panel close, and filter-chip removal buttons all render an SVG with no `aria-label`/`title` — contrast with `ChannelStatCard`'s clear button and `ToggleSwitch`, which do this correctly.
- **Skip-link support exists but is turned off:** `.figma/make/site.json` sets `accessibility.addBypassLinks: false`, even though the feature is fully implemented in `vite.config.ts` — a one-line flip restores standard skip-navigation for keyboard users who currently must tab through the entire sidebar on every load.
- **Section switches move no focus and announce nothing:** clicking a sidebar nav item just changes `activeSection` state with no focus movement or `aria-live` region — a screen-reader user gets no indication the "page" changed.
- **Form inputs rely on placeholder text or visually-adjacent `<div>`s instead of real `<label>` elements** (the min-views input, the date-preset select, roster add-channel fields, the Trend Analysis min-subscribers input) — not announced correctly to screen readers.
- **`DEFAULT_FILTERS` is computed once at module load, not at time of use:** the "Home" reset button restores a `dateFrom`/`dateTo` frozen at the moment the page was first loaded, not "the last 3 days from now" — wrong if a tab is left open across a day boundary.
- **The overperformance chart is captioned as reflecting "filtered results" but only ever sees the currently-loaded page(s)** (up to 60 per fetch), not the full filtered total — the ranking it shows can be materially wrong for filters matching more results than have been paged in.
- **Duplicate, uncoordinated timeouts for refresh status messages:** each click of "Refresh data" schedules its own 6-second timeout to clear the status message with no cancellation of a prior pending one — two quick clicks can have the first click's timeout wipe the second click's message early.
- **No `React.memo`/virtualization on `VideoCard`/`ChannelStatCard`:** any unrelated top-level state change (opening notifications, toggling theme) re-renders every mounted card; a real Core Web Vitals (INP) risk as loaded-video count grows.
- **Trend Analysis's min-subscribers field silently treats invalid input as "no filter at all"** (`Number(minSubscribers) || 0`) with no validation message — a mistyped value produces a much broader search with no indication anything changed.
- **Touch targets under the ~44px minimum** on filter-chip removal buttons (~10px hit area) and the channel-card clear control (18×18px) — unreliable on touch devices, compounding the missing-responsive-design finding above.
- **An interactive control nested inside another interactive control:** `ChannelStatCard`'s `role="button"` wrapper contains a separately-tabbable clear `<button>` — an invalid/ambiguous pattern for assistive technology.

### LOW / OPTIONAL

- The Overperformance tab's "Min views" input has no `min={0}` (inconsistent with the otherwise-identical Trend Analysis min-subscribers input, which does).
- Scrollbars are hidden globally (`scrollbar-width: none`), removing the visual cue that a panel (cohort list, velocity checkpoints) has more content than fits.
- A few spots cast through `any` to satisfy TypeScript for a conditional element wrapper, defeating `strict: true` locally.
- The 6-second refresh-message timeout is scheduled outside any effect cleanup — dormant today since `App` never unmounts, but a latent leak pattern.
- No Open Graph image is configured, so internal links shared in Slack/email show no preview thumbnail (not an SEO issue — the site is intentionally `noindex, nofollow` via `.figma/make/site.json`, which is correct for a private internal tool).

---

## 4. Deployment & infrastructure findings

*(Vercel + Render + Neon + GitHub Actions, per `PRODUCTION_ROADMAP.md`'s "Path A")*

### CRITICAL

- **No security headers on either the frontend or the backend in production** (verified live, section 0): no `Content-Security-Policy`, `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, or `Permissions-Policy` anywhere. `vercel.json` has no `headers` block, and `nginx.conf` (used only in the self-hosted Docker path) also sets none. **Fix:** add a `headers` array to `vercel.json` (Vercel supports this natively, no server needed) covering at least `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`, and a baseline `Content-Security-Policy`; add the equivalent `add_header` directives to `nginx.conf` for the self-host path. Add the same set as FastAPI middleware on the backend for its own JSON responses and the exposed `/docs` (see CRITICAL-4 above; this listing exists to note it's a deployment-layer gap, not only an app-layer one).
- **See CRITICAL-4 (backend section) and CRITICAL-1 (backend section)** — both are deployment-configuration issues as much as backend ones (missing `docs_url=None` for production, and the entrypoint's unguarded migration step) and are the two most directly tied to what already caused a real production incident.

### HIGH

- **No `.dockerignore` anywhere in the repository** — see CRITICAL-3 in the backend section; this is as much a deployment/build-pipeline gap as a backend one, since it also affects `Dockerfile.frontend`'s build context.
- **No frontend CI at all.** `.github/workflows/backend-tests.yml` runs `pytest` on backend changes; there is no equivalent workflow for the frontend — no `tsc --noEmit`, no `vite build` check, no lint gate on pull requests. A broken TypeScript build or a lint violation has no CI signal before merge; it would only surface when Vercel's own build step fails on the already-merged commit. **Fix:** add a `.github/workflows/frontend-checks.yml` running `pnpm install --frozen-lockfile`, `pnpm run build`, and `npx tsc --noEmit` on every push/PR touching frontend files — mirrors the existing backend workflow's shape.
- **No dependency-update automation.** No `dependabot.yml` or Renovate config exists for either the Python (`backend/requirements.txt`) or JS (`package.json`) dependency trees. Both are pinned with `^`/exact versions with no process to surface new CVEs or available patches. **Fix:** add a minimal `.github/dependabot.yml` covering both `pip` (`/backend`) and `npm` (`/`) ecosystems on a weekly schedule.

### MEDIUM

- **`render.yaml` defines a dead `competitor-dashboard-frontend` static service** that isn't actually used — Vercel is the real frontend host. Stale infra-as-code risks confusion (someone deploying it thinking it's live) or drift from the real Vercel config. **Fix:** remove the unused service block from `render.yaml`, or add a comment explaining it's intentionally unused/kept only as a documented alternative.
- **No explicit cache-control policy for static assets in `nginx.conf`** (the self-hosted Docker/VPS path) — no long-cache-with-fingerprint / no-cache-for-`index.html` split. Not relevant to the live Vercel deployment (which handles this automatically, confirmed via the `cache-control: public, max-age=0, must-revalidate` + `etag` headers already observed live), but would matter if the Docker Compose/VPS path (`docker-compose.yml`) is ever used for real.
- **The frontend's last production build (per live `Last-Modified` header) is from September 10, while the backend has been redeployed and has fresh data through September 22–24.** Not a bug today — no frontend-breaking API change has shipped since — but there's no process tying a backend contract change to a required frontend redeploy; a future breaking API change deployed to Render without a corresponding Vercel deploy would break the UI with no automated signal.
- **`Dockerfile` (backend) has no `HEALTHCHECK` instruction and runs as root** — already flagged in CRITICAL-1's fix, restated here as a deployment-config-specific line item since it's a one-line Dockerfile fix independent of the migration-safety work.

### LOW / OPTIONAL

- `docker-compose.yml`'s Postgres service uses hardcoded `dashboard`/`dashboard` credentials — acceptable for local self-hosting (not internet-facing by default) but worth a comment noting they should be changed if the compose file is ever adapted for a real VPS deployment (which `PRODUCTION_ROADMAP.md`'s Path B does describe as a real option).
- No `robots.txt`/sitemap beyond the intentional site-wide `noindex, nofollow` (correct and deliberate for a private tool — not a gap).
- `backend/.env.example` and `PRODUCTION_ROADMAP.md`'s own security checklist already correctly call out rotating keys and never committing `.env` — this is good existing practice, confirmed still followed (no `.env` file found committed anywhere in the repo).

---

## 5. Prioritized production-readiness roadmap

**Phase 1 — Close the exposure gaps (do first, low effort, high risk reduction)**
1. Disable `/docs`/`/redoc` in production, or gate behind the existing API key (CRITICAL-4).
2. Add `.dockerignore` to `backend/` and the frontend build context (CRITICAL-3).
3. Add security headers to `vercel.json` and `nginx.conf` (CRITICAL, deployment section).
4. Add the `X-API-Key` guard to `channels.py`'s write/delete routes and `settings.py`'s `PATCH` (HIGH-1).
5. Scrub secrets from exception messages before they reach `ScrapeRun.error_message`, or lock down `GET /api/scrape/runs` (CRITICAL-2).
6. Add a confirmation step + error handling to the frontend's channel-delete action (CRITICAL-5).

**Phase 2 — Make failures visible instead of silent (medium effort, prevents the next version of the incident that already happened once)**
7. Replace silent `.catch(() => {})` fetch failures across the frontend with a visible error state, especially the Trend Analysis tab (HIGH-4).
8. Fix the "Load more" error path so it doesn't destroy already-loaded results (HIGH-5).
9. Add a global React error boundary (CRITICAL-6).
10. Separate `alembic upgrade head` from app startup and add deploy-failure alerting (CRITICAL-1) — this is the actual fix for the root cause behind the incident in section 0.

**Phase 3 — Reliability and correctness (medium effort)**
11. Fix the check-then-act races on scrape/search cooldowns and quota budgets with DB-level locking (HIGH-2).
12. Fix the stale-response race in the main video-fetch effect (HIGH-6).
13. Bound the unauthenticated `/api/channels` median-views query and add basic rate limiting (HIGH-3).
14. Consolidate the naive/aware datetime handling to one helper (MEDIUM, backend).

**Phase 4 — Sustainability (do alongside or after the above, not blocking)**
15. Add frontend CI (`tsc`/`build`/lint gate) and Dependabot for both ecosystems.
16. Split `App.tsx` into components and add a test runner (Vitest) — HIGH-8; this is what makes every fix above actually regression-proof going forward.
17. Address responsive design (HIGH-7) and the accessibility findings (icon labels, skip links, focus management, form labels) — best done as part of the component-split work in #16, since each extracted component is a natural place to fix its own accessibility gaps.
18. Clean up stale infra config (`render.yaml`'s unused service) and add a `HEALTHCHECK` + non-root user to the backend Dockerfile.

No fixes have been applied. This document is the deliverable for this audit pass — let me know which phase (or which specific items) you'd like tackled first, and I'll scope and implement those as a separate, focused change.
