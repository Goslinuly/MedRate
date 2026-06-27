"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, PartnerSummary } from "@/lib/api";

export default function PartnersPage() {
  const [partners, setPartners] = useState<PartnerSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .partners()
      .then(setPartners)
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="mx-auto max-w-5xl px-4 py-8">
      <h1 className="text-2xl font-bold text-slate-900">Клиники-партнёры</h1>
      <p className="mt-1 text-sm text-slate-500">{partners.length} клиник в базе</p>

      {error && (
        <div className="mt-4 rounded-xl bg-red-50 p-6 text-red-700 ring-1 ring-red-200">{error}</div>
      )}
      {loading && <div className="mt-6 h-40 animate-pulse rounded-xl bg-white ring-1 ring-slate-200" />}

      {!loading && !error && (
        <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {partners.map((p) => (
            <Link
              key={p.partner_id}
              href={`/clinic/${p.partner_id}`}
              className="rounded-xl bg-white p-4 shadow-sm ring-1 ring-slate-200 transition hover:shadow-md hover:ring-teal-300"
            >
              <div className="font-semibold text-slate-800">{p.partner_name}</div>
              <div className="text-sm text-slate-400">{p.city ?? "—"}</div>
              <div className="mt-2 text-sm text-teal-700">{p.service_count} услуг</div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
