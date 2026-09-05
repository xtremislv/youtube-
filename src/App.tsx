import React, { useState, useMemo, useRef, useEffect, useCallback } from "react";
import svgPaths from "imports/svg-siexpc9d1x";
import {
  fetchChannels,
  fetchCohorts,
  fetchVideos,
  fetchSystemStatus,
  fetchScraperSettings,
  setInstagramScrapingEnabled,
  createChannel,
  deleteChannel,
  updateChannel,
  triggerManualScrape,
  ApiError,
  type ApiChannel as Channel,
  type ApiVideo as Video,
  type CohortSummary,
  type SystemStatus,
  type ScraperSettings,
  type OverperformMetric,
} from "@/lib/api";

// ─── Types ───────────────────────────────────────────────────────────────────
// Channel/Video are now the live API shapes (see src/lib/api.ts) — this file
// used to define its own Channel/Video interfaces around a hardcoded mock
// array. The API's CamelModel schemas were written to match those old mock
// shapes field-for-field, so almost nothing else in this file had to change.

type Platform = "youtube" | "instagram" | "all";
type ViewMode = "grid" | "list";

// ─── Helpers ──────────────────────────────────────────────────────────────────

function fmtViews(n: number) {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
  if (n >= 1_000) return (n / 1_000).toFixed(0) + "K";
  return String(n);
}

/** Same as fmtViews but tolerates the "not enough history yet" null a brand-new channel's baseline can be. */
function fmtViewsN(n: number | null | undefined) {
  return n == null ? "—" : fmtViews(n);
}

function fmtRatio(n: number | null | undefined) {
  return n == null ? "—" : n.toFixed(2) + "x";
}

function fmtDate(d: string) {
  return new Date(d).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function currentMonthLabel() {
  return new Date().toLocaleDateString("en-US", { month: "short", year: "numeric" });
}

/** "3m ago" / "2h ago" — used to show when data was last refreshed. */
function fmtRelativeTime(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return null;
  const mins = Math.round((Date.now() - then) / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

// ─── Icons ────────────────────────────────────────────────────────────────────

function YTIcon({ size = 14 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor">
      <path d="M23.5 6.2s-.3-1.9-1.1-2.8c-1.1-1.2-2.3-1.2-2.8-1.2C16.7 2 12 2 12 2s-4.7 0-7.6.2c-.6.1-1.7.1-2.8 1.2C.8 4.3.5 6.2.5 6.2S.2 8.4.2 10.6v2.1c0 2.2.3 4.4.3 4.4s.3 1.9 1.1 2.8c1.1 1.2 2.5 1.1 3.1 1.2C6.7 21.3 12 21.3 12 21.3s4.7 0 7.6-.3c.6-.1 1.7-.1 2.8-1.2.8-.8 1.1-2.8 1.1-2.8s.3-2.2.3-4.4v-2.1c0-2.2-.3-4.4-.3-4.4zM9.7 15.5V8.3l7.6 3.6-7.6 3.6z" />
    </svg>
  );
}

function IGIcon({ size = 14 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor">
      <path d="M12 2.163c3.204 0 3.584.012 4.85.07 3.252.148 4.771 1.691 4.919 4.919.058 1.265.069 1.645.069 4.849 0 3.205-.012 3.584-.069 4.849-.149 3.225-1.664 4.771-4.919 4.919-1.266.058-1.644.07-4.85.07-3.204 0-3.584-.012-4.849-.07-3.26-.149-4.771-1.699-4.919-4.92-.058-1.265-.07-1.644-.07-4.849 0-3.204.013-3.583.07-4.849.149-3.227 1.664-4.771 4.919-4.919 1.266-.057 1.645-.069 4.849-.069zm0-2.163c-3.259 0-3.667.014-4.947.072-4.358.2-6.78 2.618-6.98 6.98-.059 1.281-.073 1.689-.073 4.948 0 3.259.014 3.668.072 4.948.2 4.358 2.618 6.78 6.98 6.98 1.281.058 1.689.072 4.948.072 3.259 0 3.668-.014 4.948-.072 4.354-.2 6.782-2.618 6.979-6.98.059-1.28.073-1.689.073-4.948 0-3.259-.014-3.667-.072-4.947-.196-4.354-2.617-6.78-6.979-6.98-1.281-.059-1.69-.073-4.949-.073zm0 5.838c-3.403 0-6.162 2.759-6.162 6.162s2.759 6.163 6.162 6.163 6.162-2.759 6.162-6.163c0-3.403-2.759-6.162-6.162-6.162zm0 10.162c-2.209 0-4-1.79-4-4 0-2.209 1.791-4 4-4s4 1.791 4 4c0 2.21-1.791 4-4 4zm6.406-11.845c-.796 0-1.441.645-1.441 1.44s.645 1.44 1.441 1.44c.795 0 1.439-.645 1.439-1.44s-.644-1.44-1.439-1.44z" />
    </svg>
  );
}

function BellIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
      <path d="M13.73 21a2 2 0 0 1-3.46 0" />
    </svg>
  );
}

function ChevronDown({ size = 12 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
      <polyline points="6 9 12 15 18 9" />
    </svg>
  );
}

function GridIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <rect x="3" y="3" width="7" height="7" /><rect x="14" y="3" width="7" height="7" />
      <rect x="14" y="14" width="7" height="7" /><rect x="3" y="14" width="7" height="7" />
    </svg>
  );
}

function ListIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <line x1="8" y1="6" x2="21" y2="6" /><line x1="8" y1="12" x2="21" y2="12" />
      <line x1="8" y1="18" x2="21" y2="18" />
      <line x1="3" y1="6" x2="3.01" y2="6" /><line x1="3" y1="12" x2="3.01" y2="12" />
      <line x1="3" y1="18" x2="3.01" y2="18" />
    </svg>
  );
}

function BarChartIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <line x1="18" y1="20" x2="18" y2="10" /><line x1="12" y1="20" x2="12" y2="4" />
      <line x1="6" y1="20" x2="6" y2="14" /><line x1="2" y1="20" x2="22" y2="20" />
    </svg>
  );
}

function XIcon({ size = 10 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3">
      <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
    </svg>
  );
}

function MenuIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
      <line x1="3" y1="6" x2="21" y2="6" /><line x1="3" y1="12" x2="21" y2="12" />
      <line x1="3" y1="18" x2="21" y2="18" />
    </svg>
  );
}

function HomeIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 11.5 12 4l8 7.5" />
      <path d="M6 10v9h12v-9" />
      <path d="M10 19v-5h4v5" />
    </svg>
  );
}

function TrendUpIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
      <polyline points="23 6 13.5 15.5 8.5 10.5 1 18" />
      <polyline points="17 6 23 6 23 12" />
    </svg>
  );
}

function TrashIcon({ size = 12 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="3 6 5 6 21 6" />
      <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
    </svg>
  );
}

function PlusIcon({ size = 12 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
      <line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" />
    </svg>
  );
}

function RefreshIcon({ size = 14 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 12a9 9 0 1 1-2.64-6.36" />
      <path d="M21 3v6h-6" />
    </svg>
  );
}

function HeartIcon({ size = 11 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.6l-1-1a5.5 5.5 0 0 0-7.8 7.8l1 1L12 21l7.8-7.6 1-1a5.5 5.5 0 0 0 0-7.8z" />
    </svg>
  );
}

function CommentIcon({ size = 11 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
    </svg>
  );
}

function FilmIcon({ size = 12 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="2" y="3" width="20" height="18" rx="2" />
      <line x1="7" y1="3" x2="7" y2="21" /><line x1="17" y1="3" x2="17" y2="21" />
      <line x1="2" y1="9" x2="7" y2="9" /><line x1="2" y1="15" x2="7" y2="15" />
      <line x1="17" y1="9" x2="22" y2="9" /><line x1="17" y1="15" x2="22" y2="15" />
    </svg>
  );
}

// ─── Mini Sparkline ───────────────────────────────────────────────────────────

