"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";

type Geo = Awaited<ReturnType<typeof api.partnersGeo>>;

declare global {
  interface Window {
    L?: any;
  }
}

function loadLeaflet(): Promise<any> {
  return new Promise((resolve, reject) => {
    if (window.L) return resolve(window.L);
    if (!document.getElementById("leaflet-css")) {
      const link = document.createElement("link");
      link.id = "leaflet-css";
      link.rel = "stylesheet";
      link.href = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
      document.head.appendChild(link);
    }
    const script = document.createElement("script");
    script.src = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js";
    script.onload = () => resolve(window.L);
    script.onerror = reject;
    document.body.appendChild(script);
  });
}

export default function MapPage() {
  const mapRef = useRef<HTMLDivElement>(null);
  const [clinics, setClinics] = useState<Geo>([]);
  const [error, setError] = useState<string | null>(null);
  const [geocoding, setGeocoding] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => {
    api.partnersGeo().then(setClinics).catch((e) => setError(String(e)));
  }, []);

  useEffect(() => {
    let map: any;
    let cancelled = false;
    loadLeaflet()
      .then((L) => {
        if (cancelled || !mapRef.current) return;
        map = L.map(mapRef.current).setView([48.0, 67.0], 5); // Kazakhstan
        L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
          attribution: "© OpenStreetMap",
          maxZoom: 19,
        }).addTo(map);
        const markers: any[] = [];
        for (const c of clinics) {
          const m = L.marker([c.lat, c.lon]).addTo(map);
          m.bindPopup(
            `<b>${c.partner_name}</b><br>${c.city ?? ""}<br>${c.service_count} услуг`,
          );
          markers.push(m);
        }
        if (markers.length > 0) {
          const group = L.featureGroup(markers);
          map.fitBounds(group.getBounds().pad(0.2));
        }
      })
      .catch(() => setError("Не удалось загрузить карту (Leaflet CDN)"));
    return () => {
      cancelled = true;
      if (map) map.remove();
    };
  }, [clinics]);

  const runGeocode = async () => {
    setGeocoding(true);
    setMsg(null);
    try {
      const r = await api.geocode();
      setMsg(`Геокодирование запущено. Уже на карте: ${r.geocoded}, в очереди: ${r.remaining} (≈1 клиника/сек). Обновите страницу через минуту.`);
    } catch (e) {
      setError(String(e));
    } finally {
      setGeocoding(false);
    }
  };

  return (
    <div className="mx-auto max-w-5xl px-4 py-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Клиники на карте</h1>
          <p className="mt-1 text-sm text-slate-500">На карте: {clinics.length} клиник с координатами</p>
        </div>
        <button
          onClick={runGeocode}
          disabled={geocoding}
          className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium hover:bg-slate-100 disabled:opacity-50"
        >
          {geocoding ? "Запуск…" : "Геокодировать по адресам"}
        </button>
      </div>

      {error && <div className="mt-4 rounded-xl bg-red-50 p-4 text-red-700 ring-1 ring-red-200">{error}</div>}
      {msg && <div className="mt-4 rounded-xl bg-teal-50 p-4 text-teal-700 ring-1 ring-teal-200">{msg}</div>}

      {clinics.length === 0 && !error && (
        <div className="mt-4 rounded-xl bg-amber-50 p-4 text-sm text-amber-700 ring-1 ring-amber-200">
          Пока нет клиник с координатами. Нажмите «Геокодировать по адресам» — координаты определятся из
          адресов клиник (нужно, чтобы адрес был извлечён из прайса).
        </div>
      )}

      <div
        ref={mapRef}
        className="mt-4 h-[500px] w-full overflow-hidden rounded-xl ring-1 ring-slate-200"
        style={{ background: "#e8eef2" }}
      />
    </div>
  );
}
