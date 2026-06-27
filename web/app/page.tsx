"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { api, FilterOptions, ServiceSummary } from "@/lib/api";
import { categoryLabel, priceRange } from "@/lib/format";

export default function Home() {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<string>("");
  const [filters, setFilters] = useState<FilterOptions | null>(null);
  const [results, setResults] = useState<ServiceSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.filters().then(setFilters).catch(() => setFilters(null));
  }, []);

  useEffect(() => {
    const handle = setTimeout(() => {
      setLoading(true);
      setError(null);
      api
        .services(query.trim() || undefined, category || undefined)
        .then((r) => setResults(r))
        .catch((e) => setError(String(e)))
        .finally(() => setLoading(false));
    }, 250);
    return () => clearTimeout(handle);
  }, [query, category]);

  const empty = !loading && !error && results.length === 0;

  return (
    <div>
      {/* Hero */}
      <section className="bg-gradient-to-b from-teal-600 to-teal-700 px-4 py-14 text-white">
        <div className="mx-auto max-w-3xl text-center">
          <h1 className="text-3xl font-bold sm:text-4xl">
            Кто оказывает услугу и по какой цене
          </h1>
          <p className="mt-3 text-teal-50">
            Единая база прайсов клиник-партнёров. Сравните цены для резидентов и нерезидентов.
          </p>
          <div className="mt-6">
            <input
              autoFocus
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Например: приём кардиолога, УЗИ брюшной полости, ОАК…"
              className="w-full rounded-xl border-0 px-5 py-4 text-base text-slate-900 shadow-lg outline-none ring-2 ring-transparent focus:ring-teal-300"
            />
          </div>
          <CategoryChips
            categories={filters?.categories ?? []}
            value={category}
            onChange={setCategory}
          />
        </div>
      </section>

      {/* Results */}
      <section className="mx-auto max-w-5xl px-4 py-8">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-slate-800">
            {query || category ? "Результаты" : "Все услуги"}
          </h2>
          {!loading && !error && (
            <span className="text-sm text-slate-400">найдено: {results.length}</span>
          )}
        </div>

        {error && (
          <div className="rounded-xl bg-red-50 p-6 text-red-700 ring-1 ring-red-200">
            Не удалось загрузить данные: {error}. Запущен ли API на :8000?
          </div>
        )}

        {loading && <SkeletonList />}

        {empty && (
          <div className="rounded-xl bg-white p-10 text-center shadow-sm ring-1 ring-slate-200">
            <p className="text-lg font-medium text-slate-700">Ничего не найдено</p>
            <p className="mt-1 text-sm text-slate-500">
              Измените запрос или загрузите прайсы в{" "}
              <Link href="/admin/upload" className="text-teal-700 underline">
                кабинете оператора
              </Link>
              .
            </p>
          </div>
        )}

        {!loading && !error && results.length > 0 && (
          <div className="grid gap-3 sm:grid-cols-2">
            {results.map((s) => (
              <Link
                key={s.ref_service_id}
                href={`/service/${s.ref_service_id}`}
                className="group flex flex-col rounded-xl bg-white p-4 shadow-sm ring-1 ring-slate-200 transition hover:shadow-md hover:ring-teal-300"
              >
                <div className="flex items-start justify-between gap-2">
                  <span className="font-semibold text-slate-800 group-hover:text-teal-700">
                    {s.service_name_norm}
                  </span>
                  {s.category && (
                    <span className="shrink-0 rounded-md bg-slate-100 px-2 py-0.5 text-xs text-slate-500">
                      {categoryLabel(s.category)}
                    </span>
                  )}
                </div>
                <div className="mt-3 flex items-end justify-between">
                  <span className="text-sm text-slate-500">{s.partner_count} клиник</span>
                  <span className="text-sm font-medium text-slate-700">
                    {priceRange(s.price_min, s.price_max)}
                  </span>
                </div>
              </Link>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function CategoryChips({
  categories,
  value,
  onChange,
}: {
  categories: { value: string; label: string }[];
  value: string;
  onChange: (v: string) => void;
}) {
  const chips = useMemo(() => [{ value: "", label: "Все" }, ...categories], [categories]);
  if (categories.length === 0) return null;
  return (
    <div className="mt-4 flex flex-wrap justify-center gap-2">
      {chips.map((c) => (
        <button
          key={c.value || "all"}
          onClick={() => onChange(c.value)}
          className={`rounded-full px-3 py-1 text-sm font-medium transition ${
            value === c.value
              ? "bg-white text-teal-700"
              : "bg-teal-500/40 text-white hover:bg-teal-500/60"
          }`}
        >
          {c.label}
        </button>
      ))}
    </div>
  );
}

function SkeletonList() {
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} className="h-24 animate-pulse rounded-xl bg-white shadow-sm ring-1 ring-slate-200" />
      ))}
    </div>
  );
}
