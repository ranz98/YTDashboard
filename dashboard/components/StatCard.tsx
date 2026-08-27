export function StatCard({
  label,
  value,
  hint,
  tone = "default",
}: {
  label: string;
  value: string | number;
  hint?: string;
  tone?: "default" | "good" | "bad" | "busy";
}) {
  const accent =
    tone === "good"
      ? "text-emerald-600 dark:text-emerald-400"
      : tone === "bad"
        ? "text-rose-600 dark:text-rose-400"
        : tone === "busy"
          ? "text-amber-600 dark:text-amber-400"
          : "";

  return (
    <div className="panel p-4">
      <div className="muted text-xs font-medium uppercase tracking-wide">
        {label}
      </div>
      <div className={`mt-1.5 text-2xl font-semibold tabular-nums ${accent}`}>
        {value}
      </div>
      {hint ? <div className="muted mt-1 text-xs">{hint}</div> : null}
    </div>
  );
}
