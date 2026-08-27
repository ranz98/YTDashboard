import type { Status } from "@/lib/types";

const STYLES: Record<Status, string> = {
  scheduled:
    "bg-slate-100 text-slate-700 ring-slate-200 dark:bg-slate-500/15 dark:text-slate-300 dark:ring-slate-400/25",
  processing:
    "bg-amber-100 text-amber-800 ring-amber-200 dark:bg-amber-500/15 dark:text-amber-300 dark:ring-amber-400/25",
  downloaded:
    "bg-sky-100 text-sky-800 ring-sky-200 dark:bg-sky-500/15 dark:text-sky-300 dark:ring-sky-400/25",
  edited:
    "bg-violet-100 text-violet-800 ring-violet-200 dark:bg-violet-500/15 dark:text-violet-300 dark:ring-violet-400/25",
  uploaded:
    "bg-indigo-100 text-indigo-800 ring-indigo-200 dark:bg-indigo-500/15 dark:text-indigo-300 dark:ring-indigo-400/25",
  successful:
    "bg-emerald-100 text-emerald-800 ring-emerald-200 dark:bg-emerald-500/15 dark:text-emerald-300 dark:ring-emerald-400/25",
  failed:
    "bg-rose-100 text-rose-800 ring-rose-200 dark:bg-rose-500/15 dark:text-rose-300 dark:ring-rose-400/25",
  cancelled:
    "bg-zinc-100 text-zinc-600 ring-zinc-200 dark:bg-zinc-500/15 dark:text-zinc-400 dark:ring-zinc-400/25",
};

const LABELS: Record<Status, string> = {
  scheduled: "Scheduled",
  processing: "Processing",
  downloaded: "Downloaded",
  edited: "Edited",
  uploaded: "Uploaded",
  successful: "Successful",
  failed: "Failed",
  cancelled: "Cancelled",
};

export function StatusBadge({ status }: { status: Status }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset ${STYLES[status]}`}
    >
      <span
        aria-hidden
        className={`h-1.5 w-1.5 rounded-full ${
          status === "processing" ? "animate-pulse" : ""
        } bg-current opacity-70`}
      />
      {LABELS[status]}
    </span>
  );
}

export function StageDot({ done, label }: { done: boolean; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap text-xs">
      <span
        aria-hidden
        className={`h-2 w-2 rounded-full ${
          done
            ? "bg-emerald-500"
            : "bg-slate-300 dark:bg-slate-600"
        }`}
      />
      <span className={done ? "" : "muted"}>{label}</span>
    </span>
  );
}

export { LABELS as STATUS_LABELS };
