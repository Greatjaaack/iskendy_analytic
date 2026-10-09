/** ABC-анализ (Парето): класс позиции по накопленной доле ДО неё.
 *
 *  A — позиции, начинающиеся в первых 80 % суммы, B — в следующих 15 %, C — хвост.
 *  До 09.10.2026 класс считался по доле ПОСЛЕ позиции, и лидер с 85 % выручки
 *  («Балык») попадал в B, а класс A оставался пустым. */
export type AbcClass = "A" | "B" | "C";

export interface AbcRow<T> {
  item: T;
  value: number;
  /** накопленная доля с этой позицией, % (для линии Парето) */
  cum: number;
  cls: AbcClass;
}

export function abcClassify<T>(items: T[], value: (item: T) => number): AbcRow<T>[] {
  const base = items
    .map((item) => ({ item, value: value(item) }))
    .filter((d) => d.value > 0)
    .sort((a, b) => b.value - a.value);
  const total = base.reduce((s, d) => s + d.value, 0) || 1;
  let acc = 0;
  return base.map((d) => {
    const before = (acc / total) * 100;
    acc += d.value;
    const cls: AbcClass = before < 80 ? "A" : before < 95 ? "B" : "C";
    return { ...d, cum: Math.round((acc / total) * 1000) / 10, cls };
  });
}
