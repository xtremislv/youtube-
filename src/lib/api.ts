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
  videoCount: number;
  lastPublishedAt: string | null; // "YYYY-MM-DD"
}

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
  likes: number | null;
  comments: number | null;
  publishedAt: string; // "YYYY-MM-DD"
  duration: string; // "MM:SS" or "H:MM:SS"
  format: "short" | "long" | "reel";
  overperformRatio: number | null;
}

export interface VideoQuery {
  platform: Platform;
  channels: string[];
  dateFrom: string;
  dateTo: string;
  viewsThreshold: string;
  format: string;
  sortBy: string;
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

class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      // response wasn't JSON — fall back to statusText
    }
    throw new ApiError(detail, res.status);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
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

export function fetchVideos(query: VideoQuery): Promise<VideoListResult> {
  const params = new URLSearchParams();
  if (query.platform !== "all") params.set("platform", query.platform);
  for (const id of query.channels) params.append("channels", id);
  if (query.dateFrom) params.set("date_from", query.dateFrom);
  if (query.dateTo) params.set("date_to", query.dateTo);
  if (query.viewsThreshold) params.set("views_threshold", query.viewsThreshold);
  if (query.format !== "all") params.set("format", query.format);
  if (query.sortBy) params.set("sort_by", query.sortBy);
  if (query.limit) params.set("limit", String(query.limit));
  if (query.offset) params.set("offset", String(query.offset));
  return request<VideoListResult>(`/api/videos?${params.toString()}`);
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

export { ApiError };
