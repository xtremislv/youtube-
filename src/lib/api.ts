/**
 * Thin fetch wrapper around the FastAPI backend (see backend/app/main.py).
 *
 * Every type here mirrors a Pydantic response schema field-for-field (the
 * backend's CamelModel produces exactly these camelCase shapes — see
 * backend/app/schemas.py) so App.tsx can treat API responses the same way
 * it used to treat the old hardcoded CHANNELS/VIDEOS mock arrays.
 *
 * API_BASE resolves to:
 *   - "" (same-origin, e.g. "/api/videos") when VITE_API_BASE_URL is unset
 *     — this is what the Docker Compose / nginx setup uses (nginx proxies
 *     /api/* to the backend container) and what `pnpm run dev` uses (Vite's
 *     dev-server proxy in vite.config.ts).
 *   - the full backend URL (e.g. "https://your-api.onrender.com") when
 *     VITE_API_BASE_URL is set at build time — this is what a split
 *     deployment (frontend on Vercel, backend on Render) needs, since the
 *     two are served from different origins.
 */

const API_BASE = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "") ?? "";

export type Platform = "youtube" | "instagram" | "all";

export interface ApiChannel {
  id: string;
  name: string;
  platform: Exclude<Platform, "all">;
  avatar: string;
  avatarUrl: string | null;
  subs: string;
  subscriberCount: number | null;
  handle: string;
  cohort: string | null;
  isActive: boolean;
  // Derived from this channel's videos server-side (see ChannelOut in
  // backend/app/schemas.py) — null/0 until the channel has been scraped
  // at least once. Backs the Competitor Roster's channel card.
  avgViews: number | null;
  // Median views across the channel's 10 most recently published videos
  // (YouTube or Instagram alike) — a separate, more outlier-resistant stat
  // from avgViews above, which is a plain mean over the channel's entire
  // history. Backs the "Median (last 10)" line on the channel card.
  medianViewsLast10: number | null;
  videoCount: number;
  lastPublishedAt: string | null; // "YYYY-MM-DD"
}

export type OverperformMetric = "average" | "median";

export interface ApiVideo {
  id: string;
  channelId: string;
  channelName: string;
  platform: Exclude<Platform, "all">;
  title: string;
  thumbnail: string | null;
  url: string | null;
  views: number;
  avgViews: number | null;
  medianViews: number | null;
  likes: number | null;
  comments: number | null;
  publishedAt: string; // "YYYY-MM-DD"
  duration: string; // "MM:SS" or "H:MM:SS"
  format: "short" | "long" | "reel";
  overperformRatio: number | null;
  overperformRatioMedian: number | null;
  // SponsorBlock (see backend/app/sponsorblock.py) — YouTube-only; an
  // Instagram video always reports false/null since there's no equivalent
  // data source scraped for it.
  hasSponsorSegment: boolean;
  sponsorSegmentSeconds: number | null;
  // Early-velocity checkpoints (see backend/app/velocity.py) — YouTube-only,
  // and only populated going forward from whenever that feature shipped, so
  // most videos report null/null for all three. Each pair is null until
  // that checkpoint either lands within its grace window or permanently
  // misses it — render "—", not 0.
  h1Views: number | null;
  h1Ratio: number | null;
  h3Views: number | null;
  h3Ratio: number | null;
  h6Views: number | null;
  h6Ratio: number | null;
}

export interface VideoQuery {
  platform: Platform;
  channels: string[];
  dateFrom: string;
  dateTo: string;
  viewsThreshold: string;
  format: string;
  sortBy: string;
  // Which trailing baseline (mean vs. median) drives sortBy="ratio" and the
  // returned overperformCount — see backend/app/routers/videos.py. Every
  // video's response always carries both avgViews/overperformRatio *and*
  // medianViews/overperformRatioMedian regardless of this, so a frontend
  // toggle between them never needs a re-fetch on its own.
  metric?: OverperformMetric;
  // true = only videos SponsorBlock flagged as sponsored/campaign content;
  // false = only videos SponsorBlock has actually checked and confirmed
  // clean (undefined = no filter — see has_sponsor in
  // backend/app/routers/videos.py for the "not yet checked" distinction).
  hasSponsor?: boolean;
  limit?: number;
  offset?: number;
}

