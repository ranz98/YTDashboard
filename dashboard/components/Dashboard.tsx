"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { Snapshot, Status, Video } from "@/lib/types";
import { STATUSES } from "@/lib/types";
import {
  formatBytes,
  formatDate,
  formatDateTime,
  formatDuration,
  relativeTime,
} from "@/lib/format";
import { StatCard } from "./StatCard";
import { StageDot, StatusBadge, STATUS_LABELS } from "./StatusBadge";
import { ActivityTable, StageStrip } from "./Activity";

type Tab =
  | "overview"
  | "activity"
  | "all"
  | "scheduled"
  | "downloaded"
  | "edited"
  | "uploaded"
  | "successful"
  | "failed";

const TABS: { key: Tab; label: string }[] = [
  { key: "overview", label: "Overview" },
  { key: "activity", label: "Activity" },
  { key: "all", label: "All Videos" },
  { key: "scheduled", label: "Scheduled" },
  { key: "downloaded", label: "Downloaded" },
  { key: "edited", label: "Edited" },
  { key: "uploaded", label: "Uploaded" },
  { key: "successful", label: "Successful" },
  { key: "failed", label: "Failed" },
];

/** How often the dashboard re-reads the API. The VPS pushes on every stage
 *  transition, so this only bounds how stale the view can get. */
const POLL_MS = 10_000;

type SortKey = "updatedAt" | "createdAt" | "title" | "status";
const PAGE_SIZE = 12;

/** Which videos belong under each tab.
 *  Stage tabs are cumulative — a video that reached "uploaded" has genuinely
 *  been downloaded and edited, so it still shows under those tabs. Filtering
 *  on the literal status alone would make the earlier tabs look empty as soon
 *  as the pipeline moved on. */
function inTab(video: Video, tab: Tab): boolean {
  switch (tab) {
    case "all":
    case "overview":
    case "activity":
      return true;
    case "scheduled":
      return video.status === "scheduled";
    case "downloaded":
      return video.download.done;
    case "edited":
      return video.edit.done;
    case "uploaded":
      return video.upload.done;
    case "successful":
      return video.status === "successful";
    case "failed":
      return video.status === "failed" || video.status === "cancelled";
    default:
      return true;
  }
}

function ThemeToggle() {
  const [dark, setDark] = useState(false);

  useEffect(() => {
    setDark(document.documentElement.classList.contains("dark"));
  }, []);

  const toggle = () => {
    const next = !dark;
    setDark(next);
    document.documentElement.classList.toggle("dark", next);
    try {
      localStorage.setItem("theme", next ? "dark" : "light");
    } catch {
      /* private mode - the toggle still works for this page view */
    }
  };

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label="Toggle dark mode"
      className="panel px-3 py-1.5 text-sm hover:opacity-80"
    >
      {dark ? "Light" : "Dark"}
    </button>
  );
}

function Pipeline({ video }: { video: Video }) {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
      <StageDot done={video.download.done} label="Down" />
      <StageDot done={video.edit.done} label="Edit" />
      <StageDot done={video.upload.done} label="Up" />
    </div>
  );
}

function EmptyState({ tab, isDemo }: { tab: Tab; isDemo: boolean }) {
  return (
    <div className="px-6 py-16 text-center">
      <div className="text-base font-medium">No videos here yet</div>
      <p className="muted mx-auto mt-2 max-w-md text-sm">
        {tab === "all" || tab === "overview" ? (
          <>
            The pipeline has not produced anything yet. Run{" "}
            <code className="font-mono text-xs">batch\RUNPIPELINE.bat</code>,
            then sync the dashboard with{" "}
            <code className="font-mono text-xs">npm run sync</code>.
          </>
        ) : (
          <>Nothing has reached the {STATUS_LABELS[tab as Status] ?? tab} stage.</>
        )}
      </p>
      {isDemo ? null : (
        <p className="muted mt-3 text-xs">
          Reading live data — this reflects the real contents of{" "}
          <code className="font-mono">output/videos</code>.
        </p>
      )}
    </div>
  );
}

