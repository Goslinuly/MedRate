"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, ServiceSummary } from "@/lib/api";
import { formatPrice } from "@/lib/format";

type Picked = { id: number; name: string };
type Result = Awaited<ReturnType<typeof api.basketOptimize>>;

export default function BasketPage() {
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<ServiceSummary[]>([]);
  const [picked, setPicked] = useState<Picked[]>([]);
  const [resident, setResident] = useState(true);
  const [result, setResult] = useState<Result | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (query.trim().length < 2) {
      setHits([]);
      return;
    }
    const h = setTimeout(() => {
      api.services(query.trim()).then(setHits).catch(() => setHits([]));
    }, 250);
    return () => clearTimeout(h);
  }, [query]);

  const add = (s: ServiceSummary) => {
    if (!picked.some((p) => p.id === s.ref_service_id)) {
      setPicked((prev) => [...prev, { id: s.ref_service_id, name: s.service_name_norm }]);
    }
    setQuery("");
    setHits([]);
  };
  const remove = (id: number) => setPicked((prev) => prev.filter((p) => p.id !== id));

  const optimize = async () => {
    if (picked.length === 0) return;
    setLoading(true);
    setError(null);
    try {
      const r = await api.basketOptimize({ service_ids: picked.map((p) => p.id), resident });
      setResult(r);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  };

  const nameById = (id: number) => picked.find((p) => p.id === id)?.name ?? `#${id}`;

  return (
    <div className="mx-auto max-w-4xl px-4 py-8">
      <Link href="/" className="text-sm text-teal-700 hover:underline">← К поиску</Link>
      <h1 className="mt-3 text-2xl font-bold text-slate-900">Корзина обследований</h1>
      <p className="mt-1 text-sm text-slate-500">
        Соберите комплекс услуг — система найдёт самую дешёвую комбинацию и клиники с лучшим покрытием.
      </p>

      {/* Picker */}
      <div className="mt-5 rounded-xl bg-white p-4 shadow-sm ring-1 ring-slate-200">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Добавить услугу в корзину…"
          className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-teal-300"
        />
        {hits.length > 0 && (
          <div className="mt-2 max-h-56 space-y-1 overflow-auto">
            {hits.map((s) => (
              <button
                key={s.ref_service_id}
                onClick={() => add(s)}
                className="flex w-full items-center justify-between rounded-lg border border-slate-200 px-3 py-1.5 text-left text-sm hover:border-teal-300 hover:bg-teal-50/50"
              >
                <span className="text-slate-700">{s.service_name_norm}</span>
                <span className="text-xs text-slate-400">{s.partner_count} клиник</span>
              </button>
            ))}
          </div>
        )}

        {picked.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-2">
            {picked.map((p) => (
              <span key={p.id} className="flex items-center gap-1 rounded-full bg-teal-50 px-3 py-1 text-sm text-teal-700">
                {p.name}
                <button onClick={() => remove(p.id)} className="text-teal-500 hover:text-red-500">✕</button>
              </span>
            ))}
          </div>
        )}

        <div className="mt-4 flex items-center gap-3">
          <label className="flex items-center gap-2 text-sm text-slate-600">
            <input type="checkbox" checked={resident} onChange={(e) => setResident(e.target.checked)} />
            Цены для резидента
          </label>
          <button
            disabled={picked.length === 0 || loading}
            onClick={optimize}
            className="ml-auto rounded-lg bg-teal-600 px-5 py-2 text-sm font-semibold text-white hover:bg-teal-700 disabled:opacity-50"
          >
            {loading ? "Считаем…" : `Рассчитать (${picked.length})`}
          </button>
        </div>
      </div>

      {error && <div className="mt-4 rounded-xl bg-red-50 p-4 text-red-700 ring-1 ring-red-200">{error}</div>}

      {result && (
        <div className="mt-6 space-y-6">
          {/* Cheapest combination */}
          <div className="rounded-xl bg-white p-5 shadow-sm ring-1 ring-slate-200">
            <h2 className="text-lg font-semibold text-slate-800">Самая дешёвая комбинация</h2>
            <p className="text-sm text-slate-500">по каждой услуге берётся самая выгодная клиника</p>
            <table className="mt-3 w-full text-sm">
              <tbody className="divide-y divide-slate-100">
                {result.cheapest_items.map((it) => (
                  <tr key={it.ref_service_id}>
                    <td className="py-1.5 text-slate-700">{it.service_name ?? nameById(it.ref_service_id)}</td>
                    <td className="py-1.5 text-slate-500">{it.partner_name}</td>
                    <td className="py-1.5 text-right font-medium text-slate-900">{formatPrice(it.price)} ₸</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="border-t-2 border-slate-200">
                  <td className="py-2 font-semibold text-slate-800" colSpan={2}>Итого</td>
                  <td className="py-2 text-right text-lg font-bold text-teal-700">{formatPrice(result.cheapest_total)} ₸</td>
                </tr>
              </tfoot>
            </table>
            {result.missing_anywhere.length > 0 && (
              <p className="mt-2 text-xs text-amber-600">
                Нет ни в одной клинике: {result.missing_anywhere.map(nameById).join(", ")}
              </p>
            )}
          </div>

          {/* Best clinics (one-stop) */}
          <div className="rounded-xl bg-white p-5 shadow-sm ring-1 ring-slate-200">
            <h2 className="text-lg font-semibold text-slate-800">Лучшие клиники «в одном месте»</h2>
            <p className="text-sm text-slate-500">по покрытию услуг и сумме</p>
            <div className="mt-3 space-y-2">
              {result.by_clinic.slice(0, 10).map((c) => (
                <div key={c.partner_id} className="flex items-center justify-between rounded-lg border border-slate-200 px-4 py-2">
                  <div>
                    <Link href={`/clinic/${c.partner_id}`} className="font-medium text-slate-800 hover:text-teal-700">
                      {c.partner_name}
                    </Link>
                    <div className="text-xs text-slate-400">
                      покрыто {c.covered} из {c.total_requested}
                      {c.city ? ` · ${c.city}` : ""}
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="font-semibold text-slate-900">{formatPrice(c.total_price)} ₸</div>
                    {c.covered === c.total_requested && (
                      <span className="text-[11px] font-medium text-teal-600">всё в одном месте</span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
