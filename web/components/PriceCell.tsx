import { formatPrice } from "@/lib/format";

type Props = {
  resident: number | null;
  nonresident: number | null;
  fallback?: number | null;
};

/** Two clear prices: resident / non-resident — the core of Case 2. */
export default function PriceCell({ resident, nonresident, fallback }: Props) {
  const res = resident ?? fallback ?? null;
  return (
    <div className="flex flex-col gap-0.5 leading-tight">
      <div className="flex items-baseline gap-1.5">
        <span className="text-[11px] uppercase tracking-wide text-slate-400">резидент</span>
        <span className="text-base font-semibold text-slate-900">{formatPrice(res)} ₸</span>
      </div>
      <div className="flex items-baseline gap-1.5">
        <span className="text-[11px] uppercase tracking-wide text-slate-400">нерезидент</span>
        <span className="text-sm font-medium text-slate-500">
          {nonresident != null ? `${formatPrice(nonresident)} ₸` : "—"}
        </span>
      </div>
    </div>
  );
}
