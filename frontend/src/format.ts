// Общие форматтеры чисел (ru-RU). Вынесены сюда, чтобы не дублировать `fmt`
// в каждом компоненте.

/** Целое число с разделителями разрядов (без дробной части): «12 345». */
export const fmtInt = (n: number): string =>
  new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(n);

/** Число с двумя знаками после запятой; `null`/`undefined` → «—» (для цен/с-с). */
export const fmtNum = (n: number | null | undefined): string =>
  n == null ? "—" : new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(n);

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
