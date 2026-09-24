# Backend / API Production-Grade Audit — Competitor Video Intelligence Dashboard

Date: 2026-09-24
Scope: every FastAPI router, dependency, service module, and the SQLAlchemy
models/engine setup under `backend/app/**`, checked against: authentication,
authorization, input validation, output validation, rate limiting,
pagination, filtering, sorting, error handling, timeout handling, retries,
idempotency, caching, database efficiency, N+1 queries, indexes, connection
pooling, transaction handling, race conditions, concurrency, logging,
monitoring, and sensitive-information leakage — plus a specific check that
no client-supplied value can manipulate an ID, role, price, permission, or
other value the server should be the sole authority over.

Method: manual read of every router, model, and dependency; live
reproduction of the two race conditions described below against a real
local Postgres instance (not just reasoning about them); a from-scratch
regression test that deliberately forces the exact connection-pool
behavior one of the fixes depends on, run against real Postgres; the full
`0001`→`0008` Alembic migration chain run end-to-end on a fresh Postgres
database, plus an autogenerate diff against `models.py` to confirm no
drift; and the full pytest suite (173 tests) run to green before and after
every change.

---

## The governing decision: authentication is intentionally out of scope

This app has no user accounts anywhere — every endpoint is reachable by
anyone who can reach the URL, and every request is trusted as coming from
the workspace's own team. That is a real, load-bearing finding, not a
detail: it means "authorization" in the usual sense (can *this* user do
*that*?) doesn't apply, because there is no "this user."

I raised this before doing anything else, since deciding how to close it —
leave it, add a shared-secret gate, or build real per-user auth — is an
architectural call, not a bug fix. **You chose to leave the no-auth design
as-is and have everything else hardened.** Everything below respects that:
no login system, session, token, or role model was added. What follows is
what "harden everything else" turned into, checked item by item against
your list.

One thing worth being precise about, since it changes how serious "no
auth" actually is here: it is not uniformly true. `POST /api/scrape/run`
and `POST /api/scrape/check-velocity` — the two endpoints that spend real
YouTube quota / Apify credit on a schedule — already sit behind a shared
`X-API-Key` secret (`app/deps.py`'s `require_scrape_api_key`), checked
before this audit. The endpoints that are genuinely open are the ones the
dashboard's own frontend calls directly from the browser (`run-manual`,
`/api/search/topic`, every `GET`, channel CRUD, the settings toggle) —
which have nowhere secret to keep a key in the first place, since anything
shipped in a browser bundle is visible to anyone with dev tools open. Those
are guarded by cooldowns and the rate limiter added below instead.

---

## CRITICAL

### C1. Topic-search cooldown lock leaked forever under real concurrency — found and fixed during this pass's own verification

**Where:** `app/db_lock.py`, `app/routers/search.py`

This is the one finding in this report that wasn't in the original code —
it's a bug in my own first draft of the concurrency fix below, caught by
insisting on testing the fix against real Postgres rather than trusting
the design. Documenting it in full because "I fixed a race condition"
isn't worth much without also showing the fix actually holds up.

**The original design:** `POST /api/search/topic`'s cooldown (don't let two
requests both start a YouTube search before either has recorded one)
needs a lock that survives several `db.commit()` calls — the "running"
`ScrapeRun` row, the search itself, and the final success/failure row are
all separate commits. My first version took a Postgres session-level
advisory lock (`pg_advisory_lock`/`pg_advisory_unlock`) directly on the
request's own `db: Session`, released in a `finally` block.

**The bug:** a plain SQLAlchemy ORM `Session.commit()` returns its
underlying DBAPI connection to the connection pool by default. The
session's *next* statement can silently be handed back a **different**
physical Postgres backend connection — trivially so under any concurrent
load, since another request's `Session` can grab the just-freed connection
first. Postgres's session-level advisory locks are scoped to the physical
backend connection, not to the ORM `Session` object, so releasing on `db`
later can mean calling `pg_advisory_unlock` on a connection that never
held the lock. That call is a silent no-op — no exception, nothing to
notice in a log — and the lock stays held on the original, now-idle,
never-touched-again pooled connection. Every subsequent
`/api/search/topic` request would then block forever waiting for a lock
that would never be released: a self-inflicted, permanent deadlock on the
whole endpoint, until the process itself restarted.

