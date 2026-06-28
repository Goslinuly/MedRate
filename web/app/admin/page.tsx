"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, Stats } from "@/lib/api";
import { flagLabel, isCriticalFlag } from "@/lib/format";
import StatCard from "@/components/StatCard";

type DocRow = Awaited<ReturnType<typeof api.documents>>[number];

const DOC_STATUS: Record<string, { label: string; cls: string }> = {
  done: { label: "готово", cls: "bg-teal-50 text-teal-700" },
  needs_review: { label: "на ревью", cls: "bg-amber-50 text-amber-700" },
  processing: { label: "обработка", cls: "bg-blue-50 text-blue-700" },
  error: { label: "ошибка", cls: "bg-red-50 text-red-600" },
  pending: { label: "в очереди", cls: "bg-slate-100 text-slate-500" },
};

export default function AdminDashboard() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [docs, setDocs] = useState<DocRow[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.stats().then(setStats).catch((e) => setError(String(e)));
    api.documents().then(setDocs).catch(() => setDocs([]));
  }, []);

  if (error)
    return (
      <div className="mx-auto max-w-5xl px-4 py-8">
        <div className="rounded-xl bg-red-50 p-6 text-red-700 ring-1 ring-red-200">
          Не удалось загрузить метрики: {error}. Запущен ли API на :8000?
        </div>
      </div>
    );

  if (!stats)
    return (
      <div className="mx-auto max-w-5xl px-4 py-8">
        <div className="h-40 animate-pulse rounded-xl bg-white ring-1 ring-slate-200" />
      </div>
    );

  const flagEntries = Object.entries(stats.flags);
  const maxFlag = Math.max(1, ...flagEntries.map(([, n]) => n));

  return (
    <div className="mx-auto max-w-5xl px-4 py-8">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-2xl font-bold text-slate-900">Кабинет оператора</h1>
        <div className="flex gap-2">
          <a
            href={api.reportUrl()}
            target="_blank"
            rel="noreferrer"
            className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100"
          >
            ↓ Отчёт о качестве
          </a>
          <Link
            href="/admin/upload"
            className="rounded-lg bg-teal-600 px-4 py-2 text-sm font-semibold text-white hover:bg-teal-700"
          >
            + Загрузить прайсы
          </Link>
        </div>
      </div>

      <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Позиций прайсов" value={stats.price_items} />
        <StatCard
          label="Нормализовано"
          value={`${stats.normalized_pct}%`}
          hint={`${stats.normalized} из ${stats.price_items}`}
          accent="teal"
        />
        <StatCard label="Клиник" value={stats.partners} />
        <StatCard
          label="На проверке"
          value={stats.needs_review}
          hint={`${stats.verified} проверено`}
          accent={stats.needs_review > 0 ? "amber" : "teal"}
        />
      </div>

      {/* Normalization progress */}
      <div className="mt-6 rounded-xl bg-white p-5 shadow-sm ring-1 ring-slate-200">
        <div className="mb-2 flex items-center justify-between text-sm">
          <span className="font-medium text-slate-700">Автонормализация</span>
          <span className="text-slate-500">
            {stats.normalized_pct}% {stats.normalized_pct >= 70 ? "✓ цель MVP (70%)" : "(цель — 70%)"}
          </span>
        </div>
        <div className="h-3 overflow-hidden rounded-full bg-slate-100">
          <div
            className={`h-full rounded-full ${stats.normalized_pct >= 70 ? "bg-teal-500" : "bg-amber-500"}`}
            style={{ width: `${Math.min(100, stats.normalized_pct)}%` }}
          />
        </div>
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        {/* Action queues */}
        <div className="rounded-xl bg-white p-5 shadow-sm ring-1 ring-slate-200">
          <h2 className="mb-3 text-lg font-semibold text-slate-800">Очереди оператора</h2>
          <div className="space-y-2">
            <QueueRow
              href="/admin/verify"
              label="Верификация позиций"
              count={stats.needs_review}
              tone="amber"
            />
            <QueueRow
              href="/admin/unmatched"
              label="Сопоставление со справочником"
              count={stats.unmatched}
              tone="slate"
            />
          </div>
        </div>

        {/* Flags histogram */}
        <div className="rounded-xl bg-white p-5 shadow-sm ring-1 ring-slate-200">
          <h2 className="mb-3 text-lg font-semibold text-slate-800">Проблемные флаги</h2>
          {flagEntries.length === 0 ? (
            <p className="text-sm text-slate-400">Флагов нет.</p>
          ) : (
            <div className="space-y-2">
              {flagEntries.map(([flag, n]) => (
                <div key={flag} className="flex items-center gap-3 text-sm">
                  <span className="w-40 shrink-0 text-slate-600">{flagLabel(flag)}</span>
                  <div className="h-2.5 flex-1 overflow-hidden rounded-full bg-slate-100">
                    <div
                      className={`h-full ${isCriticalFlag(flag) ? "bg-red-400" : "bg-amber-400"}`}
                      style={{ width: `${(n / maxFlag) * 100}%` }}
                    />
                  </div>
                  <span className="w-8 text-right tabular-nums text-slate-500">{n}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Price documents */}
      <div className="mt-6 rounded-xl bg-white p-5 shadow-sm ring-1 ring-slate-200">
        <h2 className="mb-3 text-lg font-semibold text-slate-800">
          Прайс-документы <span className="text-sm font-normal text-slate-400">({docs.length})</span>
        </h2>
        {docs.length === 0 ? (
          <p className="text-sm text-slate-400">Документов нет — загрузите архив.</p>
        ) : (
          <table className="w-full text-sm">
            <thead className="text-left text-xs uppercase tracking-wide text-slate-400">
              <tr>
                <th className="py-1">Файл</th>
                <th className="py-1">Формат</th>
                <th className="py-1">Партнёр</th>
                <th className="py-1">Чанков</th>
                <th className="py-1">Статус</th>
                <th className="py-1">Лог</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {docs.map((d) => {
                const s = DOC_STATUS[d.parse_status ?? ""] ?? { label: d.parse_status ?? "—", cls: "bg-slate-100 text-slate-500" };
                return (
                  <tr key={d.doc_id}>
                    <td className="py-1.5 text-slate-700">{d.file_name}</td>
                    <td className="py-1.5 text-slate-500">{d.file_format}</td>
                    <td className="py-1.5 text-slate-500">{d.partner_id}</td>
                    <td className="py-1.5 text-slate-500">{d.chunks ?? "—"}</td>
                    <td className="py-1.5">
                      <span className={`rounded px-1.5 py-0.5 text-xs ${s.cls}`}>{s.label}</span>
                    </td>
                    <td className="py-1.5 text-slate-400">{d.parse_log}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {/* Ingest log */}
      <div className="mt-6 rounded-xl bg-white p-5 shadow-sm ring-1 ring-slate-200">
        <h2 className="mb-3 text-lg font-semibold text-slate-800">Журнал обработки</h2>
        {stats.ingest_log.length === 0 ? (
          <p className="text-sm text-slate-400">Журнал пуст.</p>
        ) : (
          <table className="w-full text-sm">
            <thead className="text-left text-xs uppercase tracking-wide text-slate-400">
              <tr>
                <th className="py-1">Файл</th>
                <th className="py-1">Этап</th>
                <th className="py-1">Статус</th>
                <th className="py-1">Детали</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {stats.ingest_log.map((r, i) => (
                <tr key={i}>
                  <td className="py-1.5 text-slate-700">{r.source_file}</td>
                  <td className="py-1.5 text-slate-500">{r.stage}</td>
                  <td className="py-1.5">
                    <span
                      className={`rounded px-1.5 py-0.5 text-xs ${
                        r.status === "error"
                          ? "bg-red-50 text-red-600"
                          : r.status === "ok"
                            ? "bg-teal-50 text-teal-700"
                            : "bg-slate-100 text-slate-500"
                      }`}
                    >
                      {r.status}
                    </span>
                  </td>
                  <td className="py-1.5 text-slate-400">{r.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function QueueRow({
  href,
  label,
  count,
  tone,
}: {
  href: string;
  label: string;
  count: number;
  tone: "amber" | "slate";
}) {
  return (
    <Link
      href={href}
      className="flex items-center justify-between rounded-lg border border-slate-200 px-4 py-3 transition hover:border-teal-300 hover:bg-teal-50/40"
    >
      <span className="font-medium text-slate-700">{label}</span>
      <span
        className={`rounded-full px-2.5 py-0.5 text-sm font-semibold ${
          count > 0
            ? tone === "amber"
              ? "bg-amber-100 text-amber-700"
              : "bg-slate-200 text-slate-700"
            : "bg-teal-100 text-teal-700"
        }`}
      >
        {count}
      </span>
    </Link>
  );
}
