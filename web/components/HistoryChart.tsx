"use client";

import { HistoryPoint } from "@/lib/api";
import { formatPrice } from "@/lib/format";

const COLORS = ["#0d9488", "#2563eb", "#db2777", "#d97706", "#7c3aed", "#059669"];

/** Lightweight multi-line SVG chart: one line per clinic across years. */
export default function HistoryChart({ points }: { points: HistoryPoint[] }) {
  const valid = points.filter((p) => p.source_year != null && p.price != null);
  if (valid.length < 2) return null;

  const years = Array.from(new Set(valid.map((p) => p.source_year!))).sort((a, b) => a - b);
  if (years.length < 2) return null;

  const byClinic = new Map<string, HistoryPoint[]>();
  for (const p of valid) {
    const list = byClinic.get(p.partner_name) ?? [];
    list.push(p);
    byClinic.set(p.partner_name, list);
  }

  const W = 640;
  const H = 240;
  const pad = { l: 64, r: 16, t: 16, b: 32 };
  const prices = valid.map((p) => p.price!);
  const minP = Math.min(...prices);
  const maxP = Math.max(...prices);
  const span = maxP - minP || 1;

  const x = (year: number) =>
    pad.l + ((year - years[0]) / (years[years.length - 1] - years[0] || 1)) * (W - pad.l - pad.r);
  const y = (price: number) => pad.t + (1 - (price - minP) / span) * (H - pad.t - pad.b);

  const clinics = Array.from(byClinic.entries());

  return (
    <div className="overflow-x-auto">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full min-w-[480px]">
        {[0, 0.5, 1].map((t) => {
          const py = pad.t + t * (H - pad.t - pad.b);
          const val = maxP - t * span;
          return (
            <g key={t}>
              <line x1={pad.l} y1={py} x2={W - pad.r} y2={py} stroke="#e2e8f0" />
              <text x={pad.l - 8} y={py + 4} textAnchor="end" className="fill-slate-400 text-[10px]">
                {formatPrice(val)}
              </text>
            </g>
          );
        })}
        {years.map((yr) => (
          <text key={yr} x={x(yr)} y={H - 10} textAnchor="middle" className="fill-slate-500 text-[11px]">
            {yr}
          </text>
        ))}
        {clinics.map(([name, list], i) => {
          const color = COLORS[i % COLORS.length];
          const sorted = [...list].sort((a, b) => a.source_year! - b.source_year!);
          const d = sorted
            .map((p, idx) => `${idx === 0 ? "M" : "L"} ${x(p.source_year!)} ${y(p.price!)}`)
            .join(" ");
          return (
            <g key={name}>
              <path d={d} fill="none" stroke={color} strokeWidth={2.5} />
              {sorted.map((p) => (
                <circle key={p.source_year} cx={x(p.source_year!)} cy={y(p.price!)} r={3.5} fill={color} />
              ))}
            </g>
          );
        })}
      </svg>
      <div className="mt-2 flex flex-wrap gap-3">
        {clinics.map(([name], i) => (
          <span key={name} className="flex items-center gap-1.5 text-xs text-slate-600">
            <span className="h-2.5 w-2.5 rounded-full" style={{ background: COLORS[i % COLORS.length] }} />
            {name}
          </span>
        ))}
      </div>
    </div>
  );
}