export interface VideoListResult {
  videos: ApiVideo[];
  total: number;
  overperformCount: number;
}

export interface SystemStatus {
  workspaceName: string;
  youtubeQuotaUsedToday: number;
  youtubeQuotaBudget: number;
  youtubeQuotaPct: number;
  lastScrapeStartedAt: string | null;
  lastScrapeStatus: string | null;
  totalChannels: number;
  totalVideos: number;
  overperformCount: number;
}

export interface CohortSummary {
  label: string;
  count: number;
}

export interface ScrapeRun {
  id: number;
  platform: string;
  channelId: string | null;
  startedAt: string;
  finishedAt: string | null;
  status: string;
  channelsProcessed: number;
  videosUpserted: number;
  youtubeQuotaUnitsUsed: number;
  apifyRunsStarted: number;
  errorMessage: string | null;
}

export interface ScrapeTriggerResult {
  message: string;
  runs: ScrapeRun[];
}

export interface ScraperSettings {
  instagramScrapingEnabled: boolean;
  updatedAt: string;
}

class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

// No call in this app should be able to hang forever — a stalled mobile
// connection or a proxy that swallows a response without ever closing the
// socket would otherwise leave whatever `loading` flag gated this call
// (videosLoading, submitting, refreshing, …) stuck true indefinitely, with
// no way out for the person looking at it short of reloading the page.
const DEFAULT_TIMEOUT_MS = 20_000;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  // A caller-supplied signal (App.tsx's debounced video fetch cancelling a
  // superseded request) and our own timeout both need to be able to end
  // this fetch, so both are wired onto one controller rather than relying
  // on AbortSignal.any (recent enough that assuming it's available isn't
  // worth it here).
  const controller = new AbortController();
  const externalSignal = init?.signal;
  if (externalSignal) {
    if (externalSignal.aborted) controller.abort();
    else externalSignal.addEventListener("abort", () => controller.abort(), { once: true });
  }
  const timeoutId = window.setTimeout(() => controller.abort(), DEFAULT_TIMEOUT_MS);

  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
      ...init,
      signal: controller.signal,
    });
  } catch (err) {
    // Our own timeout, not the caller's own cancellation (the video-fetch
    // effect already checks a `cancelled` flag before ever looking at what
    // kind of error this was, so this message is only ever seen for a call
    // that really did just time out).
    if (controller.signal.aborted && !externalSignal?.aborted) {
      throw new ApiError("The server took too long to respond. Check your connection and try again.", 0);
    }
    // A caller-initiated cancellation (AbortError) or a real network failure
    // (offline, DNS, connection refused — a TypeError from fetch itself).
    // Re-thrown as-is: every call site already falls back to a generic
    // "couldn't load/save" message for anything that isn't an ApiError, and
    // the cancellation case is discarded by the caller's own guard before
    // it ever reaches a user-visible message.
    throw err;
  } finally {
    window.clearTimeout(timeoutId);
  }

  if (!res.ok) {
    let detail = _statusFallbackMessage(res.status, res.statusText);
    try {
      const body = await res.json();
      detail = typeof body?.detail === "string" && body.detail ? body.detail : detail;
    } catch {
      // Error response wasn't JSON (a proxy's own HTML error page for a 502/
      // 504, for instance) — the status-based fallback above already covers it.
    }
    throw new ApiError(detail, res.status);
  }
  if (res.status === 204) return undefined as T;
  try {
    return (await res.json()) as T;
  } catch {
    // A 200 with a body that isn't valid JSON (truncated by a dropped
    // connection, a misbehaving proxy, …) — surfaced the same way any other
    // failure is, rather than letting a raw SyntaxError reach the caller.
    throw new ApiError("The server sent back a response we couldn't understand. Please try again.", res.status);
  }
}

/** A human-readable fallback for when the server's error response has no
 * usable `detail` field of its own — covers the specific statuses this
 * app's own infrastructure (Render's free tier sleeping/cold-starting, a
 * proxy timing out) is most likely to actually produce. */
