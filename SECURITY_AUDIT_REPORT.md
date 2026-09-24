# Security Audit — Competitor Video Intelligence Dashboard

Date: 2026-09-24
Scope: full backend (`backend/app/**`), frontend (`src/**`), and deployment
config (`nginx.conf`, `vercel.json`, `render.yaml`, `docker-compose.yml`,
`backend/Dockerfile`).

Method: manual source review of every router, scraper, and config file;
`pip-audit` against `backend/requirements.txt`; `pnpm audit` against
`pnpm-lock.yaml`; targeted reproduction of the exception-message leak
(below) against the real `googleapiclient` library to confirm exploitability
before reporting it, not just suspecting it.

Findings are ranked by real-world impact given how this app is actually
deployed (a small-team dashboard, publicly reachable, no user accounts —
see `PRODUCTION_ROADMAP.md`'s own "Phase 2" notes, which already flag some
of what's below as accepted, documented risk). Each entry says whether it
was fixed in this pass.

---

## CRITICAL

### C1. YouTube API key disclosure via exception messages on unauthenticated endpoints — **FIXED**

**Where:** `app/scrape_service.py`, `app/routers/search.py`, `app/routers/scrape.py`, `app/scrapers/instagram.py`

**The bug:** `YouTubeClient` is built with `build("youtube", "v3", developerKey=api_key)`. `google-api-python-client` appends that key to every request as a plain `key=...` **query parameter**, not a header — confirmed directly:

```
https://youtube.googleapis.com/youtube/v3/channels?part=snippet&id=...&key=<YOUTUBE_API_KEY>&alt=json
```

When a request fails, the library's `HttpError` embeds the **full request URL** in both `repr()` and `str()`. Several places in this codebase did `except Exception as exc: ... f"{exc}"` and then either stored the result in `ScrapeRun.error_message` or returned it directly in an HTTP response `detail`:

- `POST /api/search/topic` — **no authentication at all** — caught a failed YouTube call and returned `f"Topic search failed: {exc}"` straight in a 502 response body.
- `POST /api/scrape/run-manual` — also **no authentication**, only a cooldown — funnels into `run_daily_scrape`, whose per-channel exception handler stored the raw exception text into `ScrapeRun.error_message`.
- `GET /api/scrape/runs` — **no authentication**, returns every `ScrapeRun` including `error_message`, verbatim, to anyone.

**Exploit path (verified, not theoretical):** `POST /api/search/topic` with a filter YouTube rejects — an invalid `region` (no ISO-3166 validation exists on that field) is enough — triggers an `HttpError`, and the real `YOUTUBE_API_KEY` comes back in the 502 response body to whoever sent the request. No credentials, no waiting, no access to logs needed. I reproduced this locally against the real `HttpError` class to confirm the key is genuinely embedded (see reproduction below) — I did not run this against any live deployment.

```
raw str(exc): <HttpError 400 when requesting https://youtube.googleapis.com/youtube/v3/search?...&key=AIzaSy...REDACTED...&q=test returned "...">
```

**Fix:** added `app/error_safety.py` with `safe_error_message(exc)`, which builds a message from `HttpError.status_code`/`.reason` only (never `.uri`, which is where the key lives), and as a backstop, regex-redacts any `key=`/`token=`/`secret=`-shaped query parameter from any other exception's text (covers the Apify client or any future dependency the same way). Applied at every site that persists or returns an exception's text:

- `app/scrape_service.py` — all three `except Exception` blocks
- `app/routers/search.py` — the topic-search failure handler (both the stored `error_message` and the returned `detail`)
- `app/routers/scrape.py` — `check-velocity`'s failure handler
- `app/scrapers/instagram.py` — both Apify-call failure handlers (defense in depth; Apify's client is less likely to embed its token in a URL, but there's no reason to trust that blindly)

Verified: diagnostic value is preserved (`HTTP 400: API key not valid. Please pass a valid API key.` instead of the raw string), the key is completely absent, and all 154 existing backend tests still pass unchanged.

**Residual note (not fixed, lower severity):** `logger.exception(...)` calls at these same sites still log the *unredacted* exception server-side. That's a much smaller exposure — only whoever has access to Render's log stream (the account owner) can see it, not the public internet — so I left it as-is rather than making server-side diagnostics less useful; flagging it here so it's a deliberate choice, not an oversight.

---

## HIGH

### H1. No authentication on state-mutating and data-reading endpoints — **known, documented, NOT changed**

**Where:** `POST /api/channels`, `PATCH/DELETE /api/channels/{id}`, `PATCH /api/settings/scraper`, `POST /api/scrape/run-manual`, `POST /api/search/topic`, and every `GET` endpoint.

Only `POST /api/scrape/run` and `POST /api/scrape/check-velocity` require the `X-API-Key` header (`SCRAPE_TRIGGER_API_KEY`, via `app/deps.py::require_scrape_api_key`, which correctly fails closed if the secret is unset). Everything else — adding/removing tracked channels, toggling Instagram scraping, triggering a scrape, running a topic search that spends real YouTube quota, and reading the entire tracked dataset — is reachable by anyone who has the URL, no credential of any kind.

This is already known and documented: `PRODUCTION_ROADMAP.md`'s security checklist says outright *"anyone who can reach the API can read all tracked data and manage the channel roster"* and its Phase 2 section calls out adding real authentication before wider sharing. I'm not treating this as a "found it, you didn't know" item — I'm keeping it in the report because the task asked for a prioritized list of what's actually true today, and this is the single largest gap by real impact (anyone can silently delete every tracked channel).

**Why not fixed here:** adding real authentication changes intended functionality — the dashboard currently has no login flow, no user model, and the frontend calls every endpoint with a bare `fetch()` — and the task scope is "fix what can be fixed without changing functionality." There's no halfway version of this that's both safe and non-breaking; a shared static API key checked client-side would just move the same secret into the JS bundle, giving no real protection while adding a false sense of one. I left this exactly as `PRODUCTION_ROADMAP.md` already recommends: real auth (even HTTP Basic in front of nginx) before this is shared beyond a trusted team, which it currently is not (it's a live public URL right now, per the earlier deployment work in this project).

### H2. Rate limiting exists, but only as a global cooldown, not per-caller — **not changed, lower priority than it first appears**

`POST /api/scrape/run-manual` and `POST /api/search/topic` are both protected by a **global** cooldown (keyed off the single most recent `ScrapeRun`/`TopicSearchCache` row, not per-IP). This does cap total quota/cost burn effectively — no one, from any number of IPs, can trigger either faster than once per cooldown window — which is the actual threat this exists to prevent (YouTube quota / Apify credit exhaustion), and it already works for that. What it doesn't prevent is one bad actor holding the cooldown hostage for everyone else (an availability/fairness concern, not a data-exposure one). I didn't add per-IP rate-limiting middleware on top of this: it would be new infrastructure for a threat model (fairness, not cost) that isn't what these endpoints were built to guard against, and risks scope creep into "changing functionality" territory the task asked me to avoid. Noting it here as a conscious trade-off rather than a silent gap.

---

## MEDIUM

### M1. Stored XSS via unvalidated third-party (Apify actor) URL — **FIXED**

**Where:** `app/scrapers/instagram.py::normalize_instagram_item`

`Video.external_url` for an Instagram post was taken directly from the Apify actor's raw `url` field with no validation: `_first_present(raw, "url", default=f"https://www.instagram.com/p/{shortcode}/")`. That value is later rendered on the frontend as a clickable link with no further checks:

```tsx
const wrapperProps = video.url ? { href: video.url, target: "_blank", rel: "noreferrer" } : {};
```

React does not sanitize `href` values for a `javascript:` scheme. This module's own docstring already warns that "Apify actor output schemas are not standardized... and change when actor authors update them" — meaning the actual shape of that `url` field isn't something this app fully controls. A misbehaving, buggy, or compromised actor returning `javascript:...` in that field would become a stored-XSS payload that fires when a teammate clicks the video card, in the dashboard's own origin.

I checked the rest of the frontend for the same class of bug: no `dangerouslySetInnerHTML`/`innerHTML` anywhere in `src/`, every other `target="_blank"` link already has `rel="noreferrer"`, and image `src` values (thumbnails, avatars) aren't exploitable this way since browsers don't execute a `javascript:` URI used as an image source. This was the one real gap.

**Fix:** added `_safe_external_url()` — only accepts a value starting with `http://`/`https://`; anything else (including a missing field) falls back to the same canonical `https://www.instagram.com/p/{shortcode}/` URL the code already used when the actor omitted `url` entirely. Behavior is unchanged for every legitimate actor response; only a malformed/malicious value is now replaced rather than stored. Verified against the existing Instagram-parsing test suite (`test_instagram_parsing.py`, `test_instagram_scraper.py`) — all still pass.

### M2. No security response headers anywhere in the stack — **FIXED**

Neither the FastAPI backend, `nginx.conf` (self-hosted path), nor `vercel.json` (Vercel path) set any of `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, or `Permissions-Policy`. In particular, the dashboard's own HTML had no clickjacking protection — nothing stopped another site from framing it.

**Fix:** added a small `@app.middleware("http")` in `backend/app/main.py` that sets `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`, `Permissions-Policy: geolocation=(), camera=(), microphone=()`, and `Strict-Transport-Security` (harmless no-op over plain HTTP, so it doesn't affect local `uvicorn --reload` dev) on every API response. Added the equivalent `add_header` directives to `nginx.conf` and a matching `headers` block to `vercel.json` so the dashboard's actual HTML page gets the same protection regardless of which of the two documented deployment paths is used. Verified live via a test request — all headers present, nothing else changed.

I deliberately did **not** add a Content-Security-Policy: the frontend uses inline `style={{...}}` extensively throughout `src/App.tsx`, and a CSP strict enough to be worth adding would need `style-src 'unsafe-inline'` or a full nonce/hash rework to avoid breaking the entire UI's styling — that's a real, separate project, not a safe drop-in fix, so I'm flagging it rather than guessing at a policy that might break the app in production without a full manual QA pass.

### M3. Unnecessary `allow_credentials=True` in CORS config — **FIXED**

`app/main.py`'s CORS middleware had `allow_credentials=True`, but this app has no cookies, no sessions, and `src/lib/api.ts`'s `fetch()` wrapper never sets `credentials` — confirmed by reading it end to end. This flag was dead configuration whose only effect is to widen what a future misconfiguration of `CORS_ORIGINS` (e.g., accidentally including an untrusted origin) could get away with. Changed to `allow_credentials=False`; verified no `Access-Control-Allow-Credentials` header is sent and all tests still pass. This doesn't change any actual request the frontend makes today.

---

## LOW

### L1. `GET /docs` / `/redoc` / `/openapi.json` are public
FastAPI's interactive docs are enabled by default and expose every endpoint's exact shape to anyone. Given H1 (no auth on almost everything anyway), this mostly speeds up reconnaissance rather than granting new access — I left it as-is since disabling it would need a judgment call about whether the team still wants it for their own reference, which isn't mine to make unilaterally.

### L2. Backend Docker image runs as root
`backend/Dockerfile` has no `USER` directive, so the container runs as root. Not directly exploitable on its own, but it's a missing defense-in-depth layer if any other vulnerability (in this app or a dependency) ever allowed code execution inside the container. Not changed in this pass — it's a reasonable hardening step but touches the image's file permissions and entrypoint script, and I'd rather flag it than make an under-tested change to how the container starts.

### L3. Sensitive data reaches application logs
As noted in C1's residual note, `logger.exception(...)` still logs unredacted exception text (including, potentially, the real API key) to whatever log sink the host uses. Only the account owner can see Render's/Docker's logs, so this is a much narrower exposure than the public-endpoint version that's now fixed, but worth knowing about if logs are ever shared for debugging.

### L4. Dependencies — clean at time of audit
`pip-audit` against `backend/requirements.txt` and `pnpm audit` against `pnpm-lock.yaml` both came back with **no known vulnerabilities**. This is a point-in-time result, not a guarantee — worth re-running periodically (e.g., as a CI step) rather than treating as permanently clean.

---

## Checked and found not applicable / already handled correctly

- **SQL / NoSQL injection** — the entire backend goes through SQLAlchemy's ORM query builder; the one raw-SQL usage (`app/routers/health.py`: `db.execute(text("SELECT 1"))`) is a hardcoded literal with no user input anywhere near it. No string-formatted queries found anywhere.
- **Command injection** — no `subprocess`, `os.system`, `eval`, or `exec` anywhere in `app/`.
- **Insecure deserialization** — no `pickle`, no `yaml.load` (unsafe form), nothing that deserializes untrusted input beyond Pydantic's own validated request models.
- **SSRF** — every outbound call goes through a fixed-base-URL client (`googleapiclient` for YouTube, `apify_client` for Apify, `httpx` for SponsorBlock with a server-configured base URL). The one place user input touches channel resolution (`resolve_channel_input` in `app/scrapers/youtube.py`) does pure local string parsing — it never fetches the URL a user pastes in.
- **Path traversal** — no endpoint constructs a filesystem path from request input.
- **File upload vulnerabilities** — there are no file upload endpoints in this app (no `UploadFile`/`File(...)` usage anywhere).
- **Open redirects** — no `RedirectResponse` or redirect logic anywhere in the backend.
- **Insecure cookies / missing HttpOnly / missing Secure / missing SameSite** — not applicable; this app sets no cookies at all.
- **CSRF** — not applicable in the traditional sense: CSRF relies on a browser automatically attaching ambient credentials (cookies) to a forged cross-site request. This app has zero cookie/session-based auth, so there's no ambient credential for a forged request to ride on. (The real access-control problem is H1 — no credential is required in the first place — not CSRF specifically.)
- **Weak session management / JWT problems / token leakage** — not applicable; there are no sessions and no JWTs anywhere in this codebase.
- **IDOR / privilege escalation** — subsumed by H1: every "object" (channel, scrape run, workspace setting) is reachable by anyone regardless of any identifier, because there's no notion of "whose" resource it is yet. Fixing this properly means the same authentication work called out in H1, not a separate per-object check.
- **Verbose production errors / stack traces** — FastAPI's default unhandled-exception behavior (no custom exception handler was found that echoes tracebacks) returns a generic 500 with no stack trace to the client; `debug`/`reload` are dev-only (`uvicorn --reload`, only ever mentioned in a docstring, never in the Dockerfile's `CMD`).
- **Source map exposure** — `vite.config.ts` only emits inline sourcemaps when `mode === 'development'`; a production `vite build` ships none (confirmed via the last production build in this session: no `.map` files in `dist/assets/`).
- **Hardcoded secrets / exposed API keys** — none found. `.env` is correctly gitignored, `.env.example` only contains placeholders (`REPLACE_WITH_...`), and a full-repo grep for key-shaped literals and AWS/GCP key patterns turned up nothing beyond test fixtures using an obviously fake `"test-secret"`.

---

## Files changed in this pass

| File | Change |
|---|---|
| `backend/app/error_safety.py` | **New** — `safe_error_message()`, the fix for C1 |
| `backend/app/scrape_service.py` | Use `safe_error_message()` at all 3 exception sites |
| `backend/app/routers/search.py` | Use `safe_error_message()` for the topic-search failure path |
| `backend/app/routers/scrape.py` | Use `safe_error_message()` for the velocity-check failure path |
| `backend/app/scrapers/instagram.py` | `safe_error_message()` at both Apify error sites; `_safe_external_url()` fix for M1 |
| `backend/app/main.py` | Security-headers middleware (M2); `allow_credentials=False` (M3) |
| `vercel.json` | Security headers for the Vercel-hosted frontend (M2) |
| `nginx.conf` | Security headers for the self-hosted/Docker frontend (M2) |

**Verification performed:** full backend test suite (154/154 passing, unchanged), a live reproduction of the API-key leak against the real `HttpError` class before and after the fix, a live request confirming every new response header is present and `Access-Control-Allow-Credentials` is now absent, and a re-run of `pip-audit`/`pnpm audit` (both clean).