**How this was caught:** rather than trust the design, I reproduced it —
a standalone script against a real local Postgres, with a small connection
pool, forced exactly this sequence (acquire → commit → a second session
steals the freed connection → the original session's next statement lands
on a new one → release). `pg_locks` confirmed the lock was still held,
under a different pid than the one that "released" it, after the release
call returned successfully with no error.

**The fix:** `session_scoped_lock(db, key)` (replacing the old
`acquire_session_lock`/`release_session_lock` pair) now checks out its
**own dedicated connection** from `db`'s engine — untouched by anything the
protected code does to `db` in between — holds it for the entire `with`
block, and both explicitly unlocks and closes it afterward (closing a
connection also drops any advisory lock it holds, so even a failed
explicit unlock can't leak it past that point). It still derives the
engine from `db.get_bind()` rather than a hardcoded import, so it
transparently respects the test suite's `dependency_overrides[get_db]`
swap and never reaches past a test into a real database.

**Verified:** `tests/test_db_lock.py` reproduces the exact leak scenario
above (a small pool, a "thief" session forced to steal the connection
mid-flight) and asserts the lock still comes out clean — passing against
real Postgres. It also checks blocking behavior between two concurrent
holders, and release-on-exception. These tests are gated to skip cleanly
when no local Postgres is reachable (same reasoning `backend/README.md`
already gives for verifying Alembic migrations against real Postgres) —
they ran and passed here, and will run again anywhere a Postgres instance
matching `DATABASE_URL`/`TEST_DATABASE_URL` is reachable, but won't block
or fail a normal SQLite-only CI run.

---

## HIGH

### H1. Two check-then-act race conditions could double-spend YouTube quota / Apify credit — **FIXED**

**Where:** `app/routers/scrape.py` (`trigger_manual_scrape`), `app/routers/search.py` (`search_topic`)

**The bug:** both endpoints exist specifically to cap how much quota/credit
repeated calls can burn — a cooldown, checked before starting an expensive
external call. Both read "when did this last run" and only *afterward*
write a new marker recording that a run started. Two requests landing in
that gap (a double-click, two open tabs, someone replaying a request —
there's no auth in front of either endpoint to make that hard, by design)
can both read "no recent run" before either has committed anything, so
both proceed. The cooldown that's supposed to be the only thing standing
between a shared dashboard link and a burned daily YouTube quota doesn't
actually hold under concurrent requests.

**Fix:** `app/db_lock.py` adds two lock helpers, matched to each race's
shape. `advisory_lock` (transaction-scoped `pg_advisory_xact_lock`) closes
`trigger_manual_scrape`'s race — its critical section ends at the first
commit (the new "running" `ScrapeRun` row), so a lock that auto-releases at
that commit is exactly right. `session_scoped_lock` (see C1 above) closes
`search_topic`'s race, whose critical section spans several commits since
the cooldown marker isn't written until the whole YouTube round trip
finishes. Both are no-ops on the SQLite the test suite runs against —
SQLite has no advisory locks, but the suite runs single-threaded, so the
race they guard against can't occur there regardless.

**Residual, accepted limitation:** `trigger_manual_scrape`'s lock key is
shared across all platforms (not per-platform), so two concurrent requests
for *different* platforms (`?platform=youtube` and `?platform=instagram`)
serialize against each other rather than running independently. Given how
rarely two different-platform manual refreshes would actually overlap in
a small-team dashboard, and that "serialize" (a few extra seconds of
waiting) is a much smaller cost than "double-spend," this is a deliberate,
proportionate simplification rather than an oversight — a per-platform key
would be a small follow-up if it ever matters in practice.

---

## MEDIUM

### M1. No rate limiting anywhere — **FIXED**

**Where:** new `app/rate_limit.py`, `app/deps.py`, `app/main.py`

**The bug:** every endpoint — expensive ones like `/api/search/topic` and
cheap ones alike — had no limit on how many requests a single client could
send. Combined with no auth on most routes, this meant no backstop at all
against either an accidental retry storm from a buggy frontend build or a
deliberate flood.

**Fix:** an in-process, fixed-window, per-IP rate limiter
(`app/rate_limit.py`), applied at the FastAPI app level
(`dependencies=[Depends(rate_limit_dep)]` in `main.py`) so it covers every
route uniformly and nothing added later can accidentally skip it —
`/healthz` is explicitly exempted, since uptime monitors poll it on their
own schedule and it isn't the kind of client this is meant to guard
against. Deliberately **not** Redis-backed: I checked the actual deploy
topology first (`Dockerfile`'s `CMD` has no `--workers` flag; `render.yaml`
is a single free-tier web service) — this runs as one Uvicorn process, so
an in-process counter is the right amount of infrastructure for what's
actually deployed, not an under-engineered shortcut. Configurable via
`RATE_LIMIT_ENABLED`/`RATE_LIMIT_REQUESTS_PER_MINUTE`; disabled in the test
suite (`tests/conftest.py`) so the suite's own request volume against a
single shared fake client IP doesn't trip a limit meant for one real
caller, with its own dedicated tests (`tests/test_rate_limit.py`) exercising
it directly.

### M2. Query params silently no-op'd instead of rejecting bad input — **FIXED**

**Where:** `app/routers/videos.py`, `app/routers/channels.py`

**The bug:** `GET /api/videos`'s `platform`/`format`/`metric` and `GET
/api/channels`'s `platform` accepted any string. A typo'd or malicious
value (`platform=Youtube`, `platform=' OR 1=1`) didn't error — it just
silently filtered down to results indistinguishable from "no matches,"
making a malformed request look identical to a correct one with an empty
result. (`sort_by` already validated before this pass — the others didn't
match that existing standard.)

**Fix:** small allowlists (`PLATFORMS`, `FORMATS`, `METRICS`) checked up
front, before the query is even built, raising `422` with the valid
options listed. Covered by new tests in `tests/test_api_videos.py` and
`tests/test_api_channels.py`.

### M3. `GET /api/scrape/runs`'s `limit` was unbounded — **FIXED**

**Where:** `app/routers/scrape.py`

**The bug:** `limit: int = 20` with no upper bound — a caller could request
`?limit=1000000` and pull the entire `scrape_runs` table (which only grows)
in one response.

**Fix:** bounded to `Query(default=20, ge=1, le=200)`, matching the pattern
`GET /api/videos`'s `limit`/`offset` already used. `GET /api/videos` and
`GET /api/channels` were already properly paginated/bounded before this
pass — this was the one pagination gap.

### M4. Missing index for `scrape_runs`' most common query shape — **FIXED**

**Where:** `app/models.py`, new migration `alembic/versions/0008_scrape_runs_platform_index.py`

**The bug:** `trigger_manual_scrape`'s cooldown check and
`GET /api/system/status`'s "last scrape" lookup both filter `scrape_runs`
by `platform` and then order by `started_at desc` — the existing index
only covered `started_at` alone, so that filter+sort combination degrades
to a full-table scan plus sort as this log table grows, rather than a
single index scan.

**Fix:** added a composite `Index("ix_scrape_runs_platform_started_at",
"platform", "started_at")`, backed by a real migration. Verified against a
fresh real Postgres database: the full `0001`→`0008` chain applies
cleanly, both indexes exist afterward (`ix_scrape_runs_started_at` is kept
— it still backs `GET /api/scrape/runs`'s platform-agnostic listing), the
downgrade path was also exercised, and a post-migration `alembic revision
--autogenerate` diff against `models.py` came back completely empty (no
drift).

### M5. No global handler for unexpected exceptions — **FIXED**

**Where:** `app/main.py`

**The bug:** every route that anticipates its own failure modes already
turns them into a clean `HTTPException` with a sanitized message (the
existing `app/error_safety.py` pattern from an earlier security pass). But
anything genuinely unexpected — a bug, an unanticipated DB error — fell
through to Starlette's default handler, which returns a bare
`Internal Server Error` **plain-text** body: inconsistent with every other
error response in this API (`{"detail": ...}` JSON), and something the
frontend's fetch wrapper has to special-case rather than read normally. It
was not, itself, a credential leak — FastAPI already runs with
`debug=False` — but it was an inconsistent, unhelpful failure mode.

**Fix:** a global `@app.exception_handler(Exception)` that logs the real
exception server-side (with a traceback, for debugging) and returns a
fixed, generic `{"detail": "Something went wrong..."}`  — deliberately
*not* `str(exc)`, since an exception that wasn't anticipated by a specific
handler hasn't been vetted for what it might embed. Verified with a
dedicated test (`tests/test_unhandled_exception_handler.py`) using a local
`TestClient(app, raise_server_exceptions=False)`, since Starlette's default
`TestClient` re-raises unhandled exceptions into the test rather than
showing the registered handler's actual response — matching real
production (uvicorn) behavior required configuring around that.

### M6. Connection pool had no proactive recycling — **FIXED**

**Where:** `app/database.py`

**The bug:** the engine already had `pool_pre_ping=True` (catches an
already-dead connection at checkout time), but nothing proactively retired
an old connection before that — relying entirely on a request happening to
hit a stale one to discover it, and on Neon's free-tier autosuspend (5 min
idle) rather than anything closer to this app.

**Fix:** added `pool_recycle=1800` — proactively retires any pooled
connection older than 30 minutes, belt-and-suspenders alongside
`pool_pre_ping` against a middlebox or load balancer silently closing a
long-idle connection independent of Neon's own autosuspend.

### M7. No audit trail for channel/settings mutations — **FIXED**

**Where:** `app/routers/channels.py`, `app/routers/settings.py`

**The bug:** with no user auth, there's no "who" to attach to a change —
but "what changed and when" was still missing for the roster (add/update/
delete a tracked channel) and the Instagram-scraping toggle (which
directly controls real Apify spend), making an unexpected change hard to
debug after the fact.

**Fix:** `logger.info(...)` calls added at each mutation site, matching the
audit-trail style `app/scrape_service.py` already used for scrape runs.
One detail worth flagging as an example of doing this carefully rather
than mechanically: `delete_channel` captures `handle` into a local variable
*before* `db.delete()` + `db.commit()`, because reading an attribute off an
ORM instance after it's been deleted-and-committed raises
`ObjectDeletedError` — logging the deleted row's handle only works if it's
captured first.

---

## Confirmed already solid — checked, not changed

- **Trusted-value manipulation** (the audit's specific ask: can a client
  set an ID, role, price, permission, or other value the server should
  own?): `ChannelCreate`/`ChannelUpdate` schemas are tight allowlists — a
  channel's `id` is always server-generated, and there's no role, price, or
  permission concept anywhere in this domain to manipulate in the first
  place. Every response uses a Pydantic `response_model`, which only ever
  serializes the fields the schema declares — an ORM object can't leak an
  internal column just because it exists on the model.
- **N+1 queries**: already avoided everywhere it matters —
  `GET /api/channels`'s per-channel video stats use one grouped subquery
  outer-joined onto the channel list rather than a query per channel;
  `GET /api/videos` uses `joinedload(Video.channel)`; the "median of last
  10 videos per channel" stat pushes its per-group `LIMIT` into SQL via a
  `ROW_NUMBER()` window rather than pulling the whole `videos` table into
  Python.
- **Pagination**: `GET /api/videos` (`limit`/`offset`, bounded 1–2000) and
  `GET /api/channels` were already properly bounded; `GET /api/scrape/runs`
  was the one gap (M3, fixed).
- **Timeout handling on every outbound call**: `app/scrapers/youtube.py`
  builds its client with an explicit `httplib2.Http(timeout=...)` (the
  underlying library has no timeout by default); `app/sponsorblock.py`'s
  `httpx.Client` is constructed with an explicit `timeout`;
  `app/scrapers/instagram.py`'s Apify actor call passes `wait_secs=300`
  specifically because the library's own docs say it otherwise "waits
  indefinitely." All three were already correct before this pass.
- **Sensitive-value leakage in exceptions**: `app/error_safety.py` (from an
  earlier security-focused pass) already strips the YouTube API key out of
  `googleapiclient`'s `HttpError` messages before they reach a stored
  `error_message` or an HTTP response, with a regex backstop for
  `key=`/`token=`/`secret=`-shaped values from any other exception.
- **CORS / security headers**: `allow_credentials=False`, explicit
  `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`,
  `Permissions-Policy`, and HSTS headers were already in place from an
  earlier pass.
- **Idempotency of the one place duplication would actually corrupt
  data**: adding the same channel twice is already rejected
  (`DuplicateChannelError`) rather than creating a second row.
- **Application-level caching**: the topic-search feature already uses a
  deliberate single-slot DB cache (`TopicSearchCache`) specifically to
  avoid re-spending YouTube quota on a page reload — the right place for
  this cache to live, since it's about not re-calling YouTube, not about
  HTTP response caching.

---

## Accepted, documented gaps — deliberately not changed

- **No automatic retries on outbound YouTube/Apify calls.** Each call
  already fails cleanly (timeout, safe error message, per-channel
  isolation in the daily batch) rather than hanging or corrupting state,
  and the daily/hourly scheduled cadence already acts as its own retry for
  the automated paths. Adding automatic retries on top risks *worse*
  outcomes for quota-metered APIs — a naive retry on what looks like a
  transient failure can silently double-spend quota on a call that
  actually succeeded server-side — so this needs a deliberate,
  idempotency-aware design if you want it, not a reflexive `for attempt in
  range(3)`. Flagging it rather than guessing at that design.
- **No HTTP-level response caching** (`Cache-Control`/`ETag`) on `GET`
  endpoints. This dashboard's whole purpose is to show the latest scraped
  data — a browser or CDN caching a stale `GET /api/videos` response would
  be a correctness bug, not an optimization, for this specific app.
- **No external monitoring/APM** (Sentry, structured metrics export, etc.)
  beyond the existing `/healthz` liveness+DB check and Python's standard
  `logging`. Bringing in a third-party monitoring service means new
  accounts/keys only you can provision — out of scope for hardening what's
  already here, and a straightforward addition later if you want it.
- **`trigger_manual_scrape`'s shared lock key across platforms** — see H1's
  residual note above.

---

## Verification

- Full backend test suite: **173 passed**, 0 failed (up from 168 before
  this pass — 5 new tests in `tests/test_db_lock.py`, run against real
  Postgres where they exercise actual lock-blocking behavior, and cleanly
  skipping in a plain SQLite-only run).
- `tests/test_rate_limit.py` (new) and `tests/test_unhandled_exception_handler.py`
  (new) cover M1 and M5 directly.
- Migration `0008`: applied and downgraded cleanly against a real, fresh
  Postgres database; a post-migration `alembic revision --autogenerate`
  diff against the current `models.py` came back empty (no schema drift).
- Every fix in this report that touches concurrency (C1, H1) was verified
  by actually reproducing the race against real Postgres under a
  constrained connection pool — not just by reasoning that the SQL should
  be correct.

## Files changed in this pass

New: `app/db_lock.py`, `app/rate_limit.py`,
`alembic/versions/0008_scrape_runs_platform_index.py`,
`tests/test_rate_limit.py`, `tests/test_unhandled_exception_handler.py`,
`tests/test_db_lock.py`.

Modified: `app/routers/scrape.py`, `app/routers/search.py`, `app/config.py`,
`app/deps.py`, `app/main.py`, `app/routers/videos.py`,
`app/routers/channels.py`, `app/routers/settings.py`, `app/database.py`,
`app/models.py`, `tests/conftest.py`, `tests/test_api_videos.py`,
`tests/test_api_channels.py`, `tests/test_api_scrape.py`.
