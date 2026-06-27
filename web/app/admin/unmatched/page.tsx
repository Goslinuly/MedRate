"use client";

import { useEffect, useState } from "react";
import { api, UnmatchedItem } from "@/lib/api";

export default function UnmatchedPage() {
  const [items, setItems] = useState<UnmatchedItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<number | null>(null);

  const load = () => {
    setLoading(true);
    api
      .unmatched()
      .then(setItems)
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const matchTo = async (item: UnmatchedItem, refId: number, name: string) => {
    setBusy(item.id);
    try {
      await api.match({
        ref_service_id: refId,
        service_name_norm: name,
        queue_id: item.id,
        clinic_id: item.clinic_id ?? undefined,
        service_name_raw: item.service_name_raw,
      });
      setItems((prev) => prev.filter((i) => i.id !== item.id));
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="mx-auto max-w-4xl px-4 py-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Сопоставление со справочником</h1>
          <p className="mt-1 text-sm text-slate-500">
            Позиции без привязки к справочнику. Осталось: {items.length}
          </p>
        </div>
        <button onClick={load} className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-100">
          Обновить
        </button>
      </div>

      {error && (
        <div className="mt-4 rounded-xl bg-red-50 p-4 text-red-700 ring-1 ring-red-200">{error}</div>
      )}
      {loading && <div className="mt-6 h-32 animate-pulse rounded-xl bg-white ring-1 ring-slate-200" />}

      {!loading && items.length === 0 && (
        <div className="mt-6 rounded-xl bg-white p-10 text-center shadow-sm ring-1 ring-slate-200">
          <p className="text-lg font-medium text-teal-700">✓ Всё сопоставлено</p>
          <p className="mt-1 text-sm text-slate-500">Очередь несопоставленных позиций пуста.</p>
        </div>
      )}

      <div className="mt-6 space-y-4">
        {items.map((item) => (
          <div key={item.id} className="rounded-xl bg-white p-5 shadow-sm ring-1 ring-slate-200">
            <div className="text-xs uppercase tracking-wide text-slate-400">как в прайсе</div>
            <div className="font-semibold text-slate-800">{item.service_name_raw}</div>
            <div className="mt-1 text-sm text-slate-500">
              {item.clinic_id} · {item.source_file}
            </div>

            <div className="mt-3 text-sm font-medium text-slate-600">Кандидаты из справочника:</div>
            {item.candidates.length === 0 ? (
              <p className="mt-2 text-sm text-slate-400">
                Кандидатов нет — найдите услугу вручную в справочнике.
              </p>
            ) : (
              <div className="mt-2 flex flex-wrap gap-2">
                {item.candidates.map((c) => (
                  <button
                    key={c.id}
                    disabled={busy === item.id}
                    onClick={() => matchTo(item, c.id, c.name)}
                    className="rounded-lg border border-teal-200 bg-teal-50 px-3 py-1.5 text-sm font-medium text-teal-700 transition hover:bg-teal-100 disabled:opacity-50"
                  >
                    {c.name}
                    {c.specialty ? <span className="ml-1 text-xs text-teal-500">· {c.specialty}</span> : null}
                  </button>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
