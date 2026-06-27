"use client";

import { useEffect, useState } from "react";
import { api, VerificationItem } from "@/lib/api";
import { formatPrice } from "@/lib/format";
import { FlagList } from "@/components/FlagTag";

export default function VerifyPage() {
  const [items, setItems] = useState<VerificationItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<number | null>(null);

  const load = () => {
    setLoading(true);
    api
      .verification()
      .then(setItems)
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const remove = (id: number) => setItems((prev) => prev.filter((i) => i.record_id !== id));

  const act = async (
    item: VerificationItem,
    action: "approve" | "reject" | "correct",
    extra?: { price_resident?: number; price_nonresident?: number; service_name_norm?: string },
  ) => {
    setBusy(item.record_id);
    try {
      await api.verify({ record_id: item.record_id, action, ...extra });
      remove(item.record_id);
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
          <h1 className="text-2xl font-bold text-slate-900">Очередь верификации</h1>
          <p className="mt-1 text-sm text-slate-500">
            Подтвердите, исправьте или отклоните каждую позицию. Осталось: {items.length}
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
          <p className="text-lg font-medium text-teal-700">✓ Очередь пуста</p>
          <p className="mt-1 text-sm text-slate-500">Все позиции проверены.</p>
        </div>
      )}

      <div className="mt-6 space-y-4">
        {items.map((item) => (
          <VerifyCard key={item.record_id} item={item} busy={busy === item.record_id} onAct={act} />
        ))}
      </div>
    </div>
  );
}

function VerifyCard({
  item,
  busy,
  onAct,
}: {
  item: VerificationItem;
  busy: boolean;
  onAct: (
    item: VerificationItem,
    action: "approve" | "reject" | "correct",
    extra?: { price_resident?: number; price_nonresident?: number; service_name_norm?: string },
  ) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [res, setRes] = useState(item.price_resident ?? item.price ?? 0);
  const [nonres, setNonres] = useState(item.price_nonresident ?? 0);
  const [norm, setNorm] = useState(item.service_name_norm ?? "");

  return (
    <div className="rounded-xl bg-white p-5 shadow-sm ring-1 ring-slate-200">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-xs uppercase tracking-wide text-slate-400">как в прайсе</div>
          <div className="font-semibold text-slate-800">{item.service_name_raw}</div>
          <div className="mt-1 text-sm text-slate-500">
            {item.clinic_name} · {item.source_file}
            {item.source_year ? ` · ${item.source_year}` : ""}
          </div>
        </div>
        <div className="text-right text-sm">
          <div className="text-slate-400">справочник</div>
          <div className="font-medium text-slate-700">{item.service_name_norm ?? "— не сопоставлено —"}</div>
          {item.confidence != null && (
            <div className="text-xs text-slate-400">увер. {item.confidence}</div>
          )}
        </div>
      </div>

      {item.verification_note && (
        <div className="mt-3 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800 ring-1 ring-amber-200">
          {item.verification_note}
        </div>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-4">
        {!editing ? (
          <>
            <span className="text-sm text-slate-600">
              Резидент: <b className="text-slate-900">{formatPrice(item.price_resident ?? item.price)} ₸</b>
            </span>
            <span className="text-sm text-slate-600">
              Нерезидент: <b className="text-slate-900">{formatPrice(item.price_nonresident)} ₸</b>
            </span>
          </>
        ) : (
          <div className="flex flex-wrap items-end gap-3">
            <label className="text-xs text-slate-500">
              Резидент, ₸
              <input
                type="number"
                value={res}
                onChange={(e) => setRes(Number(e.target.value))}
                className="mt-1 block w-32 rounded-lg border border-slate-300 px-2 py-1 text-sm"
              />
            </label>
            <label className="text-xs text-slate-500">
              Нерезидент, ₸
              <input
                type="number"
                value={nonres}
                onChange={(e) => setNonres(Number(e.target.value))}
                className="mt-1 block w-32 rounded-lg border border-slate-300 px-2 py-1 text-sm"
              />
            </label>
            <label className="text-xs text-slate-500">
              Название (справочник)
              <input
                value={norm}
                onChange={(e) => setNorm(e.target.value)}
                className="mt-1 block w-64 rounded-lg border border-slate-300 px-2 py-1 text-sm"
              />
            </label>
          </div>
        )}
        <div className="ml-auto">
          <FlagList flags={item.flags} />
        </div>
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        {!editing ? (
          <>
            <button
              disabled={busy}
              onClick={() => onAct(item, "approve")}
              className="rounded-lg bg-teal-600 px-4 py-1.5 text-sm font-semibold text-white hover:bg-teal-700 disabled:opacity-50"
            >
              ✓ Подтвердить
            </button>
            <button
              disabled={busy}
              onClick={() => setEditing(true)}
              className="rounded-lg border border-slate-300 px-4 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-100"
            >
              Исправить
            </button>
            <button
              disabled={busy}
              onClick={() => onAct(item, "reject")}
              className="rounded-lg border border-red-200 px-4 py-1.5 text-sm font-medium text-red-600 hover:bg-red-50 disabled:opacity-50"
            >
              ✕ Отклонить
            </button>
          </>
        ) : (
          <>
            <button
              disabled={busy}
              onClick={() =>
                onAct(item, "correct", {
                  price_resident: res,
                  price_nonresident: nonres,
                  service_name_norm: norm || undefined,
                })
              }
              className="rounded-lg bg-teal-600 px-4 py-1.5 text-sm font-semibold text-white hover:bg-teal-700 disabled:opacity-50"
            >
              Сохранить и подтвердить
            </button>
            <button
              onClick={() => setEditing(false)}
              className="rounded-lg border border-slate-300 px-4 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-100"
            >
              Отмена
            </button>
          </>
        )}
      </div>
    </div>
  );
}
