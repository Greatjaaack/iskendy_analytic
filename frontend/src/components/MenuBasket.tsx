import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchBasket, rangeKey, type RangeSel } from "../api";
import { REFETCH_INTERVAL_MS, COLORS } from "../constants";
import { fmtInt } from "../format";

interface Props {
  range: RangeSel;
  withDelivery?: boolean;
}

type Metric = "conf" | "support";
// порядок осей: по популярности (freq, дефолт от бэкенда) / алфавит / по связи с
// выбранным блюдом (pivot — клик по подписи строки/столбца)
type Sort = { mode: "freq" | "name"; pivot: number };

// RGB основного акцента (COLORS.primary = #6366f1) — для rgba-фона ячеек
const PRIMARY_RGB = "99, 102, 241";

/** Матрица сочетаемости (market basket, #14): какие блюда чаще берут вместе в одном чеке.
 *  Две метрики на тумблере:
 *   - «Доп. продажа» (по строке): из чеков с блюдом строки — доля, где также взяли блюдо
 *     столбца (условная вероятность, asymmetric). Это рабочая метрика апсейла: «к A берут B».
 *   - «Доля чеков»: пара встречается в N% всех чеков (support, симметрично).
 *  Источник — `/api/dishes/basket` (OLAP по OrderNum), всегда по блюдам. */