function Sparkline({ ratio, color }: { ratio: number; color: string }) {
  const pts = useMemo(() => {
    const seed = ratio * 100;
    const vals = [40, 55, 45, 70, 60, seed * 0.9, seed];
    const max = Math.max(...vals);
    return vals.map((v, i) => `${(i / (vals.length - 1)) * 60},${20 - (v / max) * 18}`).join(" ");
  }, [ratio]);
  return (
    <svg width="60" height="20" viewBox="0 0 60 20">
      <polyline points={pts} fill="none" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

// ─── Mini Donut Chart ─────────────────────────────────────────────────────────

function DonutChart({ ytCount, igCount }: { ytCount: number; igCount: number }) {
  const total = ytCount + igCount;
  const ytPct = total ? (ytCount / total) * 100 : 50;
  const r = 28, cx = 32, cy = 32, circ = 2 * Math.PI * r;
  const ytDash = (ytPct / 100) * circ;
  return (
    <svg width="64" height="64" viewBox="0 0 64 64">
      <circle cx={cx} cy={cy} r={r} fill="none" stroke="rgba(225,48,108,0.25)" strokeWidth="8" />
      <circle cx={cx} cy={cy} r={r} fill="none" stroke="rgba(255,68,68,0.7)" strokeWidth="8"
        strokeDasharray={`${ytDash} ${circ - ytDash}`} strokeDashoffset={circ / 4} strokeLinecap="round" />
      <text x={cx} y={cy + 4} textAnchor="middle" fill="#dfe2ef" fontSize="10" fontFamily="JetBrains Mono,monospace" fontWeight="500">
        {Math.round(ytPct)}%
      </text>
    </svg>
  );
}

// ─── Mini Bar Chart ───────────────────────────────────────────────────────────

function BarChart({ videos, metric }: { videos: Video[]; metric: OverperformMetric }) {
  // A brand-new channel's freshest videos have no baseline yet (see
  // backend/app/overperformance.py) — the chosen metric's ratio is null
  // until enough history exists. Those can't be ranked here, so they're
  // left out rather than crashing the max()/sort() below on a null.
  const ratioOf = (v: Video) => (metric === "median" ? v.overperformRatioMedian : v.overperformRatio);
  const ranked = videos.filter((v): v is Video & { overperformRatio: number; overperformRatioMedian: number } => ratioOf(v) != null);
  const top5 = [...ranked].sort((a, b) => ratioOf(b)! - ratioOf(a)!).slice(0, 6);
  if (top5.length === 0) {
    return <div className="text-xs py-2" style={{ color: "var(--text-muted)" }}>Not enough scrape history yet to rank channels.</div>;
  }
  const max = Math.max(...top5.map(v => ratioOf(v)!));
  return (
    <div className="flex flex-col gap-1.5 w-full">
      {top5.map(v => (
        <div key={v.id} className="flex items-center gap-2">
          <span className="text-[10px] font-mono truncate w-28 shrink-0" style={{ color: "var(--text-muted)" }}>{v.channelName}</span>
          <div className="flex-1 h-1.5 rounded-full" style={{ background: "var(--bg-active)" }}>
            <div className="h-full rounded-full transition-all" style={{
              width: `${(ratioOf(v)! / max) * 100}%`,
              background: v.platform === "youtube" ? "var(--yt-red)" : "var(--ig-pink)"
            }} />
          </div>
          <span className="text-[10px] font-mono w-8 text-right shrink-0" style={{ color: "var(--accent-light)" }}>{ratioOf(v)!.toFixed(1)}x</span>
        </div>
      ))}
    </div>
  );
}

// ─── Toggle Switch ────────────────────────────────────────────────────────────
// Small hand-rolled on/off switch (no library) — used by the sidebar's
// "Apify Usage" toggle. A native checkbox styled as a switch would work too,
// but a button gives clearer control over the disabled/pending look.

function ToggleSwitch({ checked, onChange, disabled, label }: { checked: boolean; onChange: () => void; disabled?: boolean; label?: string }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={onChange}
      disabled={disabled}
      className="relative shrink-0 transition-colors disabled:opacity-50 disabled:cursor-wait"
      style={{ width: 34, height: 18, borderRadius: 999, background: checked ? "var(--accent)" : "var(--bg-active)", border: "1px solid var(--border)" }}
    >
      <span
        className="absolute rounded-full transition-transform"
        style={{ width: 12, height: 12, top: 2, left: 2, background: checked ? "#0d0096" : "var(--text-muted)", transform: checked ? "translateX(16px)" : "translateX(0)" }}
      />
    </button>
  );
}

// ─── Sidebar ──────────────────────────────────────────────────────────────────

const COHORT_COLORS = ["#c0c1ff", "#ffb3ad", "#ffb0cd", "#8fe3c7", "#ffd88f", "#a8c8ff"];

interface SidebarProps {
  open: boolean;
  activeSection: string;
  setActiveSection: (s: string) => void;
  overperformBadge: number | null;
  cohorts: CohortSummary[];
  quotaPct: number | null;
  instagramScrapingEnabled: boolean | null;
  onToggleInstagramScraping: () => void;
  togglingScraper: boolean;
}

function Sidebar({
  open,
  activeSection,
  setActiveSection,
  overperformBadge,
  cohorts,
  quotaPct,
  instagramScrapingEnabled,
  onToggleInstagramScraping,
  togglingScraper,
}: SidebarProps) {
  const navLinks = [
    { label: "Overperformance", icon: "chart", badge: overperformBadge },
    { label: "Add Channel", icon: "people", badge: null as number | null },
  ];

  return (
    <aside
      className="sidebar-slide flex flex-col h-full shrink-0 overflow-hidden"
      style={{
        width: open ? 240 : 0,
        opacity: open ? 1 : 0,
        background: "var(--bg-panel)",
        borderRight: "1px solid var(--border)",
        pointerEvents: open ? "auto" : "none",
      }}
    >
      {/* Brand */}
      <div className="flex items-center justify-between px-4 py-4 shrink-0" style={{ borderBottom: "1px solid var(--border)" }}>
        <div className="flex items-center gap-2.5">
          <div className="relative flex items-center justify-center size-8 shrink-0">
            {/* TW-Labs mark — public/tw-logo.png, already a circular black
                mark with transparent corners, so no background/clip needed
                here (unlike the old inline SVG glyph it replaces). */}
            <img src="/tw-logo.png" alt="TW-Labs" className="size-8" />
            <span className="notification-dot" style={{ position: "absolute", top: 3, right: 3, width: 7, height: 7, background: "#c0c1ff", borderRadius: "50%", border: "1.5px solid var(--bg-panel)" }} />
          </div>
          <div>
            <div className="text-sm font-bold leading-none" style={{ color: "var(--text-primary)", fontFamily: "Lora, serif" }}>
              TW<span style={{ color: "#c0c1ff" }}>-Labs</span>
            </div>
          </div>
        </div>
      </div>

      {/* Nav */}
      <div className="px-2 shrink-0">
        <div className="text-[10px] tracking-widest uppercase px-3 py-2" style={{ color: "var(--text-muted)", fontFamily: "Lora, serif" }}>
          Telemetry & Analysis
        </div>
        <nav className="flex flex-col gap-0.5">
          {navLinks.map(link => (
            <button
              key={link.label}
              onClick={() => setActiveSection(link.label)}
              className="flex items-center gap-3 px-3 py-2 rounded-lg w-full text-left transition-all"
              style={{
                background: activeSection === link.label ? "#8083ff" : "transparent",
                color: activeSection === link.label ? "#0d0096" : "var(--text-secondary)",
              }}
            >
              <NavIcon icon={link.icon} active={activeSection === link.label} />
              <span className="text-sm flex-1" style={{ fontFamily: "Lora, serif" }}>{link.label}</span>
              {link.badge != null && (
                <span className="text-[10px] px-1.5 py-0.5 rounded-full font-bold" style={{
                  background: activeSection === link.label ? "rgba(164,2,23,0.9)" : "#a40217",
                  color: "#ffaea8",
                }}>
                  {link.badge}
                </span>
              )}
            </button>
          ))}
        </nav>
      </div>

      {/* Cohorts */}
      <div className="px-2 mt-2 flex-1 min-h-0 overflow-y-auto">
        <div className="flex items-center justify-between px-3 py-2">
          <span className="text-[10px] tracking-widest uppercase" style={{ color: "var(--text-muted)", fontFamily: "Lora, serif" }}>Saved Cohorts</span>
          <svg width="8" height="8" viewBox="0 0 8.16667 8.16667" fill="none"><path d={svgPaths.p10ad69c0} fill="#c0c1ff" /></svg>
        </div>
        {cohorts.length === 0 ? (
          <div className="px-3 py-2 text-xs" style={{ color: "var(--text-muted)" }}>
            Tag channels with a cohort in Add Channel to group them here.
          </div>
        ) : (
          cohorts.map((c, i) => (
            <button key={c.label} className="flex items-center gap-3 px-3 py-2 rounded-lg w-full text-left hover:bg-white/5 transition-colors">
              <div className="size-2 rounded-sm shrink-0" style={{ background: COHORT_COLORS[i % COHORT_COLORS.length] }} />
              <span className="text-sm flex-1 text-left" style={{ color: "var(--text-secondary)", fontFamily: "Lora, serif" }}>{c.label}</span>
              <span className="text-sm" style={{ color: "var(--text-muted)", fontFamily: "JetBrains Mono, monospace" }}>{c.count}</span>
            </button>
          ))
        )}
      </div>

      {/* Apify Usage — pauses Instagram (Apify) scraping to save Apify
          credit. Enforced server-side in app/scrape_service.py so it holds
          for the GitHub Actions schedule too, not just this dashboard's own
          "Refresh data" button — see WorkspaceSettings in
          backend/app/models.py. */}
      <div className="px-2 pt-2 shrink-0">
        <div className="rounded-xl p-3" style={{ background: "#1c1f29" }}>
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-[10px] tracking-widest uppercase" style={{ color: "var(--text-secondary)", fontFamily: "Lora, serif" }}>Apify Usage</span>
            <ToggleSwitch
              checked={instagramScrapingEnabled ?? true}
              onChange={onToggleInstagramScraping}
              disabled={togglingScraper || instagramScrapingEnabled == null}
              label="Toggle Instagram (Apify) scraping"
            />
          </div>
          <div className="text-[11px] leading-snug" style={{ color: "var(--text-muted)", fontFamily: "Lora, serif" }}>
            {instagramScrapingEnabled === false
              ? "Instagram scraping paused — refresh & schedule skip Apify."
              : "Instagram scraping runs on refresh & the daily schedule."}
          </div>
        </div>
      </div>

      {/* API Quota */}
      <div className="p-2 shrink-0">
        <div className="rounded-xl p-3" style={{ background: "#1c1f29" }}>
          <div className="flex items-center justify-between mb-2">
            <span className="text-[10px] tracking-widest uppercase" style={{ color: "var(--text-secondary)", fontFamily: "Lora, serif" }}>API Quota</span>
            <span className="text-xs font-bold" style={{ color: "var(--text-primary)", fontFamily: "JetBrains Mono, monospace" }}>
              {quotaPct == null ? "—" : `${quotaPct}%`}
            </span>
          </div>
          <div className="h-1.5 rounded-full overflow-hidden" style={{ background: "var(--bg-active)" }}>
            <div className="h-full rounded-full" style={{ width: `${quotaPct ?? 0}%`, background: "var(--accent-light)" }} />
          </div>
          <div className="flex items-center justify-between mt-2">
            <span className="text-[11px]" style={{ color: "var(--text-muted)", fontFamily: "Lora, serif" }}>YouTube Data API, today</span>
            <svg width="11" height="9" viewBox="0 0 11.6676 9.33333" fill="none"><path d={svgPaths.p1cccc530} fill="#908fa0" /></svg>
          </div>
        </div>
      </div>
    </aside>
  );
}

function NavIcon({ icon, active }: { icon: string; active: boolean }) {
  const color = active ? "#0d0096" : "#c7c4d7";
  const icons: Record<string, React.ReactElement> = {
    chart: <svg width="16" height="13" viewBox="0 0 16.6681 13.3333" fill="none"><path d={svgPaths.p350ec980} fill={color} /></svg>,
    people: <svg width="20" height="10" viewBox="0 0 20 10" fill="none"><path d={svgPaths.p279daa80} fill={color} /></svg>,
    trend: <svg width="16" height="11" viewBox="0 0 16.6667 10.8333" fill="none"><path d={svgPaths.p617b400} fill={color} /></svg>,
    grid: <svg width="15" height="15" viewBox="0 0 15 15" fill="none"><path d={svgPaths.p1d75e100} fill={color} /></svg>,
    compare: <svg width="16" height="13" viewBox="0 0 16.6667 13.3333" fill="none"><path d={svgPaths.p110e1200} fill={color} /></svg>,
    bell: <svg width="16" height="16" viewBox="0 0 16.6667 16.7083" fill="none"><path d={svgPaths.p1dcf6b00} fill={color} /></svg>,
  };
  return icons[icon] || <div className="size-4" />;
}

// ─── Notification Panel ───────────────────────────────────────────────────────

function NotificationPanel({ videos, loading, onClose }: { videos: Video[]; loading: boolean; onClose: () => void }) {
  const topVideos = videos.slice(0, 5);
  const ytCount = videos.filter(v => v.platform === "youtube").length;
  const igCount = videos.filter(v => v.platform === "instagram").length;
  const totalViews = videos.reduce((s, v) => s + v.views, 0);
  // These videos were selected by their median ratio (see openNotifications
  // in App()), so the stats shown here need to read the same field or the
  // panel's own numbers won't add up against why a video is even listed.
  const avgRatio = videos.length ? (videos.reduce((s, v) => s + (v.overperformRatioMedian ?? 0), 0) / videos.length) : 0;

  return (
    <div className="absolute right-0 top-12 z-50 w-80 rounded-xl overflow-hidden shadow-2xl"
      style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}>
      <div className="flex items-center justify-between px-4 py-3" style={{ borderBottom: "1px solid var(--border)" }}>
        <span className="text-sm font-semibold" style={{ color: "var(--text-primary)", fontFamily: "Lora, serif" }}>Performance Overview</span>
        <button onClick={onClose} className="opacity-50 hover:opacity-100 transition-opacity" style={{ color: "var(--text-secondary)" }}>
          <XIcon size={12} />
        </button>
      </div>

      {loading ? (
        <div className="px-4 py-6 text-xs text-center" style={{ color: "var(--text-muted)" }}>Loading…</div>
      ) : videos.length === 0 ? (
        <div className="px-4 py-6 text-xs text-center" style={{ color: "var(--text-muted)" }}>
          No videos are overperforming yet. Add channels and run a scrape to start tracking.
        </div>
      ) : (
        <>
          {/* Stats */}
          <div className="grid grid-cols-2 gap-px" style={{ background: "var(--border)" }}>
            {[
              { label: "Overperforming", value: String(videos.length), sub: "videos" },
              { label: "Avg Ratio", value: avgRatio.toFixed(2) + "x", sub: "above baseline" },
              { label: "Total Views", value: fmtViews(totalViews), sub: "combined" },
              { label: "Platforms", value: `YT ${ytCount} · IG ${igCount}`, sub: "channels active" },
            ].map(s => (
              <div key={s.label} className="px-4 py-3" style={{ background: "var(--bg-card)" }}>
                <div className="text-[10px] uppercase tracking-widest mb-1" style={{ color: "var(--text-muted)", fontFamily: "Lora, serif" }}>{s.label}</div>
                <div className="text-base font-bold" style={{ color: "var(--text-primary)", fontFamily: "JetBrains Mono, monospace" }}>{s.value}</div>
                <div className="text-[11px]" style={{ color: "var(--text-muted)" }}>{s.sub}</div>
              </div>
            ))}
          </div>

          {/* Platform split */}
          <div className="px-4 py-3" style={{ borderTop: "1px solid var(--border)" }}>
            <div className="flex items-center gap-3">
              <DonutChart ytCount={ytCount} igCount={igCount} />
              <div className="flex-1">
                <div className="flex items-center gap-2 mb-1.5">
                  <div className="size-2 rounded-sm" style={{ background: "var(--yt-red)" }} />
                  <span className="text-xs" style={{ color: "var(--text-secondary)", fontFamily: "Lora, serif" }}>YouTube — {ytCount}</span>
                </div>
                <div className="flex items-center gap-2">
                  <div className="size-2 rounded-sm" style={{ background: "var(--ig-pink)" }} />
                  <span className="text-xs" style={{ color: "var(--text-secondary)", fontFamily: "Lora, serif" }}>Instagram — {igCount}</span>
                </div>
              </div>
            </div>
          </div>

          {/* Top alerts */}
          <div className="px-4 pb-3" style={{ borderTop: "1px solid var(--border)" }}>
            <div className="text-[10px] uppercase tracking-widest py-2" style={{ color: "var(--text-muted)", fontFamily: "Lora, serif" }}>Top Performers</div>
            <div className="flex flex-col gap-2">
              {topVideos.map(v => (
                <div key={v.id} className="flex items-center gap-2">
                  <span className="text-[10px] w-7 shrink-0 font-mono font-bold" style={{ color: "#4ade80" }}>{fmtRatio(v.overperformRatioMedian)}</span>
                  <span className="text-xs truncate flex-1" style={{ color: "var(--text-secondary)", fontFamily: "Lora, serif" }}>{v.title}</span>
                  <span className={`text-[10px] px-1.5 rounded-sm ${v.platform === "youtube" ? "badge-yt" : "badge-ig"}`}>
                    {v.platform === "youtube" ? "YT" : "IG"}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

// ─── Filter Bar ───────────────────────────────────────────────────────────────

type DatePreset = "all" | "3d" | "7d" | "2w" | "1m" | "2m" | "custom";

const DATE_PRESETS: { value: DatePreset; label: string; days: number | null }[] = [
  { value: "all", label: "All time", days: null },
  { value: "3d", label: "Last 3 days", days: 3 },
  { value: "7d", label: "Last 7 days", days: 7 },
  { value: "2w", label: "Last 2 weeks", days: 14 },
  { value: "1m", label: "Last 1 month", days: 30 },
  { value: "2m", label: "Last 2 months", days: 60 },
  { value: "custom", label: "Custom range", days: null },
];

// "YYYY-MM-DD" in the viewer's local timezone — matches what <input type="date">
// produces/consumes, so a preset and manual custom-range entry are interchangeable.
function isoDate(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function presetToRange(preset: DatePreset): { dateFrom: string; dateTo: string } {
  const found = DATE_PRESETS.find(p => p.value === preset);
  if (!found?.days) return { dateFrom: "", dateTo: "" };
  const to = new Date();
  const from = new Date();
  from.setDate(from.getDate() - found.days);
  return { dateFrom: isoDate(from), dateTo: isoDate(to) };
}

interface Filters {
  platform: Platform;
  channels: string[];
  datePreset: DatePreset;
  dateFrom: string;
  dateTo: string;
  viewsThreshold: string;
  sortBy: string;
  metric: OverperformMetric;
  showChart: boolean;
  format: string;
}

// Which format values make sense for a given platform, and their label —
// YouTube channels are only ever "long" or "short" (see
// classify_youtube_format in backend/app/scrapers/duration.py) and Instagram
// content is always scraped as "reel" (backend/app/scrapers/instagram.py),
// so showing all four options regardless of platform just offers filters
// that can never match anything for that platform.
const FORMAT_OPTIONS_BY_PLATFORM: Record<Platform, { value: string; label: string }[]> = {
  all: [
    { value: "all", label: "All Formats" },
    { value: "long", label: "Long-form" },
    { value: "short", label: "Shorts / Reels" },
    { value: "reel", label: "Reels only" },
  ],
  youtube: [
    { value: "all", label: "All Formats" },
    { value: "long", label: "Long-form" },
    { value: "short", label: "Shorts" },
  ],
  instagram: [
    { value: "all", label: "All Formats" },
    { value: "reel", label: "Reels only" },
  ],
};

// Keeps the format filter valid whenever the platform changes — e.g.
// switching to Instagram while "Long-form" or "Shorts" is selected snaps to
// "Reels only" (the one format Instagram content ever has) instead of
// silently keeping a filter that can no longer match anything; switching
// away from Instagram while "Reels only" is selected resets to "All
// Formats" for the same reason, in reverse.
function nextFormatForPlatform(format: string, platform: Platform): string {
  const valid = FORMAT_OPTIONS_BY_PLATFORM[platform].some(o => o.value === format);
  if (valid) return format;
  return platform === "instagram" ? "reel" : "all";
}

function FilterBar({ filters, setFilters, viewMode, setViewMode, shownCount, totalResults, channels }: {
  filters: Filters;
  setFilters: (f: Filters) => void;
  viewMode: ViewMode;
  setViewMode: (v: ViewMode) => void;
  shownCount: number;
  totalResults: number;
  channels: Channel[];
}) {
  const [channelOpen, setChannelOpen] = useState(false);
  const dropRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handler(e: MouseEvent) {
      if (dropRef.current && !dropRef.current.contains(e.target as Node)) setChannelOpen(false);
    }
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const platformChannels = channels.filter(c => filters.platform === "all" || c.platform === filters.platform);

  function toggleChannel(id: string) {
    const next = filters.channels.includes(id)
      ? filters.channels.filter(c => c !== id)
      : [...filters.channels, id];
    setFilters({ ...filters, channels: next });
  }

  function clearChannels() { setFilters({ ...filters, channels: [] }); }

  const set = (k: keyof Filters) => (val: string | boolean) => setFilters({ ...filters, [k]: val });

  return (
    <div className="sticky top-0 z-30 px-5 py-3 flex flex-wrap items-center gap-2" style={{ background: "rgba(15,19,28,0.92)", backdropFilter: "blur(12px)", borderBottom: "1px solid var(--border)" }}>

      {/* Platform toggle */}
      <div className="flex rounded-lg overflow-hidden shrink-0" style={{ border: "1px solid var(--border)" }}>
        {(["all", "youtube", "instagram"] as Platform[]).map(p => (
          <button key={p} onClick={() => setFilters({ ...filters, platform: p, channels: [], format: nextFormatForPlatform(filters.format, p) })}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs transition-all"
            style={{
              background: filters.platform === p ? "var(--accent)" : "var(--bg-elevated)",
              color: filters.platform === p ? "#0d0096" : "var(--text-muted)",
              fontFamily: "Inter, sans-serif",
              fontWeight: 500,
            }}>
            {p === "youtube" && <YTIcon size={12} />}
            {p === "instagram" && <IGIcon size={12} />}
            {p === "all" ? "All" : p === "youtube" ? "YouTube" : "Instagram"}
          </button>
        ))}
      </div>

      {/* Channel multi-select */}
      <div className="relative shrink-0" ref={dropRef}>
        <button onClick={() => setChannelOpen(o => !o)}
          className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs transition-all"
          style={{ background: "var(--bg-elevated)", color: filters.channels.length ? "var(--accent-light)" : "var(--text-muted)", border: `1px solid ${filters.channels.length ? "var(--accent)" : "var(--border)"}`, fontFamily: "Inter, sans-serif" }}>
          {filters.channels.length ? `${filters.channels.length} channels` : "All Channels"}
          <ChevronDown />
        </button>
        {channelOpen && (
          <div className="absolute left-0 top-10 z-50 w-56 rounded-xl py-1.5 shadow-2xl overflow-hidden"
            style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}>
            <div className="flex items-center justify-between px-3 py-1.5" style={{ borderBottom: "1px solid var(--border)" }}>
              <span className="text-[10px] uppercase tracking-widest" style={{ color: "var(--text-muted)", fontFamily: "Lora, serif" }}>Select channels</span>
              {filters.channels.length > 0 && (
                <button onClick={clearChannels} className="text-[10px] hover:underline" style={{ color: "var(--accent-light)" }}>Clear</button>
              )}
            </div>
            {platformChannels.length === 0 ? (
              <div className="px-3 py-3 text-xs" style={{ color: "var(--text-muted)" }}>
                No channels tracked yet — add some in Add Channel.
              </div>
            ) : (
              platformChannels.map(c => (
                <label key={c.id} className="flex items-center gap-2.5 px-3 py-2 cursor-pointer hover:bg-white/5 transition-colors">
                  <input type="checkbox" checked={filters.channels.includes(c.id)} onChange={() => toggleChannel(c.id)}
                    className="accent-purple-400 cursor-pointer" />
                  <span className="text-xs flex-1" style={{ color: "var(--text-secondary)", fontFamily: "Lora, serif" }}>{c.name}</span>
                  <span className={`text-[10px] px-1.5 rounded ${c.platform === "youtube" ? "badge-yt" : "badge-ig"}`}>
                    {c.platform === "youtube" ? "YT" : "IG"}
                  </span>
                </label>
              ))
            )}
          </div>
        )}
      </div>

      {/* Date range — a preset dropdown; picking "Custom range" reveals the
          two date pickers below it for a manual from/to. */}
      <div className="flex items-center gap-1 shrink-0">
        <select
          value={filters.datePreset}
          onChange={e => {
            const preset = e.target.value as DatePreset;
            if (preset === "custom") {
              setFilters({ ...filters, datePreset: preset });
            } else {
              setFilters({ ...filters, datePreset: preset, ...presetToRange(preset) });
            }
          }}
          className="select-custom text-xs" style={{ fontFamily: "Inter, sans-serif" }}>
          {DATE_PRESETS.map(p => <option key={p.value} value={p.value}>{p.label}</option>)}
        </select>
        {filters.datePreset === "custom" && (
          <>
            <input type="date" value={filters.dateFrom} onChange={e => set("dateFrom")(e.target.value)}
              className="select-custom text-xs" style={{ fontFamily: "JetBrains Mono, monospace" }} />
            <span style={{ color: "var(--text-muted)" }} className="text-xs">→</span>
            <input type="date" value={filters.dateTo} onChange={e => set("dateTo")(e.target.value)}
              className="select-custom text-xs" style={{ fontFamily: "JetBrains Mono, monospace" }} />
          </>
        )}
      </div>

      {/* Views threshold — the "optional benchmark": set it and the grid
          below only shows videos that crossed it. */}
      <div className="relative shrink-0">
        <input type="number" placeholder="Min views (optional)" value={filters.viewsThreshold}
          onChange={e => set("viewsThreshold")(e.target.value)}
          className="select-custom text-xs w-40 pr-3" style={{ fontFamily: "JetBrains Mono, monospace" }} />
      </div>

      {/* Format filter — options narrow to what the current platform can
          actually have (see FORMAT_OPTIONS_BY_PLATFORM above). */}
      <select value={filters.format} onChange={e => set("format")(e.target.value)}
        className="select-custom text-xs shrink-0" style={{ fontFamily: "Inter, sans-serif" }}>
        {FORMAT_OPTIONS_BY_PLATFORM[filters.platform].map(o => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>

      {/* Baseline metric — which trailing stat (mean vs. median) the
          overperform ratio badges/sort are computed against. Both are
          always in the API response (see backend/app/overperformance.py),
          so flipping this is instant, no re-fetch needed. */}
      <div className="flex rounded-lg overflow-hidden shrink-0" style={{ border: "1px solid var(--border)" }} title="Which baseline the overperform ratio is calculated from">
        {(["average", "median"] as OverperformMetric[]).map(m => (
          <button key={m} onClick={() => setFilters({ ...filters, metric: m })}
            className="px-3 py-1.5 text-xs transition-all"
            style={{
              background: filters.metric === m ? "var(--accent)" : "var(--bg-elevated)",
              color: filters.metric === m ? "#0d0096" : "var(--text-muted)",
              fontFamily: "Inter, sans-serif",
              fontWeight: 500,
            }}>
            {m === "average" ? "Avg" : "Median"}
          </button>
        ))}
      </div>

      {/* Sort */}
      <select value={filters.sortBy} onChange={e => set("sortBy")(e.target.value)}
        className="select-custom text-xs shrink-0" style={{ fontFamily: "Inter, sans-serif" }}>
        <option value="ratio">Sort: Overperform ratio</option>
        <option value="views">Sort: Total views</option>
        <option value="date">Sort: Publish date</option>
        <option value="engagement">Sort: Engagement</option>
      </select>

      {/* Chart toggle chip */}
      <button onClick={() => set("showChart")(!filters.showChart)}
        className={`filter-chip shrink-0 ${filters.showChart ? "active" : ""}`}>
        <BarChartIcon />
        Chart
      </button>

      {/* Spacer */}
      <div className="flex-1 min-w-0" />

      {/* Result count — the API caps a single page at PAGE_SIZE (see the
          "Load more" button below the grid), so this must show how many of
          the true total match are actually on screen, not just shownCount
          alone — otherwise a 500-video cap silently masquerades as "the
          total", which is exactly the bug this replaced. */}
      <span className="text-xs shrink-0" style={{ color: "var(--text-muted)", fontFamily: "JetBrains Mono, monospace" }}>
        {shownCount < totalResults ? `${shownCount} of ${totalResults} videos` : `${totalResults} videos`}
      </span>

      {/* View mode */}
      <div className="flex rounded-lg overflow-hidden shrink-0" style={{ border: "1px solid var(--border)" }}>
        <button onClick={() => setViewMode("grid")} className="p-1.5 transition-colors"
          style={{ background: viewMode === "grid" ? "var(--bg-active)" : "var(--bg-elevated)", color: viewMode === "grid" ? "var(--accent-light)" : "var(--text-muted)" }}>
          <GridIcon />
        </button>
        <button onClick={() => setViewMode("list")} className="p-1.5 transition-colors"
          style={{ background: viewMode === "list" ? "var(--bg-active)" : "var(--bg-elevated)", color: viewMode === "list" ? "var(--accent-light)" : "var(--text-muted)" }}>
          <ListIcon />
        </button>
      </div>
    </div>
  );
}

// ─── Video Card ───────────────────────────────────────────────────────────────

function VideoCard({ video, mode, metric = "average" }: { video: Video; mode: ViewMode; metric?: OverperformMetric }) {
  const ratio = metric === "median" ? video.overperformRatioMedian : video.overperformRatio;
  const overColor =
    ratio == null ? "var(--text-muted)"
    : ratio < 1 ? "#f87171"   // underperforming vs. baseline — always red, regardless of tier below
    : ratio >= 3 ? "#4ade80"
    : ratio >= 2 ? "#facc15"
    : "#fb923c";
  const baselineLabel = metric === "median" ? "vs median" : "vs avg";
  const thumb = video.thumbnail;
  const Wrapper = video.url ? "a" : "div";
  const wrapperProps = video.url ? { href: video.url, target: "_blank", rel: "noreferrer" } : {};

  if (mode === "list") {
    return (
      <Wrapper {...(wrapperProps as any)} className="video-card flex items-center gap-4 p-3 cursor-pointer group">
        <div className="relative shrink-0 rounded-lg overflow-hidden w-32 h-20" style={{ background: "var(--bg-elevated)" }}>
          {thumb ? <img src={thumb} alt={video.title} className="size-full object-cover" loading="lazy" /> : null}
          <div className="absolute bottom-1 right-1 text-[10px] px-1 rounded font-mono" style={{ background: "rgba(0,0,0,0.75)", color: "#fff" }}>
            {video.duration}
          </div>
          <div className="absolute top-1 left-1">
            <span className={`text-[10px] px-1.5 py-0.5 rounded ${video.platform === "youtube" ? "badge-yt" : "badge-ig"}`}>
              {video.platform === "youtube" ? <YTIcon size={9} /> : <IGIcon size={9} />}
            </span>
          </div>
        </div>

        <div className="flex-1 min-w-0">
          <div className="text-sm font-semibold truncate mb-1" style={{ color: "var(--text-primary)", fontFamily: "Lora, serif" }}>{video.title}</div>
          <div className="flex items-center gap-3 flex-wrap">
            <span className="text-xs" style={{ color: "var(--text-muted)", fontFamily: "Lora, serif" }}>{video.channelName}</span>
            <span className="text-xs" style={{ color: "var(--text-muted)" }}>·</span>
            <span className="text-xs font-mono" style={{ color: "var(--text-muted)" }}>{fmtDate(video.publishedAt)}</span>
            <span className="flex items-center gap-1 text-xs font-mono" style={{ color: "var(--text-muted)" }} title="Likes">
              <HeartIcon />{fmtViewsN(video.likes)}
            </span>
            <span className="flex items-center gap-1 text-xs font-mono" style={{ color: "var(--text-muted)" }} title="Comments">
              <CommentIcon />{fmtViewsN(video.comments)}
            </span>
          </div>
        </div>

        <div className="flex items-center gap-6 shrink-0">
          <div className="text-right">
            <div className="text-sm font-bold font-mono" style={{ color: "var(--text-primary)" }}>{fmtViews(video.views)}</div>
            <div className="text-[10px]" style={{ color: "var(--text-muted)" }}>views</div>
          </div>
          <div className="text-right">
            <div className="text-sm font-bold font-mono flex items-center gap-1" style={{ color: overColor }}>
              <TrendUpIcon />{fmtRatio(ratio)}
            </div>
            <div className="text-[10px]" style={{ color: "var(--text-muted)" }}>{baselineLabel}</div>
          </div>
          <Sparkline ratio={ratio ?? 1} color={overColor} />
          {ratio != null && ratio >= 2 && <span className="badge-overperform text-[10px] px-2 py-0.5 rounded-full font-mono font-bold">OVP</span>}
        </div>
      </Wrapper>
    );
  }

  return (
    <Wrapper {...(wrapperProps as any)} className="video-card cursor-pointer group flex flex-col">
      <div className="relative w-full aspect-video overflow-hidden" style={{ background: "var(--bg-elevated)" }}>
        {thumb ? (
          <img src={thumb} alt={video.title} className="size-full object-cover group-hover:scale-105 transition-transform duration-300" loading="lazy" />
        ) : (
          <div className="size-full flex items-center justify-center text-3xl">🎬</div>
        )}
        <div className="absolute inset-0 bg-gradient-to-t from-black/60 to-transparent" />
        <div className="absolute bottom-2 right-2 text-[10px] px-1.5 py-0.5 rounded font-mono font-medium" style={{ background: "rgba(0,0,0,0.8)", color: "#fff" }}>
          {video.duration}
        </div>
        <div className="absolute top-2 left-2 flex gap-1">
          <span className={`text-[10px] px-1.5 py-0.5 rounded-sm flex items-center gap-1 ${video.platform === "youtube" ? "badge-yt" : "badge-ig"}`}>
            {video.platform === "youtube" ? <YTIcon size={9} /> : <IGIcon size={9} />}
            {video.platform === "youtube" ? "YT" : "IG"}
          </span>
        </div>
        <div className="absolute top-2 right-2">
          {/* Opaque (not translucent) background — a low-opacity fill here
              used to wash out against bright thumbnails and become
              unreadable. Text color follows overColor: red below 1x
              (underperforming), tiered green/yellow/orange at and above it. */}
          <span
            className="text-[10px] px-1.5 py-0.5 rounded-sm font-mono font-bold flex items-center gap-1"
            style={{ background: "rgba(10,12,18,0.92)", color: overColor, border: `1px solid ${ratio == null ? "var(--border)" : overColor}` }}
          >
            <TrendUpIcon />{ratio == null ? "New" : `${ratio.toFixed(1)}x`}
          </span>
        </div>
      </div>

      <div className="p-3 flex flex-col gap-2 flex-1">
        <div className="text-sm font-semibold leading-snug line-clamp-2" style={{ color: "var(--text-primary)", fontFamily: "Lora, serif" }}>{video.title}</div>
        <div className="flex items-center justify-between">
          <span className="text-xs truncate" style={{ color: "var(--text-muted)", fontFamily: "Lora, serif" }}>{video.channelName}</span>
          <span className="text-[11px] font-mono shrink-0 ml-1" style={{ color: "var(--text-muted)" }}>{fmtDate(video.publishedAt)}</span>
        </div>
        <div className="flex items-center gap-3">
          <span className="flex items-center gap-1 text-[11px] font-mono" style={{ color: "var(--text-muted)" }} title="Likes">
            <HeartIcon />{fmtViewsN(video.likes)}
          </span>
          <span className="flex items-center gap-1 text-[11px] font-mono" style={{ color: "var(--text-muted)" }} title="Comments">
            <CommentIcon />{fmtViewsN(video.comments)}
          </span>
        </div>

        <div className="flex items-center gap-3 mt-auto pt-2" style={{ borderTop: "1px solid var(--border)" }}>
          <div className="flex-1">
            <div className="text-[10px] mb-0.5" style={{ color: "var(--text-muted)" }}>Views</div>
            <div className="text-sm font-bold font-mono" style={{ color: "var(--text-primary)" }}>{fmtViews(video.views)}</div>
          </div>
          <div className="flex-1">
            <div className="text-[10px] mb-0.5" style={{ color: "var(--text-muted)" }}>{metric === "median" ? "Median" : "Avg"}</div>
            <div className="text-sm font-mono" style={{ color: "var(--text-muted)" }}>{fmtViewsN(metric === "median" ? video.medianViews : video.avgViews)}</div>
          </div>
          <div>
            <Sparkline ratio={ratio ?? 1} color={overColor} />
          </div>
        </div>
      </div>
    </Wrapper>
  );
}

// ─── Chart Panel ──────────────────────────────────────────────────────────────

function ChartPanel({ videos, metric }: { videos: Video[]; metric: OverperformMetric }) {
  return (
    <div className="mx-5 mb-4 rounded-xl p-4" style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}>
      <div className="flex items-center justify-between mb-4">
        <div>
          <div className="text-sm font-semibold" style={{ color: "var(--text-primary)", fontFamily: "Lora, serif" }}>Overperformance by Channel</div>
          <div className="text-xs" style={{ color: "var(--text-muted)" }}>Ratio vs channel {metric === "median" ? "median" : "average"} baseline — filtered results</div>
        </div>
        <div className="flex items-center gap-3 text-xs" style={{ fontFamily: "Lora, serif" }}>
          <span className="flex items-center gap-1.5"><span className="size-2 rounded-sm inline-block" style={{ background: "var(--yt-red)" }} />YouTube</span>
          <span className="flex items-center gap-1.5"><span className="size-2 rounded-sm inline-block" style={{ background: "var(--ig-pink)" }} />Instagram</span>
        </div>
      </div>
      <BarChart videos={videos} metric={metric} />
    </div>
  );
}

// ─── Competitor Roster ────────────────────────────────────────────────────────
// Fills in what was previously just a sidebar nav item with no content: add,
// tag, and remove the channels this workspace tracks (see POST/PATCH/DELETE
// /api/channels in backend/app/routers/channels.py). Adding a channel here
// registers it for the next scrape run — it does not scrape immediately (see
// that router's module docstring for why).

function CompetitorRoster({ channels, onChanged }: { channels: Channel[]; onChanged: () => void }) {
  const [platform, setPlatform] = useState<"youtube" | "instagram">("youtube");
  const [handle, setHandle] = useState("");
  const [cohort, setCohort] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    if (!handle.trim()) return;
    setSubmitting(true);
    setFormError(null);
    try {
      await createChannel({ platform, handle: handle.trim(), cohort: cohort.trim() || null });
      setHandle("");
      setCohort("");
      onChanged();
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "Could not add that channel.");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleRemove(id: string) {
    await deleteChannel(id);
    onChanged();
  }

  async function handleToggleActive(c: Channel) {
    await updateChannel(c.id, { isActive: !c.isActive });
    onChanged();
  }

  return (
    <div className="p-5 max-w-3xl">
      <form onSubmit={handleAdd} className="rounded-xl p-4 mb-5 flex flex-wrap items-end gap-3" style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}>
        <div>
          <div className="text-[10px] uppercase tracking-widest mb-1" style={{ color: "var(--text-muted)" }}>Platform</div>
          <select value={platform} onChange={e => setPlatform(e.target.value as "youtube" | "instagram")} className="select-custom text-xs">
            <option value="youtube">YouTube</option>
            <option value="instagram">Instagram</option>
          </select>
        </div>
        <div className="flex-1 min-w-[200px]">
          <div className="text-[10px] uppercase tracking-widest mb-1" style={{ color: "var(--text-muted)" }}>
            {platform === "youtube" ? "@handle, channel URL, or channel ID" : "Instagram username"}
          </div>
          <input value={handle} onChange={e => setHandle(e.target.value)} placeholder={platform === "youtube" ? "@mkbhd" : "theverge"}
            className="select-custom text-xs w-full" style={{ fontFamily: "JetBrains Mono, monospace" }} />
        </div>
        <div>
          <div className="text-[10px] uppercase tracking-widest mb-1" style={{ color: "var(--text-muted)" }}>Cohort (optional)</div>
          <input value={cohort} onChange={e => setCohort(e.target.value)} placeholder="Tech Giants"
            className="select-custom text-xs w-40" />
        </div>
        <button type="submit" disabled={submitting || !handle.trim()}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all disabled:opacity-50"
          style={{ background: "var(--accent)", color: "#0d0096" }}>
          <PlusIcon />
          {submitting ? "Adding…" : "Track channel"}
        </button>
        {formError && <div className="text-xs w-full" style={{ color: "#fb923c" }}>{formError}</div>}
      </form>

      {channels.length === 0 ? (
        <div className="flex flex-col items-center justify-center h-48" style={{ color: "var(--text-muted)" }}>
          <div className="text-4xl mb-3">📡</div>
          <div className="text-sm" style={{ fontFamily: "Lora, serif" }}>No competitors tracked yet</div>
          <div className="text-xs mt-1">Add a YouTube or Instagram handle above to start scraping it.</div>
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {channels.map(c => (
            <ChannelCard key={c.id} channel={c} onToggleActive={() => handleToggleActive(c)} onRemove={() => handleRemove(c.id)} />
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Channel Card ─────────────────────────────────────────────────────────────
// Each tracked competitor's row in the roster, expanded from a plain name+subs
// line into a real card: identity/actions on top, then the channel-level
// stats (avg views, videos tracked, last published) that back it — those
// three are computed server-side from the channel's videos, see ChannelOut in
// backend/app/schemas.py. A channel that hasn't been scraped yet just shows
// "—" for them rather than 0, since 0 avg views would misleadingly read as
// "this channel underperforms" instead of "no data yet".

function ChannelCard({ channel: c, onToggleActive, onRemove }: { channel: Channel; onToggleActive: () => void; onRemove: () => void }) {
  return (
    <div className="video-card flex flex-col gap-3 p-3">
      <div className="flex items-center gap-3">
        <div className="flex items-center justify-center rounded-full size-9 shrink-0 text-xs font-bold" style={{ background: "var(--bg-elevated)", color: "var(--accent-light)" }}>
          {c.avatarUrl ? <img src={c.avatarUrl} alt={c.name} className="size-9 rounded-full object-cover" /> : c.avatar}
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-sm font-semibold truncate" style={{ color: "var(--text-primary)", fontFamily: "Lora, serif" }}>{c.name}</div>
          <div className="flex items-center gap-2 mt-0.5 flex-wrap">
            <span className={`text-[10px] px-1.5 rounded ${c.platform === "youtube" ? "badge-yt" : "badge-ig"}`}>{c.platform === "youtube" ? "YT" : "IG"}</span>
            <span className="text-xs font-mono" style={{ color: "var(--text-muted)" }}>@{c.handle}</span>
            {c.cohort && <span className="filter-chip">{c.cohort}</span>}
            {!c.isActive && (
              <span className="text-[10px] px-1.5 py-0.5 rounded" style={{ color: "var(--text-muted)", border: "1px solid var(--border)" }}>Paused</span>
            )}
          </div>
        </div>
        <button onClick={onToggleActive} className="text-xs px-2 py-1 rounded-lg shrink-0" style={{ color: "var(--text-muted)", border: "1px solid var(--border)" }}>
          {c.isActive ? "Pause" : "Resume"}
        </button>
        <button onClick={onRemove} className="flex items-center justify-center rounded-lg size-8 shrink-0 hover:bg-white/5" style={{ color: "var(--text-muted)" }}>
          <TrashIcon />
        </button>
      </div>

      <div className="flex items-center gap-5 flex-wrap pt-2" style={{ borderTop: "1px solid var(--border)" }}>
        <div>
          <div className="text-[10px] mb-0.5" style={{ color: "var(--text-muted)" }}>Subscribers</div>
          <div className="text-sm font-bold font-mono" style={{ color: "var(--text-primary)" }}>{c.subs}</div>
        </div>
        <div>
          <div className="text-[10px] mb-0.5" style={{ color: "var(--text-muted)" }}>Avg views</div>
          <div className="text-sm font-bold font-mono" style={{ color: "var(--text-primary)" }}>{fmtViewsN(c.avgViews)}</div>
        </div>
        <div className="flex items-center gap-1.5">
          <span style={{ color: "var(--text-muted)" }}><FilmIcon /></span>
          <div>
            <div className="text-[10px] mb-0.5" style={{ color: "var(--text-muted)" }}>Tracked</div>
            <div className="text-sm font-mono" style={{ color: "var(--text-muted)" }}>{c.videoCount} video{c.videoCount === 1 ? "" : "s"}</div>
          </div>
        </div>
        <div>
          <div className="text-[10px] mb-0.5" style={{ color: "var(--text-muted)" }}>Last published</div>
          <div className="text-sm font-mono" style={{ color: "var(--text-muted)" }}>{c.lastPublishedAt ? fmtDate(c.lastPublishedAt) : "—"}</div>
        </div>
      </div>
    </div>
  );
}

// ─── Channel Stat Card (Overperformance strip) ─────────────────────────────────
// A compact, read-only cousin of ChannelCard above — sits in a horizontally
// scrollable strip right under the Overperformance page's sticky filter bar
// (see visibleChannels in App()) to give at-a-glance channel context (subs,
// avg views, videos tracked, last published) for whichever channels the
// current filter/grid is actually showing. No pause/remove actions here —
// that's the Competitor Roster's job. Clicking the card itself narrows the
// grid to just this channel (sets filters.channels to [c.id]) — a shortcut
// for the same thing the "Channels" dropdown in the filter bar already does,
// since picking one channel out of a strip you're already looking at is
// faster than opening a dropdown and finding it in a list.

function ChannelStatCard({ channel: c, active, onClick, onClear }: { channel: Channel; active: boolean; onClick: () => void; onClear: () => void }) {
  return (
    <div
      className="video-card group relative flex flex-col gap-2 p-3 shrink-0"
      style={{
        width: 216,
        cursor: "pointer",
        borderColor: active ? "var(--accent)" : undefined,
        boxShadow: active ? "0 0 0 1px var(--accent)" : undefined,
      }}
      onClick={onClick}
      role="button"
      tabIndex={0}
      title={active ? `Showing only ${c.name} — pick another channel or clear in the filter bar to change` : `Show only videos from ${c.name}`}
      onKeyDown={e => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onClick();
        }
      }}
    >
      {/* Clears this channel back out of the filter — translucent and
          barely visible at rest so it doesn't clutter the card, fully
          opaque on hover so it's easy to hit once you're going for it. */}
      <button
        onClick={e => { e.stopPropagation(); onClear(); }}
        title={`Clear ${c.name} filter`}
        aria-label={`Clear ${c.name} filter`}
        className="absolute top-1.5 right-1.5 flex items-center justify-center rounded-full opacity-20 group-hover:opacity-100 hover:!opacity-100 transition-opacity"
        style={{ width: 18, height: 18, background: "rgba(10,12,18,0.85)", color: "var(--text-secondary)" }}
      >
        <XIcon size={8} />
      </button>
      <div className="flex items-center gap-2">
        <div className="flex items-center justify-center rounded-full size-8 shrink-0 text-[11px] font-bold" style={{ background: "var(--bg-elevated)", color: "var(--accent-light)" }}>
          {c.avatarUrl ? <img src={c.avatarUrl} alt={c.name} className="size-8 rounded-full object-cover" /> : c.avatar}
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-xs font-semibold truncate pr-4" style={{ color: "var(--text-primary)", fontFamily: "Lora, serif" }}>{c.name}</div>
          <div className="flex items-center gap-1.5 mt-0.5">
            <span className={`text-[9px] px-1 rounded ${c.platform === "youtube" ? "badge-yt" : "badge-ig"}`}>{c.platform === "youtube" ? "YT" : "IG"}</span>
            {c.cohort && <span className="filter-chip" style={{ fontSize: 9, padding: "1px 5px" }}>{c.cohort}</span>}
          </div>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-x-3 gap-y-1.5 pt-1.5" style={{ borderTop: "1px solid var(--border)" }}>
        <div>
          <div className="text-[9px]" style={{ color: "var(--text-muted)" }}>Subscribers</div>
          <div className="text-xs font-bold font-mono" style={{ color: "var(--text-primary)" }}>{c.subs}</div>
        </div>
        <div>
          <div className="text-[9px]" style={{ color: "var(--text-muted)" }}>Avg views</div>
          <div className="text-xs font-bold font-mono" style={{ color: "var(--text-primary)" }}>{fmtViewsN(c.avgViews)}</div>
        </div>
        <div>
          <div className="text-[9px]" style={{ color: "var(--text-muted)" }}>Median (last 10)</div>
          <div className="text-xs font-bold font-mono" style={{ color: "var(--text-primary)" }}>{fmtViewsN(c.medianViewsLast10)}</div>
        </div>
        <div>
          <div className="text-[9px]" style={{ color: "var(--text-muted)" }}>Tracked</div>
          <div className="text-xs font-mono" style={{ color: "var(--text-muted)" }}>{c.videoCount} vid{c.videoCount === 1 ? "" : "s"}</div>
        </div>
        <div className="col-span-2">
          <div className="text-[9px]" style={{ color: "var(--text-muted)" }}>Last pub.</div>
          <div className="text-xs font-mono" style={{ color: "var(--text-muted)" }}>{c.lastPublishedAt ? fmtDate(c.lastPublishedAt) : "—"}</div>
        </div>
      </div>
    </div>
  );
}

// ─── Main App ─────────────────────────────────────────────────────────────────

const EMPTY_VIDEOS: Video[] = [];

// How many videos one page fetches. The backend caps a single request at
// 2000 (see backend/app/routers/videos.py) and previously the frontend
// never sent a `limit` at all, silently falling back to its default of
// 500 — anything past that was invisible in the grid no matter how many
// videos actually matched the filters. Paging in smaller chunks with an
// explicit "Load more" button keeps both the request size and the number
// of cards rendered at once reasonable regardless of how large the table
// grows.
const VIDEOS_PAGE_SIZE = 60;

export default function App() {
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [activeSection, setActiveSection] = useState("Overperformance");
  const [notifOpen, setNotifOpen] = useState(false);
  const [viewMode, setViewMode] = useState<ViewMode>("grid");
  const notifRef = useRef<HTMLDivElement>(null);

  const [filters, setFilters] = useState<Filters>({
    platform: "all",
    channels: [],
    datePreset: "all",
    dateFrom: "",
    dateTo: "",
    viewsThreshold: "",
    sortBy: "ratio",
    metric: "median",
    showChart: false,
    format: "all",
  });

  const [channels, setChannels] = useState<Channel[]>([]);
  const [cohorts, setCohorts] = useState<CohortSummary[]>([]);
  const [systemStatus, setSystemStatus] = useState<SystemStatus | null>(null);

  const [videos, setVideos] = useState<Video[]>(EMPTY_VIDEOS);
  const [videosTotal, setVideosTotal] = useState(0);
  const [videosLoading, setVideosLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [videosError, setVideosError] = useState<string | null>(null);

  const [notifVideos, setNotifVideos] = useState<Video[]>(EMPTY_VIDEOS);
  const [notifLoading, setNotifLoading] = useState(false);

  const [refreshing, setRefreshing] = useState(false);
  const [refreshMessage, setRefreshMessage] = useState<{ text: string; kind: "success" | "error" } | null>(null);
  const [videosRefetchTick, setVideosRefetchTick] = useState(0);

  // The sidebar's "Apify Usage" toggle — null until the first load resolves,
  // so ToggleSwitch can stay disabled rather than flash a wrong default.
  const [scraperSettings, setScraperSettings] = useState<ScraperSettings | null>(null);
  const [togglingScraper, setTogglingScraper] = useState(false);

  const refreshChannelsAndCohorts = useCallback(() => {
    fetchChannels().then(setChannels).catch(() => {});
    fetchCohorts().then(setCohorts).catch(() => {});
    fetchSystemStatus().then(setSystemStatus).catch(() => {});
    fetchScraperSettings().then(setScraperSettings).catch(() => {});
  }, []);

  const handleToggleInstagramScraping = useCallback(async () => {
    if (!scraperSettings || togglingScraper) return;
    const next = !scraperSettings.instagramScrapingEnabled;
    setTogglingScraper(true);
    try {
      setScraperSettings(await setInstagramScrapingEnabled(next));
    } catch {
      // Leave the switch as-is on failure — the next refreshChannelsAndCohorts
      // (initial load, or after a manual refresh) resyncs it from the server.
    } finally {
      setTogglingScraper(false);
    }
  }, [scraperSettings, togglingScraper]);

  // "Refresh data" button in the top bar — see src/lib/api.ts's
  // triggerManualScrape docstring for why this hits a different,
  // cooldown-limited endpoint instead of the API-key-protected one the
  // GitHub Actions schedule uses.
  const handleManualRefresh = useCallback(async () => {
    if (refreshing) return;
    setRefreshing(true);
    setRefreshMessage(null);
    try {
      const result = await triggerManualScrape();
      const totalVideos = result.runs.reduce((sum, r) => sum + r.videosUpserted, 0);
      const failed = result.runs.filter(r => r.status === "failed");
      const skippedInstagram = result.runs.some(r => r.platform === "instagram" && r.status === "skipped");
      setRefreshMessage(
        failed.length > 0
          ? { text: failed[0].errorMessage ?? "Refresh finished with errors.", kind: "error" }
          : {
              text: `Refreshed — ${totalVideos} video${totalVideos === 1 ? "" : "s"} updated.${skippedInstagram ? " Instagram paused." : ""}`,
              kind: "success",
            },
      );
      refreshChannelsAndCohorts();
      setVideosRefetchTick(t => t + 1);
    } catch (err) {
      setRefreshMessage({
        text: err instanceof ApiError ? err.message : "Could not start a refresh.",
        kind: "error",
      });
    } finally {
      setRefreshing(false);
      window.setTimeout(() => setRefreshMessage(null), 6000);
    }
  }, [refreshing, refreshChannelsAndCohorts]);

  // Initial load.
  useEffect(() => {
    refreshChannelsAndCohorts();
  }, [refreshChannelsAndCohorts]);

  // Re-fetch videos whenever a filter changes. Debounced so typing in the
  // "min views" box doesn't fire a request per keystroke — filtering now
  // happens server-side (see backend/app/routers/videos.py) rather than in
  // a client-side useMemo, since it needs to scale past a hardcoded array.
  useEffect(() => {
    setVideosLoading(true);
    setVideosError(null);
    const handle = window.setTimeout(() => {
      fetchVideos({
        platform: filters.platform,
        channels: filters.channels,
        dateFrom: filters.dateFrom,
        dateTo: filters.dateTo,
        viewsThreshold: filters.viewsThreshold,
        format: filters.format,
        sortBy: filters.sortBy,
        metric: filters.metric,
        limit: VIDEOS_PAGE_SIZE,
        offset: 0,
      })
        .then(result => {
          setVideos(result.videos);
          setVideosTotal(result.total);
          setVideosLoading(false);
        })
        .catch(err => {
          setVideosError(err instanceof ApiError ? err.message : "Could not load videos.");
          setVideosLoading(false);
        });
    }, 300);
    return () => window.clearTimeout(handle);
  }, [filters, videosRefetchTick]);

  // "Load more" button below the grid — fetches the next VIDEOS_PAGE_SIZE
  // videos at the current offset (videos.length) and appends rather than
  // replaces. Uses the same filters as the main fetch above so the next
  // page honors whatever's currently selected.
  const handleLoadMore = useCallback(() => {
    if (loadingMore || videosLoading || videos.length >= videosTotal) return;
    setLoadingMore(true);
    fetchVideos({
      platform: filters.platform,
      channels: filters.channels,
      dateFrom: filters.dateFrom,
      dateTo: filters.dateTo,
      viewsThreshold: filters.viewsThreshold,
      format: filters.format,
      sortBy: filters.sortBy,
      metric: filters.metric,
      limit: VIDEOS_PAGE_SIZE,
      offset: videos.length,
    })
      .then(result => {
        setVideos(prev => [...prev, ...result.videos]);
        setVideosTotal(result.total);
        setLoadingMore(false);
      })
      .catch(err => {
        setVideosError(err instanceof ApiError ? err.message : "Could not load more videos.");
        setLoadingMore(false);
      });
  }, [filters, videos.length, videosTotal, loadingMore, videosLoading]);

  // Backs the channel strip under the Overperformance page's filter bar: the
  // explicitly selected channels when the "Channels" filter is narrowed,
  // otherwise whichever tracked channels actually have a video in the
  // current (filtered) results — so the strip always matches what's in the
  // grid below it rather than dumping every tracked channel onto the page.
  const visibleChannels = useMemo(() => {
    if (filters.channels.length > 0) {
      const selected = new Set(filters.channels);
      return channels.filter(c => selected.has(c.id));
    }
    const shownIds = new Set(videos.map(v => v.channelId));
    return channels.filter(c => shownIds.has(c.id));
  }, [channels, filters.channels, videos]);

  useEffect(() => {
    function handler(e: MouseEvent) {
      if (notifRef.current && !notifRef.current.contains(e.target as Node)) setNotifOpen(false);
    }
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  function openNotifications() {
    setNotifOpen(o => {
      const next = !o;
      if (next) {
        setNotifLoading(true);
        // metric: "median" matches the Overperformance page's default (see
        // the initial filters.metric below) and app/routers/system.py's
        // overperformCount, so the bell shows the same videos the badge
        // count is counting rather than silently falling back to average.
        fetchVideos({ platform: "all", channels: [], dateFrom: "", dateTo: "", viewsThreshold: "", format: "all", sortBy: "ratio", metric: "median", limit: 50 })
          .then(result => {
            setNotifVideos(result.videos.filter(v => v.overperformRatioMedian != null && v.overperformRatioMedian >= 2));
            setNotifLoading(false);
          })
          .catch(() => setNotifLoading(false));
      }
      return next;
    });
  }

  return (
    <div className="flex h-full overflow-hidden" style={{ background: "var(--bg-base)", fontFamily: "Lora, serif" }}>
      <Sidebar
        open={sidebarOpen}
        activeSection={activeSection}
        setActiveSection={setActiveSection}
        overperformBadge={systemStatus?.overperformCount ?? null}
        cohorts={cohorts}
        quotaPct={systemStatus?.youtubeQuotaPct ?? null}
        instagramScrapingEnabled={scraperSettings?.instagramScrapingEnabled ?? null}
        onToggleInstagramScraping={handleToggleInstagramScraping}
        togglingScraper={togglingScraper}
      />

      {/* Main */}
      <div className="flex flex-col flex-1 min-w-0 overflow-hidden">

        {/* Top Bar */}
        <div className="flex items-center justify-between px-5 py-3 shrink-0" style={{ borderBottom: "1px solid var(--border)", background: "var(--bg-panel)" }}>
          <div className="flex items-center gap-3">
            <button onClick={() => setSidebarOpen(o => !o)}
              className="flex items-center justify-center rounded-lg size-8 transition-colors hover:bg-white/5"
              style={{ color: "var(--text-muted)", border: "1px solid var(--border)" }}>
              <MenuIcon />
            </button>
            <button onClick={() => setActiveSection("Overperformance")}
              title="Home"
              className="flex items-center justify-center rounded-lg size-8 transition-colors hover:bg-white/5"
              style={{
                color: activeSection === "Overperformance" ? "var(--accent-light)" : "var(--text-muted)",
                border: `1px solid ${activeSection === "Overperformance" ? "var(--accent)" : "var(--border)"}`,
              }}>
              <HomeIcon />
            </button>
            <div>
              <h1 className="text-sm font-bold leading-none" style={{ color: "var(--text-primary)", fontFamily: "Lora, serif" }}>
                {activeSection}
              </h1>
              <p className="text-[11px] mt-0.5" style={{ color: "var(--text-muted)" }}>
                Competitor video intelligence · {currentMonthLabel()}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {/* Active filters summary */}
            <div className="flex items-center gap-1.5 flex-wrap">
              {filters.platform !== "all" && (
                <span className="filter-chip active">
                  {filters.platform === "youtube" ? <YTIcon size={10} /> : <IGIcon size={10} />}
                  {filters.platform}
                  <button onClick={() => setFilters({ ...filters, platform: "all", format: nextFormatForPlatform(filters.format, "all") })}><XIcon /></button>
                </span>
              )}
              {filters.channels.length > 0 && (
                <span className="filter-chip active">
                  {filters.channels.length} ch
                  <button onClick={() => setFilters({ ...filters, channels: [] })}><XIcon /></button>
                </span>
              )}
              {filters.viewsThreshold && (
                <span className="filter-chip active">
                  ≥{fmtViews(Number(filters.viewsThreshold))}
                  <button onClick={() => setFilters({ ...filters, viewsThreshold: "" })}><XIcon /></button>
                </span>
              )}
            </div>

            {/* Refresh data */}
            <div className="relative flex items-center gap-2">
              {refreshMessage && (
                <span
                  className="text-[11px] px-2 py-1 rounded-md whitespace-nowrap"
                  style={{
                    color: refreshMessage.kind === "success" ? "var(--accent-light)" : "#f87171",
                    background: "var(--bg-base)",
                    border: `1px solid ${refreshMessage.kind === "success" ? "var(--accent)" : "#f87171"}`,
                  }}
                >
                  {refreshMessage.text}
                </span>
              )}
              <button
                onClick={handleManualRefresh}
                disabled={refreshing}
                title={
                  systemStatus?.lastScrapeStartedAt
                    ? `Last refreshed ${fmtRelativeTime(systemStatus.lastScrapeStartedAt)}`
                    : "Fetch the latest videos right now"
                }
                className="flex items-center gap-1.5 rounded-lg h-9 px-3 transition-colors hover:bg-white/5 disabled:opacity-50"
                style={{ color: "var(--text-muted)", border: "1px solid var(--border)" }}
              >
                <span className={refreshing ? "animate-spin" : undefined}><RefreshIcon /></span>
                <span className="text-xs" style={{ fontFamily: "Lora, serif" }}>
                  {refreshing ? "Refreshing…" : "Refresh data"}
                </span>
              </button>
              {!refreshing && systemStatus?.lastScrapeStartedAt && (
                <span className="text-[10px] hidden sm:inline" style={{ color: "var(--text-muted)" }}>
                  Updated {fmtRelativeTime(systemStatus.lastScrapeStartedAt)}
                </span>
              )}
            </div>

            {/* Notification bell */}
            <div className="relative" ref={notifRef}>
              <button onClick={openNotifications}
                className="flex items-center justify-center rounded-lg size-9 transition-colors hover:bg-white/5"
                style={{ color: notifOpen ? "var(--accent-light)" : "var(--text-muted)", border: `1px solid ${notifOpen ? "var(--accent)" : "var(--border)"}` }}>
                <BellIcon />
                <span className="notification-dot" />
              </button>
              {notifOpen && <NotificationPanel videos={notifVideos} loading={notifLoading} onClose={() => setNotifOpen(false)} />}
            </div>
          </div>
        </div>

        {activeSection === "Add Channel" ? (
          <div className="flex-1 overflow-y-auto">
            <CompetitorRoster channels={channels} onChanged={refreshChannelsAndCohorts} />
          </div>
        ) : (
          <>
            {/* Filter Bar */}
            <FilterBar filters={filters} setFilters={setFilters} viewMode={viewMode} setViewMode={setViewMode} shownCount={videos.length} totalResults={videosTotal} channels={channels} />

            {/* Content */}
            <div className="flex-1 overflow-y-auto">
              {visibleChannels.length > 0 && (
                <div className="px-5 pt-4 pb-1 flex items-stretch gap-3 overflow-x-auto">
                  {visibleChannels.map(c => (
                    <ChannelStatCard
                      key={c.id}
                      channel={c}
                      active={filters.channels.length === 1 && filters.channels[0] === c.id}
                      onClick={() => setFilters({ ...filters, channels: [c.id] })}
                      onClear={() => setFilters({ ...filters, channels: filters.channels.filter(id => id !== c.id) })}
                    />
                  ))}
                </div>
              )}

              {filters.showChart && <ChartPanel videos={videos} metric={filters.metric} />}

              {videosError ? (
                <div className="flex flex-col items-center justify-center h-64" style={{ color: "var(--text-muted)" }}>
                  <div className="text-4xl mb-3">⚠️</div>
                  <div className="text-sm" style={{ fontFamily: "Lora, serif" }}>Couldn't load videos</div>
                  <div className="text-xs mt-1">{videosError}</div>
                </div>
              ) : videosLoading ? (
                <div className="flex flex-col items-center justify-center h-64" style={{ color: "var(--text-muted)" }}>
                  <div className="text-sm" style={{ fontFamily: "Lora, serif" }}>Loading videos…</div>
                </div>
              ) : videos.length === 0 ? (
                <div className="flex flex-col items-center justify-center h-64" style={{ color: "var(--text-muted)" }}>
                  <div className="text-4xl mb-3">📭</div>
                  <div className="text-sm" style={{ fontFamily: "Lora, serif" }}>No videos match your filters</div>
                  <div className="text-xs mt-1">
                    {channels.length === 0
                      ? "Add a channel in Add Channel to get started."
                      : "Try adjusting the date range or views threshold."}
                  </div>
                </div>
              ) : (
                <>
                  {viewMode === "grid" ? (
                    <div className="p-5 grid gap-4" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))" }}>
                      {videos.map(v => <VideoCard key={v.id} video={v} mode="grid" metric={filters.metric} />)}
                    </div>
                  ) : (
                    <div className="p-5 flex flex-col gap-2">
                      {videos.map(v => <VideoCard key={v.id} video={v} mode="list" metric={filters.metric} />)}
                    </div>
                  )}
                  {videos.length < videosTotal && (
                    <div className="flex flex-col items-center gap-2 pb-8">
                      <button
                        onClick={handleLoadMore}
                        disabled={loadingMore}
                        className="px-4 py-2 rounded-lg text-xs font-semibold transition-opacity"
                        style={{
                          background: "var(--bg-elevated)",
                          border: "1px solid var(--border)",
                          color: "var(--text-secondary)",
                          fontFamily: "Inter, sans-serif",
                          opacity: loadingMore ? 0.6 : 1,
                          cursor: loadingMore ? "default" : "pointer",
                        }}>
                        {loadingMore ? "Loading…" : `Load more (${videosTotal - videos.length} remaining)`}
                      </button>
                    </div>
                  )}
                </>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
