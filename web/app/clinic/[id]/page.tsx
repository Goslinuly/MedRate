"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { api, PartnerServices } from "@/lib/api";
import { categoryLabel } from "@/lib/format";
import PriceCell from "@/components/PriceCell";
import VerifiedBadge from "@/components/VerifiedBadge";
import { FlagList } from "@/components/FlagTag";

export default function ClinicPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const [data, setData] = useState<PartnerServices | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api
      .partnerServices(id)
      .then(setData)
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [id]);

  const services = data?.services ?? [];

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
          <h1 className="mt-3 text-2xl font-bold text-slate-900">{id}</h1>
          <p className="mt-1 text-sm text-slate-500">Услуг в прайсе: {services.length}</p>

          <div className="mt-5 overflow-hidden rounded-xl bg-white shadow-sm ring-1 ring-slate-200">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-400">
                <tr>
                  <th className="px-4 py-3">Услуга</th>
                  <th className="px-4 py-3">Категория</th>
                  <th className="px-4 py-3">Цена</th>
                  <th className="px-4 py-3">Статус</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {services.map((s, i) => (
                  <tr key={i}>
                    <td className="px-4 py-3">
                      <div className="font-medium text-slate-800">
                        {s.service_name_norm ?? s.service_name_raw}
                      </div>
                      {s.service_name_norm && s.service_name_norm !== s.service_name_raw && (
                        <div className="text-xs text-slate-400">{s.service_name_raw}</div>
                      )}
                      <div className="mt-1">
                        <FlagList flags={s.flags} />
                      </div>
                    </td>
                    <td className="px-4 py-3 text-slate-600">{categoryLabel(s.category)}</td>
                    <td className="px-4 py-3">
                      <PriceCell
                        resident={s.price_resident}
                        nonresident={s.price_nonresident}
                        fallback={s.price}
                      />
                      {s.unit && <div className="mt-0.5 text-xs text-slate-400">за {s.unit}</div>}
                    </td>
                    <td className="px-4 py-3">
                      <VerifiedBadge verified={s.is_verified} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
