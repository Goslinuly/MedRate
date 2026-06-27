import { flagLabel, isCriticalFlag } from "@/lib/format";

export default function FlagTag({ flag }: { flag: string }) {
  const critical = isCriticalFlag(flag);
  return (
    <span
      className={`inline-flex items-center rounded-md px-1.5 py-0.5 text-xs font-medium ${
        critical
          ? "bg-red-50 text-red-700 ring-1 ring-red-200"
          : "bg-amber-50 text-amber-700 ring-1 ring-amber-200"
      }`}
    >
      {flagLabel(flag)}
    </span>
  );
}

export function FlagList({ flags }: { flags: string[] }) {
  if (!flags?.length) return null;
  return (
    <div className="flex flex-wrap gap-1">
      {flags.map((f) => (
        <FlagTag key={f} flag={f} />
      ))}
    </div>
  );
}
