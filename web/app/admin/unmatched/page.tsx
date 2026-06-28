"use client";

import { useEffect, useState } from "react";
import { api, UnmatchedItem } from "@/lib/api";
import { categoryLabel, CATEGORY_LABELS } from "@/lib/format";

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
          <UnmatchedCard key={item.id} item={item} busy={busy === item.id} onMatch={matchTo} />
        ))}
      </div>
    </div>
  );
}

function UnmatchedCard({
  item,
  busy,
  onMatch,
}: {
  item: UnmatchedItem;
  busy: boolean;
  onMatch: (item: UnmatchedItem, refId: number, name: string) => void;
}) {
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<{ id: number; name: string; specialty: string | null }[]>([]);
  const [searching, setSearching] = useState(false);
  const [creating, setCreating] = useState(false);
  const [newCat, setNewCat] = useState("other");

  useEffect(() => {
    if (query.trim().length < 2) {
      setHits([]);
      return;
    }
    const h = setTimeout(() => {
      setSearching(true);
      api
        .referenceSearch(query.trim())
        .then(setHits)
        .catch(() => setHits([]))
        .finally(() => setSearching(false));
    }, 250);
    return () => clearTimeout(h);
  }, [query]);

  const createAndMatch = async () => {
    setCreating(true);
    try {
      const created = await api.referenceCreate({ name: item.service_name_raw, category: newCat });
      await onMatch(item, created.ref_service_id, created.service_name_norm);
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="rounded-xl bg-white p-5 shadow-sm ring-1 ring-slate-200">
      <div className="text-xs uppercase tracking-wide text-slate-400">как в прайсе</div>
      <div className="font-semibold text-slate-800">{item.service_name_raw}</div>
      <div className="mt-1 text-sm text-slate-500">
        {item.clinic_id} · {item.source_file}
      </div>

      {/* Suggested candidates */}
      {item.candidates.length > 0 && (
        <>
          <div className="mt-3 text-sm font-medium text-slate-600">Предложенные кандидаты:</div>
          <div className="mt-2 flex flex-wrap gap-2">
            {item.candidates.map((c) => (
              <button
                key={c.id}
                disabled={busy}
                onClick={() => onMatch(item, c.id, c.name)}
                className="rounded-lg border border-teal-200 bg-teal-50 px-3 py-1.5 text-sm font-medium text-teal-700 transition hover:bg-teal-100 disabled:opacity-50"
              >
                {c.name}
                {c.specialty ? <span className="ml-1 text-xs text-teal-500">· {c.specialty}</span> : null}
              </button>
            ))}
          </div>
        </>
      )}

      {/* Search whole catalogue */}
      <div className="mt-4">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Найти услугу в справочнике…"
          className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-teal-300"
        />
        {searching && <div className="mt-1 text-xs text-slate-400">поиск…</div>}
        {hits.length > 0 && (
          <div className="mt-2 max-h-48 space-y-1 overflow-auto">
            {hits.map((h) => (
              <button
                key={h.id}
                disabled={busy}
                onClick={() => onMatch(item, h.id, h.name)}
                className="flex w-full items-center justify-between rounded-lg border border-slate-200 px-3 py-1.5 text-left text-sm hover:border-teal-300 hover:bg-teal-50/50 disabled:opacity-50"
              >
                <span className="text-slate-700">{h.name}</span>
                {h.specialty && <span className="text-xs text-slate-400">{h.specialty}</span>}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Create new catalogue entry */}
      <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-slate-100 pt-3">
        <span className="text-sm text-slate-500">Нет подходящей? Создать новую:</span>
        <select
          value={newCat}
          onChange={(e) => setNewCat(e.target.value)}
          className="rounded-lg border border-slate-300 px-2 py-1 text-sm"
        >
          {Object.entries(CATEGORY_LABELS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
        <button
          disabled={busy || creating}
          onClick={createAndMatch}
          className="rounded-lg bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50"
        >
          + Создать «{item.service_name_raw.slice(0, 24)}{item.service_name_raw.length > 24 ? "…" : ""}»
        </button>
        <span className="text-xs text-slate-400">категория: {categoryLabel(newCat)}</span>
      </div>
    </div>
  );
}
