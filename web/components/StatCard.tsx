export default function StatCard({
  label,
  value,
  hint,
  accent,
}: {
  label: string;
  value: string | number;
  hint?: string;
  accent?: "teal" | "amber" | "red" | "slate";
}) {
  const ring =
    accent === "teal"
      ? "ring-teal-200"
      : accent === "amber"
        ? "ring-amber-200"
        : accent === "red"
          ? "ring-red-200"
          : "ring-slate-200";
  const text =
    accent === "teal"
      ? "text-teal-700"
      : accent === "amber"
        ? "text-amber-700"
        : accent === "red"
          ? "text-red-700"
          : "text-slate-900";
  return (
    <div className={`rounded-xl bg-white p-4 shadow-sm ring-1 ${ring}`}>
      <div className="text-sm text-slate-500">{label}</div>
      <div className={`mt-1 text-3xl font-bold ${text}`}>{value}</div>
      {hint && <div className="mt-1 text-xs text-slate-400">{hint}</div>}
    </div>
  );
}
