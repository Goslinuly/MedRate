"use client";

import { useCallback, useRef, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";

type JobState = {
  state: string;
  files?: number;
  services?: number;
  normalized?: number;
  failed_files?: number;
  error?: string;
};

export default function UploadPage() {
  const [files, setFiles] = useState<File[]>([]);
  const [reset, setReset] = useState(true);
  const [job, setJob] = useState<JobState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const addFiles = (list: FileList | null) => {
    if (!list) return;
    setFiles((prev) => [...prev, ...Array.from(list)]);
  };

  const poll = useCallback((jobId: string) => {
    const tick = async () => {
      try {
        const status = await api.ingestStatus(jobId);
        setJob(status);
        if (status.state === "running") setTimeout(tick, 1500);
      } catch (e) {
        setError(String(e));
      }
    };
    tick();
  }, []);

  const start = async () => {
    if (files.length === 0) return;
    setError(null);
    setJob({ state: "running" });
    try {
      const { job_id } = await api.ingest(files, reset);
      poll(job_id);
    } catch (e) {
      setError(String(e));
      setJob(null);
    }
  };

  const running = job?.state === "running";

  return (
    <div className="mx-auto max-w-3xl px-4 py-8">
      <h1 className="text-2xl font-bold text-slate-900">Загрузка прайсов</h1>
      <p className="mt-1 text-sm text-slate-500">
        Загрузите ZIP-архив или отдельные файлы (PDF, DOCX, XLSX, XLS, CSV, изображения). Обработка
        идёт в фоне через Gemini.
      </p>

      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          addFiles(e.dataTransfer.files);
        }}
        onClick={() => inputRef.current?.click()}
        className={`mt-6 cursor-pointer rounded-2xl border-2 border-dashed p-10 text-center transition ${
          dragging ? "border-teal-500 bg-teal-50" : "border-slate-300 bg-white hover:border-teal-400"
        }`}
      >
        <div className="text-4xl">📥</div>
        <p className="mt-2 font-medium text-slate-700">Перетащите файлы сюда или нажмите для выбора</p>
        <p className="text-sm text-slate-400">ZIP · PDF · DOCX · XLSX · XLS · CSV · PNG · JPG</p>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept=".zip,.pdf,.docx,.xlsx,.xls,.csv,.png,.jpg,.jpeg"
          className="hidden"
          onChange={(e) => addFiles(e.target.files)}
        />
      </div>

      {files.length > 0 && (
        <div className="mt-4 rounded-xl bg-white p-4 shadow-sm ring-1 ring-slate-200">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-sm font-medium text-slate-700">Файлов выбрано: {files.length}</span>
            <button onClick={() => setFiles([])} className="text-sm text-slate-400 hover:text-red-500">
              Очистить
            </button>
          </div>
          <ul className="max-h-40 space-y-1 overflow-auto text-sm text-slate-600">
            {files.map((f, i) => (
              <li key={i} className="flex justify-between">
                <span className="truncate">{f.name}</span>
                <span className="ml-2 shrink-0 text-slate-400">{(f.size / 1024).toFixed(0)} КБ</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="mt-4 flex items-center gap-3">
        <label className="flex items-center gap-2 text-sm text-slate-600">
          <input type="checkbox" checked={reset} onChange={(e) => setReset(e.target.checked)} />
          Очистить базу перед загрузкой
        </label>
        <button
          disabled={files.length === 0 || running}
          onClick={start}
          className="ml-auto rounded-lg bg-teal-600 px-5 py-2 text-sm font-semibold text-white hover:bg-teal-700 disabled:opacity-50"
        >
          {running ? "Обработка…" : "Запустить обработку"}
        </button>
      </div>

      {error && (
        <div className="mt-4 rounded-xl bg-red-50 p-4 text-red-700 ring-1 ring-red-200">{error}</div>
      )}

      {job && (
        <div className="mt-6 rounded-xl bg-white p-5 shadow-sm ring-1 ring-slate-200">
          {job.state === "running" && (
            <div className="flex items-center gap-3 text-slate-700">
              <span className="h-4 w-4 animate-spin rounded-full border-2 border-teal-500 border-t-transparent" />
              Обработка документов… это может занять до нескольких минут.
            </div>
          )}
          {job.state === "done" && (
            <div>
              <p className="text-lg font-semibold text-teal-700">✓ Готово</p>
              <div className="mt-2 grid grid-cols-2 gap-2 text-sm text-slate-600 sm:grid-cols-4">
                <div>Файлов: <b>{job.files}</b></div>
                <div>Позиций: <b>{job.services}</b></div>
                <div>Нормализовано: <b>{job.normalized}</b></div>
                <div>Ошибок: <b>{job.failed_files}</b></div>
              </div>
              <div className="mt-3 flex gap-3 text-sm">
                <Link href="/admin" className="text-teal-700 underline">К дашборду</Link>
                <Link href="/admin/verify" className="text-teal-700 underline">К верификации</Link>
                <Link href="/" className="text-teal-700 underline">На сайт</Link>
              </div>
            </div>
          )}
          {job.state === "error" && (
            <p className="text-red-600">Ошибка обработки: {job.error}</p>
          )}
        </div>
      )}
    </div>
  );
}