export function MenuBasket({ range, withDelivery = true }: Props) {
  const [metric, setMetric] = useState<Metric>("conf");
  const [sort, setSort] = useState<Sort>({ mode: "freq", pivot: -1 });

  const q = useQuery({
    queryKey: ["basket", rangeKey(range), "dish", withDelivery],
    queryFn: () => fetchBasket(range, "dish", withDelivery, 14),
    refetchInterval: REFETCH_INTERVAL_MS,
  });

  const labels = q.data?.labels ?? [];
  const matrix = q.data?.matrix ?? [];
  const freq = q.data?.freq ?? [];
  const orders = q.data?.orders ?? 0;
  const pairs = q.data?.pairs ?? [];

  // значение ячейки (i — строка, j — столбец) в выбранной метрике, %.
  const cellPct = (i: number, j: number): number => {
    const v = matrix[i]?.[j] ?? 0;
    if (metric === "conf") {
      const base = freq[i] ?? 0; // чеки с блюдом строки
      return base ? (v / base) * 100 : 0;
    }
    return orders ? (v / orders) * 100 : 0;
  };

  // нормировка насыщенности — по 90-му перцентилю ненулевых ячеек, а не по max:
  // редкие блюда дают conf 100% от 1–2 чеков и иначе «съели» бы всю палитру,
  // оставив реальные связи (9–30%) бледными. Клиппинг по p90 → контраст у массы.
  const nz: number[] = [];
  for (let i = 0; i < labels.length; i++)
    for (let j = 0; j < labels.length; j++)
      if (i !== j) {
        const v = cellPct(i, j);
        if (v > 0) nz.push(v);
      }
  nz.sort((a, b) => a - b);
  const maxPct = nz.length ? nz[Math.floor(nz.length * 0.9)] || nz[nz.length - 1] : 0;

  const short = (s: string, n = 20) => (s.length > n ? s.slice(0, n - 1) + "…" : s);

  const CELL_W = 54;
  const CELL_H = 38;

  // Порядок осей (одна перестановка на обе оси — диагональ остаётся выровненной).
  // pivot >= 0: сортировка по силе связи с выбранным блюдом (само блюдо первым),
  // иначе по выбранному режиму. Элементы массива — исходные индексы в matrix/freq.
  const order = labels.map((_, i) => i);
  if (sort.pivot >= 0) {
    order.sort((a, b) => {
      if (a === sort.pivot) return -1;
      if (b === sort.pivot) return 1;
      return (matrix[sort.pivot]?.[b] ?? 0) - (matrix[sort.pivot]?.[a] ?? 0);
    });
  } else if (sort.mode === "name") {
    order.sort((a, b) => labels[a].localeCompare(labels[b], "ru"));
  } // freq — бэкенд уже отдал по убыванию частоты, исходный порядок сохраняем

  // клик по подписи блюда: сортировать по связи с ним; повторный клик — сброс
  const pivotOn = (i: number) =>
    setSort((s) => ({ mode: s.mode, pivot: s.pivot === i ? -1 : i }));

  return (
    <div style={{ background: COLORS.card, borderRadius: 12, padding: "20px 24px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8, marginBottom: 14 }}>
        <div>
          <div style={{ color: "var(--text)", fontWeight: 600, fontSize: 15 }}>Сочетаемость в чеке</div>
          <div style={{ color: "var(--muted)", fontSize: 12, marginTop: 2 }}>
            {metric === "conf"
              ? "Из чеков с блюдом строки — доля, где также взяли блюдо столбца"
              : "Доля всех чеков, где встречаются обе позиции"}{" "}
            · чеков: {fmtInt(orders)}
          </div>
        </div>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          {/* сортировка осей */}
          <div style={{ display: "flex", gap: 4, background: "var(--bg)", borderRadius: 8, padding: 3 }}>
            {([
              ["freq", "По популярности"],
              ["name", "А–Я"],
            ] as [Sort["mode"], string][]).map(([key, label]) => {
              const active = sort.pivot < 0 && sort.mode === key;
              return (
                <button
                  key={key}
                  onClick={() => setSort({ mode: key, pivot: -1 })}
                  style={{
                    border: "none", borderRadius: 6, padding: "5px 12px", fontSize: 12, cursor: "pointer",
                    background: active ? COLORS.primary : "transparent",
                    color: active ? "#fff" : "var(--muted)",
                    fontWeight: active ? 600 : 500,
                  }}
                >
                  {label}
                </button>
              );
            })}
          </div>
          {/* метрика */}
          <div style={{ display: "flex", gap: 4, background: "var(--bg)", borderRadius: 8, padding: 3 }}>
            {([
              ["conf", "Доп. продажа"],
              ["support", "Доля чеков"],
            ] as [Metric, string][]).map(([key, label]) => (
              <button
                key={key}
                onClick={() => setMetric(key)}
                style={{
                  border: "none", borderRadius: 6, padding: "5px 12px", fontSize: 12, cursor: "pointer",
                  background: metric === key ? COLORS.primary : "transparent",
                  color: metric === key ? "#fff" : "var(--muted)",
                  fontWeight: metric === key ? 600 : 500,
                }}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {sort.pivot >= 0 && (
        <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 10 }}>
          Сортировка по связи с «<span style={{ color: COLORS.indigoText, fontWeight: 600 }}>{labels[sort.pivot]}</span>» ·{" "}
          <button
            onClick={() => setSort((s) => ({ mode: s.mode, pivot: -1 }))}
            style={{ border: "none", background: "transparent", color: COLORS.primary, cursor: "pointer", fontSize: 12, padding: 0 }}
          >
            сбросить
          </button>
        </div>
      )}

      {q.isLoading && <div style={{ color: "var(--muted)", textAlign: "center", padding: 24 }}>Загрузка…</div>}
      {!q.isLoading && labels.length === 0 && (
        <div style={{ color: "var(--muted)", textAlign: "center", padding: 24 }}>Нет данных</div>
      )}

      {/* тепловая матрица: строки — «основное» блюдо, столбцы — «добавка» */}
      {labels.length > 0 && (
        <div style={{ overflowX: "auto" }}>
          <table style={{ borderCollapse: "separate", borderSpacing: 3, fontSize: 13 }}>
            <thead>
              <tr>
                <th style={{ padding: 4 }} />
                {order.map((oj) => {
                  const colLabel = labels[oj];
                  const isPivot = oj === sort.pivot;
                  return (
                    <th
                      key={oj}
                      title={`${colLabel} — сортировать по связи с ним`}
                      onClick={() => pivotOn(oj)}
                      style={{
                        padding: "4px 2px", color: isPivot ? COLORS.indigoText : "var(--muted)",
                        fontWeight: isPivot ? 700 : 500, cursor: "pointer",
                        width: CELL_W, textAlign: "center", fontSize: 11, verticalAlign: "bottom",
                        height: 96,
                      }}
                    >
                      <div style={{ writingMode: "vertical-rl", transform: "rotate(180deg)", margin: "0 auto", whiteSpace: "nowrap", maxHeight: 90, overflow: "hidden" }}>
                        {short(colLabel, 16)}
                      </div>
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              {order.map((oi) => {
                const rowLabel = labels[oi];
                const rowPivot = oi === sort.pivot;
                return (
                  <tr key={oi}>
                    <td
                      onClick={() => pivotOn(oi)}
                      style={{
                        padding: "2px 10px 2px 0", color: rowPivot ? COLORS.indigoText : "var(--text)",
                        fontWeight: rowPivot ? 700 : 400, cursor: "pointer",
                        whiteSpace: "nowrap", textAlign: "right", maxWidth: 180, overflow: "hidden", textOverflow: "ellipsis",
                      }}
                      title={`${rowLabel} · в ${freq[oi] ?? 0} чеках — сортировать по связи с ним`}
                    >
                      {short(rowLabel)}
                    </td>
                    {order.map((oj) => {
                      const colLabel = labels[oj];
                      if (oi === oj) {
                        return (
                          <td
                            key={oj}
                            style={{ width: CELL_W, height: CELL_H, textAlign: "center", background: "var(--bg)", color: "var(--muted)", borderRadius: 6, fontSize: 11 }}
                            title={`${rowLabel}: в ${freq[oi] ?? 0} чеках`}
                          >
                            {fmtInt(freq[oi] ?? 0)}
                          </td>
                        );
                      }
                      const pct = cellPct(oi, oj);
                      const intensity = Math.min(1, maxPct ? pct / maxPct : 0);
                      const co = matrix[oi]?.[oj] ?? 0;
                      const tip =
                        metric === "conf"
                          ? `Из ${freq[oi] ?? 0} чеков с «${rowLabel}» в ${co} также «${colLabel}» (${Math.round(pct)}%)`
                          : `«${rowLabel}» + «${colLabel}»: ${co} чек. (${pct.toFixed(1)}% всех чеков)`;
                      // фон через rgba (прозрачность только у фона, не у текста);
                      // текст всегда непрозрачный: тёмный/светлый по теме на бледном фоне, белый на насыщенном
                      const alpha = pct > 0 ? 0.12 + intensity * 0.88 : 0;
                      return (
                        <td
                          key={oj}
                          title={tip}
                          style={{
                            width: CELL_W, height: CELL_H, textAlign: "center", borderRadius: 6,
                            background: pct > 0 ? `rgba(${PRIMARY_RGB}, ${alpha})` : "var(--bg)",
                            color: intensity > 0.55 ? "#fff" : "var(--text)",
                            fontSize: 12, fontWeight: pct > 0 ? 600 : 400,
                          }}
                        >
                          {pct >= 0.5 ? `${Math.round(pct)}%` : ""}
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>

          {/* шкала насыщенности */}
          <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 12, fontSize: 11, color: "var(--muted)", flexWrap: "wrap" }}>
            <span>реже</span>
            {[0.18, 0.38, 0.58, 0.78, 1].map((o) => (
              <span key={o} style={{ width: 22, height: 14, borderRadius: 3, background: `rgba(${PRIMARY_RGB}, ${o})` }} />
            ))}
            <span>чаще · диагональ (серым) = в скольких чеках есть само блюдо</span>
          </div>
        </div>
      )}

      {/* рейтинг пар — самый читаемый разрез «что с чем» */}
      {pairs.length > 0 && (
        <div style={{ marginTop: 20 }}>
          <div style={{ color: "var(--text)", fontSize: 13, fontWeight: 600, marginBottom: 4 }}>Топ пар «что с чем»</div>
          <div style={{ color: "var(--muted)", fontSize: 11, marginBottom: 8 }}>
            «доля чеков» — в скольких чеках есть обе позиции · «к A берут B» — из чеков с A доля с B
          </div>
          {pairs.slice(0, 12).map((p) => {
            const w = pairs[0]?.support ? Math.round((p.support / pairs[0].support) * 100) : 0;
            return (
              <div key={`${p.a}/${p.b}`} style={{ display: "flex", alignItems: "center", gap: 10, padding: "7px 0", borderTop: "1px solid var(--grid)" }}>
                <div style={{ flex: 1, minWidth: 0, color: "var(--text)", fontSize: 13, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {p.a} <span style={{ color: "var(--muted)" }}>+</span> {p.b}
                </div>
                <div style={{ flex: "0 0 120px", display: "flex", alignItems: "center", gap: 6 }}>
                  <div style={{ flex: 1, height: 6, background: "var(--bg)", borderRadius: 3, overflow: "hidden" }}>
                    <div style={{ width: `${w}%`, height: "100%", background: COLORS.primary, borderRadius: 3 }} />
                  </div>
                  <span style={{ flex: "0 0 56px", textAlign: "right", color: COLORS.indigoText, fontSize: 12, fontWeight: 600 }}>
                    {p.support}%
                  </span>
                </div>
                <div style={{ flex: "0 0 130px", textAlign: "right", color: "var(--muted)", fontSize: 12 }}>
                  к «{short(p.a, 12)}» {p.confidence}%
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