function _statusFallbackMessage(status: number, statusText: string): string {
  if (status === 401 || status === 403) return "This request wasn't authorized.";
  if (status === 404) return "That item couldn't be found — it may have already been removed.";
  if (status === 429) return "Too many requests — please wait a moment and try again.";
  if (status === 502 || status === 503 || status === 504) {
    return "The server is temporarily unavailable — it may be starting up. Please try again in a moment.";
  }
  if (status >= 500) return "Something went wrong on the server. Please try again.";
  return statusText || "Something went wrong.";
}

/**
 * A fetch a caller may want to abort mid-flight — currently just
 * fetchVideos, whose callers (App.tsx's filter-change effect,
 * ChannelStatCard's velocity panel) can fire a new request before an
 * earlier one has finished. Passing `signal` lets `fetch` itself tear down
 * the in-flight request instead of merely ignoring its response: without
 * it, a superseded request still runs to completion server-side (three DB
 * queries in /api/videos, per app/routers/videos.py) purely to have its
 * result thrown away client-side.
 */
export interface RequestOptions {
  signal?: AbortSignal;
}

export function fetchChannels(platform?: Platform): Promise<ApiChannel[]> {
  const params = platform && platform !== "all" ? `?platform=${platform}` : "";
  return request<ApiChannel[]>(`/api/channels${params}`);
}

export function fetchCohorts(): Promise<CohortSummary[]> {
  return request<CohortSummary[]>("/api/channels/cohorts");
}

export function createChannel(payload: { platform: string; handle: string; cohort?: string | null }): Promise<ApiChannel> {
  return request<ApiChannel>("/api/channels", { method: "POST", body: JSON.stringify(payload) });
}

