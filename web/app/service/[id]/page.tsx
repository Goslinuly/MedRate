"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { api, ServicePartners, ServiceHistory } from "@/lib/api";
import { formatPrice } from "@/lib/format";
import PriceCell from "@/components/PriceCell";
import VerifiedBadge from "@/components/VerifiedBadge";
import { FlagList } from "@/components/FlagTag";
import HistoryChart from "@/components/HistoryChart";

export default function ServicePage() {
  const params = useParams<{ id: string }>();
  const id = Number(params.id);
  const [data, setData] = useState<ServicePartners | null>(null);
  const [history, setHistory] = useState<ServiceHistory | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api
      .servicePartners(id)
      .then(setData)
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
    api.serviceHistory(id).then(setHistory).catch(() => setHistory(null));
  }, [id]);

  const partners = data?.partners ?? [];
  const cheapest =
    partners.length > 0
      ? Math.min(...partners.map((p) => p.price_resident ?? p.price ?? Infinity))
      : null;

  return (
    <div className="mx-auto max-w-5xl px-4 py-8">
      <Link href="/" className="text-sm text-teal-700 hover:underline">
        ← К поиску
      </Link>

      {error && (
        <div className="mt-4 rounded-xl bg-red-50 p-6 text-red-700 ring-1 ring-red-200">{error}</div>
      )}

      {loading && <div className="mt-6 h-40 animate-pulse rounded-xl bg-white ring-1 ring-slate-200" />}

      {data && (
        <>
          <h1 className="mt-3 text-2xl font-bold text-slate-900">{data.service_name}</h1>
          <p className="mt-1 text-sm text-slate-500">
            {partners.length} клиник · отсортировано от самой выгодной цены
          </p>

          {data.market && data.market.count >= 2 && (
            <div className="mt-4 grid grid-cols-2 gap-3 rounded-xl bg-white p-4 shadow-sm ring-1 ring-slate-200 sm:grid-cols-4">
              <div>
                <div className="text-xs text-slate-400">медиана рынка</div>
                <div className="text-lg font-bold text-slate-900">{formatPrice(data.market.median)} ₸</div>
              </div>
              <div>
                <div className="text-xs text-slate-400">25–75 перцентиль</div>
                <div className="text-sm font-medium text-slate-700">
                  {formatPrice(data.market.p25)} – {formatPrice(data.market.p75)} ₸
                </div>
              </div>
              <div>
                <div className="text-xs text-slate-400">минимум</div>
                <div className="text-sm font-medium text-teal-700">{formatPrice(data.market.min)} ₸</div>
              </div>
              <div>
                <div className="text-xs text-slate-400">максимум</div>
                <div className="text-sm font-medium text-slate-700">{formatPrice(data.market.max)} ₸</div>
              </div>
            </div>
          )}

          <div className="mt-5 overflow-hidden rounded-xl bg-white shadow-sm ring-1 ring-slate-200">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-400">
                <tr>
                  <th className="px-4 py-3">Клиника</th>
                  <th className="px-4 py-3">Цена</th>
                  <th className="px-4 py-3">Как в прайсе</th>
                  <th className="px-4 py-3">Статус</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {partners.map((p) => {
                  const best = (p.price_resident ?? p.price) === cheapest;
                  return (
                    <tr
                      key={p.partner_id + p.service_name_raw}
                      className={p.is_outlier ? "bg-red-50/60" : best ? "bg-teal-50/50" : ""}
                    >
                      <td className="px-4 py-3">
                        <Link
                          href={`/clinic/${p.partner_id}`}
                          className="font-medium text-slate-800 hover:text-teal-700"
                        >
                          {p.partner_name}
                        </Link>
                        <div className="text-xs text-slate-400">{p.city ?? ""}</div>
                        {best && (
                          <span className="mt-1 inline-block rounded bg-teal-600 px-1.5 py-0.5 text-[10px] font-semibold text-white">
                            выгодно
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <PriceCell
                          resident={p.price_resident}
                          nonresident={p.price_nonresident}
                          fallback={p.price}
                        />
                        {p.unit && <div className="mt-0.5 text-xs text-slate-400">за {p.unit}</div>}
                        {p.delta_pct != null && p.delta_pct !== 0 && (
                          <div
                            className={`mt-1 inline-block rounded px-1.5 py-0.5 text-[11px] font-medium ${
                              p.delta_pct < 0
                                ? "bg-teal-50 text-teal-700"
                                : p.is_outlier
                                  ? "bg-red-100 text-red-700"
                                  : "bg-amber-50 text-amber-700"
                            }`}
                          >
                            {p.delta_pct < 0
                              ? `дешевле рынка на ${Math.abs(p.delta_pct)}%`
                              : `дороже рынка на ${p.delta_pct}%`}
                            {p.is_outlier ? " · выброс" : ""}
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-3 text-slate-600">
                        <div>{p.service_name_raw}</div>
                        <div className="mt-1">
                          <FlagList flags={p.flags} />
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <VerifiedBadge verified={p.is_verified} />
                        {p.source_year && (
                          <div className="mt-1 text-xs text-slate-400">прайс {p.source_year}</div>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {cheapest != null && Number.isFinite(cheapest) && (
            <p className="mt-3 text-sm text-slate-500">
              Минимальная цена для резидента:{" "}
              <span className="font-semibold text-teal-700">{formatPrice(cheapest)} ₸</span>
            </p>
          )}

          {history && history.points.length > 1 && (
            <div className="mt-8 rounded-xl bg-white p-5 shadow-sm ring-1 ring-slate-200">
              <h2 className="mb-3 text-lg font-semibold text-slate-800">История цен</h2>
              <HistoryChart points={history.points} />
            </div>
          )}
        </>
      )}
    </div>
  );
}
