import type { RunEvent } from "@/lib/types";
import { formatDateTime, formatDuration, relativeTime } from "@/lib/format";

const RUN_STYLES: Record<RunEvent["status"], string> = {
  running:
    "bg-amber-100 text-amber-800 ring-amber-200 dark:bg-amber-500/15 dark:text-amber-300 dark:ring-amber-400/25",
  success:
    "bg-emerald-100 text-emerald-800 ring-emerald-200 dark:bg-emerald-500/15 dark:text-emerald-300 dark:ring-emerald-400/25",
  failed:
    "bg-rose-100 text-rose-800 ring-rose-200 dark:bg-rose-500/15 dark:text-rose-300 dark:ring-rose-400/25",
  skipped:
    "bg-slate-100 text-slate-600 ring-slate-200 dark:bg-slate-500/15 dark:text-slate-400 dark:ring-slate-400/25",
};

const RUN_LABELS: Record<RunEvent["status"], string> = {
  running: "Running",
  success: "Succeeded",
  failed: "Failed",
  skipped: "Nothing to do",
};

const STAGE_LABELS: Record<RunEvent["stage"], string> = {
  download: "Download",
  edit: "Edit",
  upload: "Upload",
  pipeline: "Full pipeline",
};

export function RunBadge({ status }: { status: RunEvent["status"] }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset ${RUN_STYLES[status]}`}
    >
      <span
        aria-hidden
        className={`h-1.5 w-1.5 rounded-full bg-current opacity-70 ${
          status === "running" ? "animate-pulse" : ""
        }`}
      />
      {RUN_LABELS[status]}
    </span>
  );
}

/** Live state of the three scheduled jobs, newest run of each. */
export function StageStrip({ runs }: { runs: RunEvent[] }) {
  const stages: RunEvent["stage"][] = ["download", "edit", "upload"];
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
      {stages.map((stage) => {
        const latest = runs.find((r) => r.stage === stage);
        return (
          <div key={stage} className="panel p-4">
            <div className="flex items-center justify-between gap-2">
              <span className="text-sm font-medium">{STAGE_LABELS[stage]}</span>
              {latest ? (
                <RunBadge status={latest.status} />
              ) : (
                <span className="muted text-xs">No runs yet</span>
              )}
            </div>
            {latest ? (
              <div className="muted mt-2 space-y-0.5 text-xs">
                <div>
                  {latest.status === "running" ? "Started" : "Finished"}{" "}
                  {formatDateTime(latest.finishedAt ?? latest.startedAt)}
                </div>
                {latest.durationMs !== null ? (
                  <div>Took {formatDuration(latest.durationMs)}</div>
                ) : null}
                {latest.message ? (
                  <div
                    className={
                      latest.status === "failed"
                        ? "text-rose-600 dark:text-rose-400"
                        : ""
                    }
                  >
                    {latest.message}
                  </div>
                ) : null}
              </div>
            ) : (
              <div className="muted mt-2 text-xs">
                Waiting for the scheduled task to report in.
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

export function ActivityTable({
  runs,
  now,
}: {
  runs: RunEvent[];
  now: number;
}) {
  if (runs.length === 0) {
    return (
      <div className="panel px-6 py-16 text-center">
        <div className="text-base font-medium">No activity recorded yet</div>
        <p className="muted mx-auto mt-2 max-w-lg text-sm">
          The scheduled tasks report here each time they start and finish. If
          this stays empty, check that <code className="font-mono text-xs">DASHBOARD_URL</code>{" "}
          and <code className="font-mono text-xs">DASHBOARD_TOKEN</code> are set on
          the VPS, and that a KV store is configured on the Vercel project.
        </p>
      </div>
    );
  }

  return (
    <div className="panel overflow-hidden">
      <div className="table-scroll">
        <table className="w-full min-w-[860px] text-left text-sm">
          <thead
            className="muted border-b text-xs uppercase tracking-wide"
            style={{ borderColor: "var(--border)" }}
          >
            <tr>
              <th className="px-4 py-3 font-medium">Stage</th>
              <th className="px-4 py-3 font-medium">Result</th>
              <th className="px-4 py-3 font-medium">Started</th>
              <th className="px-4 py-3 font-medium">Duration</th>
              <th className="px-4 py-3 font-medium">Host</th>
              <th className="px-4 py-3 font-medium">Detail</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((run) => (
              <tr
                key={run.id}
                className="border-b last:border-0"
                style={{ borderColor: "var(--border)" }}
              >
                <td className="px-4 py-3 font-medium whitespace-nowrap">
                  {STAGE_LABELS[run.stage]}
                </td>
                <td className="px-4 py-3">
                  <RunBadge status={run.status} />
                </td>
                <td className="muted px-4 py-3 whitespace-nowrap">
                  {relativeTime(run.startedAt, now)}
                </td>
                <td className="muted px-4 py-3 whitespace-nowrap tabular-nums">
                  {formatDuration(run.durationMs)}
                </td>
                <td className="muted px-4 py-3 font-mono text-xs whitespace-nowrap">
                  {run.host ?? "—"}
                </td>
                <td className="px-4 py-3">
                  <div className="max-w-[420px] text-xs">
                    {run.videoTitle ? (
                      <div className="font-medium">{run.videoTitle}</div>
                    ) : null}
                    {run.message ? (
                      <div
                        className={
                          run.status === "failed"
                            ? "text-rose-600 dark:text-rose-400"
                            : "muted"
                        }
                      >
                        {run.message}
                      </div>
                    ) : null}
                    {run.exitCode !== null && run.exitCode !== 0 ? (
                      <div className="muted font-mono">exit {run.exitCode}</div>
                    ) : null}
                    {!run.message && !run.videoTitle && run.exitCode === 0 ? (
                      <span className="muted">—</span>
                    ) : null}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