export function Dashboard({ initial }: { initial: Snapshot }) {
  const [snapshot, setSnapshot] = useState<Snapshot>(initial);
  const [tab, setTab] = useState<Tab>("overview");
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<Status | "all">("all");
  const [sortKey, setSortKey] = useState<SortKey>("updatedAt");
  const [sortAsc, setSortAsc] = useState(false);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());

  // Relative timestamps are computed on the client only, after mount, so the
  // server-rendered markup and the first client render agree.
  useEffect(() => {
    setNow(Date.now());
    const timer = setInterval(() => setNow(Date.now()), 60_000);
    return () => clearInterval(timer);
  }, []);

  const refresh = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const res = await fetch("/api/pipeline", { cache: "no-store" });
      if (!res.ok) throw new Error(`API returned ${res.status}`);
      const data = (await res.json()) as Snapshot;
      if (!data || !Array.isArray(data.videos)) {
        throw new Error("Malformed snapshot payload");
      }
      setSnapshot(data);
      setNow(Date.now());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not refresh");
    } finally {
      if (!silent) setLoading(false);
    }
  }, []);

  // Background poll. Silent so a transient blip does not flash the whole UI
  // into a loading state while the user is reading it.
  useEffect(() => {
    const timer = setInterval(() => void refresh(true), POLL_MS);
    return () => clearInterval(timer);
  }, [refresh]);

  useEffect(() => setPage(1), [tab, query, statusFilter, sortKey, sortAsc]);

  const videos = snapshot.videos ?? [];
  const summary = snapshot.summary;
  const isDemo = snapshot.source === "demo";
  const runs = snapshot.runs ?? [];
  const activeRun = runs.find((r) => r.status === "running") ?? null;

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    let rows = videos.filter((v) => inTab(v, tab));
    if (statusFilter !== "all") {
      rows = rows.filter((v) => v.status === statusFilter);
    }
    if (q) {
      rows = rows.filter(
        (v) =>
          v.title.toLowerCase().includes(q) ||
          v.id.toLowerCase().includes(q) ||
          (v.channel ?? "").toLowerCase().includes(q) ||
          (v.originalTitle ?? "").toLowerCase().includes(q),
      );
    }
    const dir = sortAsc ? 1 : -1;
    return [...rows].sort((a, b) => {
      if (sortKey === "title") return dir * a.title.localeCompare(b.title);
      if (sortKey === "status") return dir * a.status.localeCompare(b.status);
      const av = a[sortKey] ?? "";
      const bv = b[sortKey] ?? "";
      return dir * String(av).localeCompare(String(bv));
    });
  }, [videos, tab, statusFilter, query, sortKey, sortAsc]);

  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const safePage = Math.min(page, pageCount);
  const pageRows = filtered.slice(
    (safePage - 1) * PAGE_SIZE,
    safePage * PAGE_SIZE,
  );

  const successful = useMemo(
    () => videos.filter((v) => v.status === "successful"),
    [videos],
  );

  const sortButton = (key: SortKey, label: string) => (
    <button
      type="button"
      onClick={() => {
        if (sortKey === key) setSortAsc(!sortAsc);
        else {
          setSortKey(key);
          setSortAsc(false);
        }
      }}
      className="inline-flex items-center gap-1 hover:underline"
    >
      {label}
      {sortKey === key ? (
        <span aria-hidden className="text-[10px]">{sortAsc ? "▲" : "▼"}</span>
      ) : null}
    </button>
  );

  return (
    <div className="mx-auto max-w-[1400px] px-4 py-6 sm:px-6 lg:px-8">
      <header className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">
            Pipeline Dashboard
          </h1>
          <p className="muted mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
            <span>Updated {formatDateTime(snapshot.generatedAt)}</span>
            <span aria-hidden>·</span>
            <span>
              <span className="font-mono text-xs">{videos.length}</span> video
              {videos.length === 1 ? "" : "s"} tracked
            </span>
            {activeRun ? (
              <>
                <span aria-hidden>·</span>
                <span className="inline-flex items-center gap-1.5 font-medium text-amber-600 dark:text-amber-400">
                  <span
                    aria-hidden
                    className="h-1.5 w-1.5 animate-pulse rounded-full bg-current"
                  />
                  {activeRun.stage} running
                </span>
              </>
            ) : null}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => void refresh()}
            disabled={loading}
            className="panel px-3 py-1.5 text-sm hover:opacity-80 disabled:opacity-50"
          >
            {loading ? "Refreshing…" : "Refresh"}
          </button>
          <ThemeToggle />
        </div>
      </header>

      {isDemo ? (
        <div className="mb-4 rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200">
          <strong className="font-semibold">Demo data.</strong> No real pipeline
          output was found. Run the pipeline, then{" "}
          <code className="font-mono text-xs">npm run sync</code> to replace this
          with live data.
        </div>
      ) : null}

      {error ? (
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-rose-300 bg-rose-50 px-4 py-3 text-sm text-rose-900 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-200">
          <span>
            <strong className="font-semibold">Could not refresh.</strong> {error}
          </span>
          <button
            type="button"
            onClick={() => void refresh()}
            className="rounded-md border border-rose-400/50 px-2.5 py-1 text-xs hover:opacity-80"
          >
            Try again
          </button>
        </div>
      ) : null}

      <nav className="table-scroll mb-5 border-b" style={{ borderColor: "var(--border)" }}>
        <div className="flex min-w-max gap-1">
          {TABS.map((t) => {
            const count =
              t.key === "overview"
                ? null
                : t.key === "activity"
                  ? runs.length
                  : videos.filter((v) => inTab(v, t.key)).length;
            const active = tab === t.key;
            return (
              <button
                key={t.key}
                type="button"
                onClick={() => setTab(t.key)}
                className={`-mb-px whitespace-nowrap border-b-2 px-3 py-2 text-sm transition-colors ${
                  active
                    ? "border-current font-medium"
                    : "muted border-transparent hover:opacity-80"
                }`}
                style={active ? { color: "var(--accent)" } : undefined}
              >
                {t.label}
                {count !== null ? (
                  <span className="muted ml-1.5 text-xs tabular-nums">{count}</span>
                ) : null}
              </button>
            );
          })}
        </div>
      </nav>

      {tab === "activity" ? (
        <section className="space-y-4">
          <StageStrip runs={runs} />
          <ActivityTable runs={runs} now={now} />
        </section>
      ) : tab === "overview" ? (
        <section className="space-y-6">
          <StageStrip runs={runs} />
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
            <StatCard label="Total" value={summary.total} />
            <StatCard label="Scheduled" value={summary.byStatus.scheduled} />
            <StatCard
              label="Processing"
              value={summary.byStatus.processing}
              tone="busy"
            />
            <StatCard label="Downloaded" value={summary.downloaded} />
            <StatCard label="Edited" value={summary.edited} />
            <StatCard label="Uploaded" value={summary.uploaded} />
          </div>

          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
            <StatCard
              label="Successful"
              value={summary.byStatus.successful}
              tone="good"
            />
            <StatCard label="Failed" value={summary.byStatus.failed} tone="bad" />
            <StatCard label="Cancelled" value={summary.byStatus.cancelled} />
            <StatCard label="Today" value={summary.processedToday} hint="processed" />
            <StatCard
              label="This week"
              value={summary.processedThisWeek}
              hint="processed"
            />
            <StatCard
              label="This month"
              value={summary.processedThisMonth}
              hint="processed"
            />
          </div>

          <div className="panel p-5">
            <h2 className="text-sm font-semibold">Pipeline funnel</h2>
            <p className="muted mt-1 text-xs">
              How far the tracked videos have progressed.
            </p>
            <div className="mt-4 space-y-3">
              {(
                [
                  ["Downloaded", summary.downloaded],
                  ["Edited", summary.edited],
                  ["Uploaded", summary.uploaded],
                  ["Successful", summary.byStatus.successful],
                ] as const
              ).map(([label, value]) => {
                const pct = summary.total ? (value / summary.total) * 100 : 0;
                return (
                  <div key={label}>
                    <div className="mb-1 flex justify-between text-xs">
                      <span>{label}</span>
                      <span className="muted tabular-nums">
                        {value} / {summary.total}
                      </span>
                    </div>
                    <div
                      className="h-2 overflow-hidden rounded-full"
                      style={{ background: "var(--border)" }}
                    >
                      <div
                        className="h-full rounded-full"
                        style={{
                          width: `${pct}%`,
                          background: "var(--accent)",
                        }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
            {summary.avgProcessingMs ? (
              <p className="muted mt-4 text-xs">
                Average time from first artifact to upload:{" "}
                <strong className="font-medium">
                  {formatDuration(summary.avgProcessingMs)}
                </strong>
              </p>
            ) : null}
          </div>
        </section>
      ) : tab === "successful" ? (
        <section className="panel overflow-hidden">
          <div className="table-scroll">
            <table className="w-full min-w-[820px] text-left text-sm">
              <thead
                className="muted border-b text-xs uppercase tracking-wide"
                style={{ borderColor: "var(--border)" }}
              >
                <tr>
                  <th className="px-4 py-3 font-medium">Video</th>
                  <th className="px-4 py-3 font-medium">Uploaded</th>
                  <th className="px-4 py-3 font-medium">Duration</th>
                  <th className="px-4 py-3 font-medium">Status</th>
                  <th className="px-4 py-3 font-medium">Link</th>
                </tr>
              </thead>
              <tbody>
                {successful.map((v) => (
                  <tr
                    key={v.id}
                    className="border-b last:border-0"
                    style={{ borderColor: "var(--border)" }}
                  >
                    <td className="px-4 py-3">
                      <div className="font-medium">{v.title}</div>
                      <div className="muted font-mono text-xs">{v.id}</div>
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap">
                      {formatDateTime(v.upload.at)}
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap tabular-nums">
                      {formatDuration(v.processingMs)}
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge status={v.status} />
                    </td>
                    <td className="px-4 py-3">
                      {v.upload.url ? (
                        <a
                          href={v.upload.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="hover:underline"
                          style={{ color: "var(--accent)" }}
                        >
                          Watch
                        </a>
                      ) : v.sourceUrl ? (
                        <a
                          href={v.sourceUrl}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="muted hover:underline"
                        >
                          Source
                        </a>
                      ) : (
                        <span className="muted">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {successful.length === 0 ? (
            <EmptyState tab={tab} isDemo={isDemo} />
          ) : null}
        </section>
      ) : (
        <section className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search title, id or channel…"
              className="panel min-w-0 flex-1 px-3 py-2 text-sm outline-none focus:ring-2"
              style={{ background: "var(--panel)" }}
            />
            <select
              value={statusFilter}
              onChange={(e) =>
                setStatusFilter(e.target.value as Status | "all")
              }
              className="panel px-3 py-2 text-sm outline-none"
              aria-label="Filter by status"
            >
              <option value="all">All statuses</option>
              {STATUSES.map((s) => (
                <option key={s} value={s}>
                  {STATUS_LABELS[s]}
                </option>
              ))}
            </select>
          </div>

          <div className="panel overflow-hidden">
            <div className="table-scroll">
              <table className="w-full min-w-[1000px] text-left text-sm">
                <thead
                  className="muted border-b text-xs uppercase tracking-wide"
                  style={{ borderColor: "var(--border)" }}
                >
                  <tr>
                    <th className="px-4 py-3 font-medium">
                      {sortButton("title", "Video")}
                    </th>
                    <th className="px-4 py-3 font-medium">
                      {sortButton("status", "Status")}
                    </th>
                    <th className="px-4 py-3 font-medium">Scheduled</th>
                    <th className="px-4 py-3 font-medium">Stages</th>
                    <th className="px-4 py-3 font-medium">Size</th>
                    <th className="px-4 py-3 font-medium">
                      {sortButton("createdAt", "Created")}
                    </th>
                    <th className="px-4 py-3 font-medium">
                      {sortButton("updatedAt", "Updated")}
                    </th>
                    <th className="px-4 py-3 font-medium">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {pageRows.map((v) => (
                    <tr
                      key={v.id}
                      className="border-b last:border-0"
                      style={{ borderColor: "var(--border)" }}
                    >
                      <td className="px-4 py-3">
                        <div className="max-w-[280px] truncate font-medium" title={v.title}>
                          {v.title}
                        </div>
                        <div className="muted font-mono text-xs">
                          {v.id}
                          {v.channel ? ` · ${v.channel}` : ""}
                        </div>
                        {v.error ? (
                          <div className="mt-1 text-xs text-rose-600 dark:text-rose-400">
                            {v.error}
                          </div>
                        ) : null}
                      </td>
                      <td className="px-4 py-3">
                        <StatusBadge status={v.status} />
                      </td>
                      <td className="muted px-4 py-3 whitespace-nowrap">
                        {formatDate(v.scheduledAt)}
                      </td>
                      <td className="px-4 py-3">
                        <Pipeline video={v} />
                      </td>
                      <td className="muted px-4 py-3 whitespace-nowrap tabular-nums">
                        {formatBytes(v.edit.sizeBytes ?? v.download.sizeBytes)}
                      </td>
                      <td className="muted px-4 py-3 whitespace-nowrap">
                        {formatDate(v.createdAt)}
                      </td>
                      <td className="muted px-4 py-3 whitespace-nowrap">
                        {relativeTime(v.updatedAt, now)}
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap">
                        <div className="flex gap-3">
                          {v.upload.url ? (
                            <a
                              href={v.upload.url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="hover:underline"
                              style={{ color: "var(--accent)" }}
                            >
                              Watch
                            </a>
                          ) : null}
                          {v.sourceUrl ? (
                            <a
                              href={v.sourceUrl}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="muted hover:underline"
                            >
                              Source
                            </a>
                          ) : null}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {pageRows.length === 0 ? (
              query || statusFilter !== "all" ? (
                <div className="px-6 py-16 text-center">
                  <div className="text-base font-medium">No matches</div>
                  <p className="muted mt-2 text-sm">
                    Nothing matches that search or filter.
                  </p>
                  <button
                    type="button"
                    onClick={() => {
                      setQuery("");
                      setStatusFilter("all");
                    }}
                    className="panel mt-4 px-3 py-1.5 text-sm hover:opacity-80"
                  >
                    Clear filters
                  </button>
                </div>
              ) : (
                <EmptyState tab={tab} isDemo={isDemo} />
              )
            ) : null}
          </div>

          {pageCount > 1 ? (
            <div className="flex items-center justify-between text-sm">
              <span className="muted">
                {(safePage - 1) * PAGE_SIZE + 1}–
                {Math.min(safePage * PAGE_SIZE, filtered.length)} of{" "}
                {filtered.length}
              </span>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => setPage(safePage - 1)}
                  disabled={safePage <= 1}
                  className="panel px-3 py-1.5 hover:opacity-80 disabled:opacity-40"
                >
                  Previous
                </button>
                <button
                  type="button"
                  onClick={() => setPage(safePage + 1)}
                  disabled={safePage >= pageCount}
                  className="panel px-3 py-1.5 hover:opacity-80 disabled:opacity-40"
                >
                  Next
                </button>
              </div>
            </div>
          ) : null}
        </section>
      )}

      <footer className="muted mt-10 text-xs">
        Data derived from{" "}
        <code className="font-mono">output/videos</code> and{" "}
        <code className="font-mono">output/uploaded.json</code> by{" "}
        <code className="font-mono">scripts/pipeline_status.py</code>.
      </footer>
    </div>
  );
}
