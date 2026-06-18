// Общие форматтеры чисел (ru-RU). Вынесены сюда, чтобы не дублировать `fmt`
// в каждом компоненте.

/** Целое число с разделителями разрядов (без дробной части): «12 345». */
export const fmtInt = (n: number): string =>
  new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(n);

/** Число с двумя знаками после запятой; `null`/`undefined` → «—» (для цен/с-с). */
export const fmtNum = (n: number | null | undefined): string =>
  n == null ? "—" : new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(n);