export function updateChannel(
  id: string,
  payload: { cohort?: string | null; isActive?: boolean; notes?: string | null },
): Promise<ApiChannel> {
  return request<ApiChannel>(`/api/channels/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: JSON.stringify({
      cohort: payload.cohort,
      is_active: payload.isActive,
      notes: payload.notes,
    }),
  });
}

export function deleteChannel(id: string): Promise<void> {
  return request<void>(`/api/channels/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export function fetchVideos(query: VideoQuery, options?: RequestOptions): Promise<VideoListResult> {
  const params = new URLSearchParams();
  if (query.platform !== "all") params.set("platform", query.platform);
  for (const id of query.channels) params.append("channels", id);
  if (query.dateFrom) params.set("date_from", query.dateFrom);
  if (query.dateTo) params.set("date_to", query.dateTo);
  if (query.viewsThreshold) params.set("views_threshold", query.viewsThreshold);
  if (query.format !== "all") params.set("format", query.format);
  if (query.sortBy) params.set("sort_by", query.sortBy);
  if (query.metric) params.set("metric", query.metric);
  if (query.hasSponsor !== undefined) params.set("has_sponsor", String(query.hasSponsor));
  if (query.limit) params.set("limit", String(query.limit));
  if (query.offset) params.set("offset", String(query.offset));
  return request<VideoListResult>(`/api/videos?${params.toString()}`, { signal: options?.signal });
}

export function fetchSystemStatus(): Promise<SystemStatus> {
  return request<SystemStatus>("/api/system/status");
}

/**
 * Kicks off a scrape right now, for the dashboard's "Refresh data" button.
 * Hits POST /api/scrape/run-manual — unlike POST /api/scrape/run (which the
 * GitHub Actions cron/curl use), this one needs no API key, since a key
 * shipped in this bundle would be readable by anyone who opens dev tools on
 * the deployed site. It's cooldown-limited server-side instead: expect a
 * 429 ApiError (see MANUAL_SCRAPE_COOLDOWN_SECONDS in backend/.env.example)
 * if one already ran recently — callers should show `err.message` (it's
 * already a human-readable "try again in Ns" string) rather than treating
 * it like an unexpected failure.
 */
export function triggerManualScrape(platform?: Exclude<Platform, "all">): Promise<ScrapeTriggerResult> {
  const params = platform ? `?platform=${platform}` : "";
  return request<ScrapeTriggerResult>(`/api/scrape/run-manual${params}`, { method: "POST" });
}

/**
 * The sidebar's "Apify Usage" toggle. Backed by GET/PATCH /api/settings/scraper
 * (see WorkspaceSettings in backend/app/models.py) — a DB-persisted switch,
 * not a per-browser preference, so it takes effect for every scrape trigger
 * (the GitHub Actions schedule included), not just this browser tab.
 */
export function fetchScraperSettings(): Promise<ScraperSettings> {
  return request<ScraperSettings>("/api/settings/scraper");
}

export function setInstagramScrapingEnabled(enabled: boolean): Promise<ScraperSettings> {
  return request<ScraperSettings>("/api/settings/scraper", {
    method: "PATCH",
    body: JSON.stringify({ instagram_scraping_enabled: enabled }),
  });
}

/**
 * Topic search / "is this trending" (see backend/app/topic_search.py) — a
 * user-triggered YouTube search, kept deliberately separate from the
 * tracked-channel Channel/Video data above. Only a single-slot cache
 * persists server-side (the latest query's summary + its top channels);
 * repeating the same query still re-searches YouTube fresh rather than
 * reusing it, since "is this trending right now" goes stale by definition
 * — the cache's only job is to survive a page reload.
 */
export interface TopicSearchChannelResult {
  rank: number;
  channelId: string;
  channelName: string;
  channelHandle: string | null;
  channelAvatarUrl: string | null;
  subscriberCount: number;
  videoId: string;
  videoTitle: string;
  videoThumbnailUrl: string | null;
  videoUrl: string;
  videoViews: number;
  videoPublishedAt: string; // "YYYY-MM-DD"
  // (views / subscribers) / days-since-published — see topic_search.py's
  // score_candidate() for why both channel size and video age are
  // normalized out.
  score: number;
  // This channel's median views over its *other* recent uploads, and this
  // video's ratio against that median — both null if the channel had no
  // other recent uploads to compare against.
  channelMedianViews: number | null;
  overperformRatio: number | null;
  isOutperforming: boolean;
}

export interface TopicSearchResult {
  query: string;
  searchedAt: string;
  dateFrom: string | null; // "YYYY-MM-DD"; null = no lower bound ("All time")
  dateTo: string | null; // "YYYY-MM-DD"; null = up to now
  lookbackDays: number | null; // derived/display-only; null when dateFrom is unset
  minSubscribers: number;
  regionCode: string | null; // null = no regional restriction ("Global")
  topN: number;
  // How many videos survived the date filter + subscriber gate — the
  // population `channels` was ranked out of.
  totalCandidates: number;
  // Of `channels` (already capped at topN), how many are outperforming
  // their own channel's median — the headline "X of N" hype readout.
  outperformCount: number;
  youtubeQuotaUnitsUsed: number;
  channels: TopicSearchChannelResult[];
}

/** GET /api/search/latest — the page-reload path. Never spends quota; returns
 * null if no search has ever run. */
export function fetchLatestTopicSearch(): Promise<TopicSearchResult | null> {
  return request<TopicSearchResult | null>("/api/search/latest");
}

export interface TopicSearchFilters {
  // All optional — omitting a field falls back to the backend's own
  // default (500K subs / last 60 days / India — see
  // backend/app/config.py's Settings). The Trend Analysis tab's UI always
  // sends concrete values for its own defaults (500K / last 30 days /
  // India) instead of relying on this fallback; it exists mainly for
  // "All time" (send dateFrom/dateTo as "" explicitly — distinct from
  // omitting them, which gets the backend's fixed lookback instead) and
  // "Global" (region: "GLOBAL" — no regionCode sent to YouTube at all).
  minSubscribers?: number;
  dateFrom?: string; // "YYYY-MM-DD", or "" for no lower bound
  dateTo?: string; // "YYYY-MM-DD", or "" for no upper bound
  region?: "IN" | "GLOBAL" | (string & {});
}

/**
 * POST /api/search/topic — runs a fresh search against YouTube right now.
 * Real quota spend; expect an ApiError (400 bad filter, 429 cooldown/
 * budget, 502 upstream failure, 503 not configured) rather than treating
 * every rejection as unexpected — see backend/app/routers/search.py.
 */
export function searchTopic(query: string, filters: TopicSearchFilters = {}): Promise<TopicSearchResult> {
  return request<TopicSearchResult>("/api/search/topic", {
    method: "POST",
    body: JSON.stringify({
      query,
      min_subscribers: filters.minSubscribers,
      date_from: filters.dateFrom,
      date_to: filters.dateTo,
      region: filters.region,
    }),
  });
}

export { ApiError };
