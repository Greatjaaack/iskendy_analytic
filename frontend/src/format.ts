// Общие форматтеры чисел (ru-RU). Вынесены сюда, чтобы не дублировать `fmt`
// в каждом компоненте.

/** Целое число с разделителями разрядов (без дробной части): «12 345». */
export const fmtInt = (n: number): string =>
  new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(n);

/** Рубли целым числом: «4 400 ₽» (без сокращений «4.4к»). */
export const fmtRub = (n: number | null | undefined): string => `${fmtInt(n ?? 0)} ₽`;

/** Изменение к прошлому периоду в процентах с одним знаком; нет базы → `null`.
 *  База берётся по модулю — так дельта прибыли верна и при убытке в прошлом периоде. */
export const pctDelta = (cur: number, prev: number | null | undefined): number | null =>
  prev == null || prev === 0 ? null : Math.round(((cur - prev) / Math.abs(prev)) * 1000) / 10;

/** Часовой пояс точки. «Сегодня» считаем в нём, как бэкенд (`settings.timezone`). */
export const RESTAURANT_TZ = "Europe/Moscow";

// «sv-SE» форматирует дату ровно как ISO: «2026-09-26».
const isoDateInTz = (d: Date): string =>
  new Intl.DateTimeFormat("sv-SE", { timeZone: RESTAURANT_TZ }).format(d);

/** Сегодняшняя дата точки в ISO. Раньше страницы брали `toISOString()` — это дата по UTC,
 *  и с 00:00 до 03:00 МСК «сегодня» во фронте было ещё вчера: календарь не давал выбрать
 *  текущий день, а диапазон по умолчанию обрывался вчерашним. */
export const todayISO = (): string => isoDateInTz(new Date());

/** Дата `n` дней назад в поясе точки, ISO. */
export const daysAgoISO = (n: number): string => isoDateInTz(new Date(Date.now() - n * 86_400_000));

/** «2026-06-22» → «22.06» (день.месяц). */
export const dm = (iso: string): string => {
  const [, mm, dd] = iso.split("-");
  return `${dd}.${mm}`;
};

/** Метка часового интервала: «10:00». */
export const hourLabel = (h: number): string => `${String(h).padStart(2, "0")}:00`;

/** Заполняет пропуски часов между min и max наблюдаемыми (нулевыми строками от `makeEmpty`),
 *  чтобы почасовые графики имели непрерывную равномерную ось X (часы без продаж не схлопываются).
 *  Не расширяет диапазон за пределы данных — закрытые часы не добавляются. */
export function fillHourGaps<T extends { hour: number }>(rows: T[], makeEmpty: (hour: number) => T): T[] {
  if (rows.length === 0) return rows;
  const byHour = new Map(rows.map((r) => [r.hour, r]));
  const hours = rows.map((r) => r.hour);
  const min = Math.min(...hours);
  const max = Math.max(...hours);
  const out: T[] = [];
  for (let h = min; h <= max; h++) out.push(byHour.get(h) ?? makeEmpty(h));
  return out;
}
