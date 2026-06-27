const BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export type ServiceSummary = {
  ref_service_id: number;
  service_name_norm: string;
  category: string | null;
  partner_count: number;
  price_min: number | null;
  price_max: number | null;
};

export type PartnerPrice = {
  partner_id: string;
  partner_name: string;
  city: string | null;
  service_name_raw: string;
  price: number | null;
  price_resident: number | null;
  price_nonresident: number | null;
  price_min: number | null;
  price_max: number | null;
  currency: string | null;
  unit: string | null;
  is_verified: number;
  source_file: string | null;
  source_year: number | null;
  parsed_at: string | null;
  confidence: number | null;
  flags: string[];
};

export type ServicePartners = {
  service_id: number;
  service_name: string | null;
  partners: PartnerPrice[];
};

export type PartnerSummary = {
  partner_id: string;
  partner_name: string;
  city: string | null;
  service_count: number;
};

export type PartnerServiceItem = {
  service_name_norm: string | null;
  service_name_raw: string;
  category: string | null;
  price: number | null;
  price_resident: number | null;
  price_nonresident: number | null;
  price_min: number | null;
  price_max: number | null;
  currency: string | null;
  unit: string | null;
  is_verified: number;
  source_file: string | null;
  source_year: number | null;
  flags: string[];
};

export type PartnerServices = { partner_id: string; services: PartnerServiceItem[] };

export type FilterOptions = {
  cities: string[];
  categories: { value: string; label: string }[];
  clinics: { partner_id: string; partner_name: string }[];
};

export type HistoryPoint = {
  partner_id: string;
  partner_name: string;
  source_year: number | null;
  price: number | null;
  is_active: number;
};

export type ServiceHistory = {
  service_id: number;
  service_name: string | null;
  points: HistoryPoint[];
};

export type VerificationItem = {
  record_id: number;
  clinic_id: string | null;
  clinic_name: string | null;
  service_name_raw: string;
  service_name_norm: string | null;
  ref_service_id: number | null;
  category: string | null;
  price: number | null;
  price_resident: number | null;
  price_nonresident: number | null;
  currency: string | null;
  unit: string | null;
  confidence: number | null;
  verification_note: string | null;
  source_file: string | null;
  source_page: number | null;
  source_year: number | null;
  flags: string[];
};

export type UnmatchedItem = {
  id: number;
  service_name_raw: string;
  clinic_id: string | null;
  source_file: string | null;
  candidates: { id: number; name: string; specialty?: string }[];
};

export type Stats = {
  price_items: number;
  normalized: number;
  normalized_pct: number;
  partners: number;
  unmatched: number;
  verified: number;
  needs_review: number;
  flags: Record<string, number>;
  ingest_log: { source_file: string; stage: string; status: string; reason: string; created_at: string }[];
};

export const api = {
  services: (q?: string, category?: string) => {
    const p = new URLSearchParams();
    if (q) p.set("q", q);
    if (category) p.set("category", category);
    const qs = p.toString();
    return get<ServiceSummary[]>(`/services${qs ? `?${qs}` : ""}`);
  },
  servicePartners: (id: number, activeOnly = true) =>
    get<ServicePartners>(`/services/${id}/partners?active_only=${activeOnly}`),
  serviceHistory: (id: number) => get<ServiceHistory>(`/services/${id}/history`),
  partners: (city?: string) =>
    get<PartnerSummary[]>(`/partners${city ? `?city=${encodeURIComponent(city)}` : ""}`),
  partnerServices: (id: string) => get<PartnerServices>(`/partners/${encodeURIComponent(id)}/services`),
  filters: () => get<FilterOptions>("/filters"),
  stats: () => get<Stats>("/stats"),
  verification: (flag?: string) =>
    get<VerificationItem[]>(`/verification${flag ? `?flag=${encodeURIComponent(flag)}` : ""}`),
  verify: (body: {
    record_id: number;
    action: "approve" | "reject" | "correct";
    price_resident?: number;
    price_nonresident?: number;
    service_name_norm?: string;
    ref_service_id?: number;
    note?: string;
  }) => post<{ record_id: number; action: string; is_verified: number; is_active: number }>("/verify", body),
  unmatched: () => get<UnmatchedItem[]>("/unmatched"),
  match: (body: {
    ref_service_id: number;
    service_name_norm: string;
    record_id?: number;
    queue_id?: number;
    clinic_id?: string;
    service_name_raw?: string;
  }) => post<{ ref_service_id: number; matched: boolean; affected: number }>("/match", body),
  ingest: async (files: File[], reset: boolean) => {
    const form = new FormData();
    files.forEach((f) => form.append("files", f));
    form.append("reset", String(reset));
    const res = await fetch(`${BASE}/ingest`, { method: "POST", body: form });
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    return res.json() as Promise<{ job_id: string; files_received: number }>;
  },
  ingestStatus: (jobId: string) =>
    get<{
      job_id: string;
      state: string;
      files?: number;
      services?: number;
      normalized?: number;
      failed_files?: number;
      error?: string;
    }>(`/ingest/status/${jobId}`),
};

export { BASE };
