export function formatPrice(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return Math.round(value).toLocaleString("ru-RU").replace(/,/g, " ");
}

export function priceRange(min: number | null, max: number | null): string {
  if (min == null && max == null) return "—";
  if (min != null && max != null && min !== max)
    return `${formatPrice(min)} – ${formatPrice(max)} ₸`;
  return `${formatPrice(min ?? max)} ₸`;
}

export const CATEGORY_LABELS: Record<string, string> = {
  consultation: "Приём врача",
  lab_tests: "Лаборатория",
  ultrasound: "УЗИ",
  ct_mri: "КТ / МРТ",
  xray: "Рентген",
  dentistry: "Стоматология",
  physiotherapy: "Физиотерапия",
  surgery: "Хирургия",
  procedures: "Процедуры",
  vaccination: "Вакцинация",
  inpatient: "Стационар",
  other: "Прочее",
};

export function categoryLabel(value: string | null | undefined): string {
  if (!value) return "";
  return CATEGORY_LABELS[value] ?? value;
}

export const FLAG_LABELS: Record<string, string> = {
  low_quality_scan: "плохой скан",
  ambiguous_price: "неоднозначная цена",
  name_uncertain: "название неточно",
  price_is_range: "цена-диапазон",
  currency_assumed: "валюта по умолчанию",
  multi_column_layout: "много колонок",
  non_price_row: "не цена",
  unmatched_service: "нет в справочнике",
  kzt_converted_from_usd: "конверт. из USD",
  kzt_converted_from_rub: "конверт. из RUB",
  invalid_price: "некорректная цена",
  nonresident_below_resident: "нерезидент < резидент",
  future_date: "дата в будущем",
  price_anomaly: "аномалия цены",
};

export function flagLabel(flag: string): string {
  return FLAG_LABELS[flag] ?? flag;
}

const CRITICAL = new Set([
  "invalid_price",
  "nonresident_below_resident",
  "future_date",
  "price_anomaly",
  "ambiguous_price",
]);

export function isCriticalFlag(flag: string): boolean {
  return CRITICAL.has(flag);
}
