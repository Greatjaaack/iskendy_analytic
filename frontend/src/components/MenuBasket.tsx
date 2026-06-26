import { useState } from "react";
import { useLiveQuery } from "../hooks";
import { fetchBasket, rangeKey, type RangeSel } from "../api";
import { COLORS } from "../constants";
import { fmtInt } from "../format";

interface Props {
  range: RangeSel;
  withDelivery?: boolean;
}

type Metric = "conf" | "support";
// порядок осей фиксирован тумблером (по популярности / алфавит) и НЕ двигается при
// клике. Клик по подписи строки/столбца — подсветка: выбранное блюдо и все, что с
// ним берут в чеках, остаются яркими, остальное затемняется (focus — индекс блюда).
type Order = "freq" | "name";

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
  const [order, setOrder] = useState<Order>("freq");
  const [focus, setFocus] = useState(-1); // подсвеченное блюдо (клик по подписи), -1 = нет

  const q = useLiveQuery({
    queryKey: ["basket", rangeKey(range), "dish", withDelivery],
    queryFn: () => fetchBasket(range, "dish", withDelivery, 14),
  });

  const labels = q.data?.labels ?? [];
  const matrix = q.data?.matrix ?? [];
  const freq = q.data?.freq ?? [];
  const orders = q.data?.orders ?? 0;

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

  const short = (s: string, n = 22) => (s.length > n ? s.slice(0, n - 1) + "…" : s);

  const CELL_W = 72;
  const CELL_H = 52;
  const focusMode = focus >= 0;

  // Порядок осей (одна перестановка на обе оси — диагональ остаётся выровненной).
  // Зависит только от тумблера и НЕ двигается при клике. Элементы — исходные индексы.
  const axis = labels.map((_, i) => i);
  if (order === "name") {
    axis.sort((a, b) => labels[a].localeCompare(labels[b], "ru"));
  } // freq — бэкенд уже отдал по убыванию частоты, исходный порядок сохраняем

  // клик по подписи блюда: подсветить его и связанные; повторный клик — сброс
  const focusOn = (i: number) => setFocus((f) => (f === i ? -1 : i));

  // связано ли блюдо k с подсвеченным (focus): само блюдо или есть со-встречаемость
  // в любую сторону. Без подсветки (focus < 0) — связаны все.
  const linked = (k: number) =>
    focus < 0 || k === focus || (matrix[focus]?.[k] ?? 0) > 0 || (matrix[k]?.[focus] ?? 0) > 0;
  // ячейка (i,j) активна, если подсветки нет либо она в крестовине выбранного блюда
  const cellOn = (i: number, j: number) => focus < 0 || i === focus || j === focus;

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
            ] as [Order, string][]).map(([key, label]) => {
              const active = order === key;
              return (
                <button
                  key={key}
                  onClick={() => setOrder(key)}
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

      {focus >= 0 && (
        <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 10 }}>
          Подсветка связей «<span style={{ color: COLORS.indigoText, fontWeight: 600 }}>{labels[focus]}</span>» — что с ним берут в чеке ·{" "}
          <button
            onClick={() => setFocus(-1)}
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
          <table style={{ borderCollapse: "separate", borderSpacing: 4, fontSize: 14 }}>
            <thead>
              <tr>
                <th style={{ padding: 4 }} />
                {axis.map((oj) => {
                  const colLabel = labels[oj];
                  const isFocus = oj === focus;
                  const isLinked = linked(oj);
                  const dim = focusMode && !isLinked; // не связано с выбранным — гасим
                  return (
                    <th
                      key={oj}
                      title={`${colLabel} — подсветить связи`}
                      onClick={() => focusOn(oj)}
                      style={{
                        padding: 0, cursor: "pointer",
                        opacity: dim ? 0.16 : 1, filter: dim ? "grayscale(1)" : "none",
                        transition: "opacity .15s",
                        width: CELL_W, verticalAlign: "bottom", height: 130,
                      }}
                    >
                      {/* подпись под углом 45°: якорь левого-нижнего угла в центре
                          столбца, текст уходит вверх-вправо (overflow видим) */}
                      <div style={{ position: "relative", width: "100%", height: "100%" }}>
                        <span
                          style={{
                            position: "absolute", left: "50%", bottom: 4,
                            transform: "rotate(-45deg)", transformOrigin: "left bottom",
                            whiteSpace: "nowrap", fontSize: 12, lineHeight: 1,
                            color: isFocus ? "#fff" : focusMode && isLinked ? "var(--text)" : "var(--muted)",
                            fontWeight: isFocus || (focusMode && isLinked) ? 700 : 500,
                            background: isFocus
                              ? COLORS.primary
                              : focusMode && isLinked
                                ? `rgba(${PRIMARY_RGB}, 0.2)`
                                : "transparent",
                            borderRadius: isFocus || (focusMode && isLinked) ? 6 : 0,
                            padding: isFocus || (focusMode && isLinked) ? "3px 7px" : "3px 2px",
                          }}
                        >
                          {short(colLabel, 18)}
                        </span>
                      </div>
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              {axis.map((oi) => {
                const rowLabel = labels[oi];
                const rowFocus = oi === focus;
                const rowLinked = linked(oi);
                const rowDim = focusMode && !rowLinked;
                return (
                  <tr key={oi}>
                    <td
                      onClick={() => focusOn(oi)}
                      style={{
                        padding: "2px 12px 2px 0",
                        color: "var(--text)",
                        fontWeight: rowFocus ? 700 : focusMode && rowLinked ? 600 : 400, cursor: "pointer",
                        opacity: rowDim ? 0.16 : 1, filter: rowDim ? "grayscale(1)" : "none",
                        transition: "opacity .15s",
                        whiteSpace: "nowrap", textAlign: "right", maxWidth: 220, overflow: "hidden", textOverflow: "ellipsis",
                        fontSize: 14,
                      }}
                      title={`${rowLabel} · в ${freq[oi] ?? 0} чеках — подсветить связи`}
                    >
                      <span
                        style={{
                          background: rowFocus
                            ? COLORS.primary
                            : focusMode && rowLinked
                              ? `rgba(${PRIMARY_RGB}, 0.2)`
                              : "transparent",
                          color: rowFocus ? "#fff" : undefined,
                          borderRadius: rowFocus || (focusMode && rowLinked) ? 6 : 0,
                          padding: rowFocus || (focusMode && rowLinked) ? "3px 8px" : 0,
                        }}
                      >
                        {short(rowLabel)}
                      </span>
                    </td>
                    {axis.map((oj) => {
                      const colLabel = labels[oj];
                      const off = !cellOn(oi, oj); // вне крестовины подсвеченного блюда
                      if (oi === oj) {
                        return (
                          <td
                            key={oj}
                            style={{ width: CELL_W, height: CELL_H, textAlign: "center", background: "var(--bg)", color: "var(--muted)", borderRadius: 6, fontSize: 12, opacity: off ? 0.12 : 1, transition: "opacity .15s" }}
                            title={`${rowLabel}: в ${freq[oi] ?? 0} чеках`}
                          >
                            {fmtInt(freq[oi] ?? 0)}
                          </td>
                        );
                      }
                      const pct = cellPct(oi, oj);
                      // ниже порога видимости (0.5%) ячейка пустая — нет числа, нет заливки,
                      // нет подсветки. Важно для «доли чеков»: там значения мелкие, и иначе
                      // подсветка floor-ом заливала бы пустые ячейки (без числа).
                      const shown = pct >= 0.5;
                      const intensity = Math.min(1, maxPct ? pct / maxPct : 0);
                      const co = matrix[oi]?.[oj] ?? 0;
                      const tip =
                        metric === "conf"
                          ? `Из ${freq[oi] ?? 0} чеков с «${rowLabel}» в ${co} также «${colLabel}» (${Math.round(pct)}%)`
                          : `«${rowLabel}» + «${colLabel}»: ${co} чек. (${pct.toFixed(1)}% всех чеков)`;
                      // фон через rgba (прозрачность только у фона, не у текста);
                      // текст всегда непрозрачный: тёмный/светлый по теме на бледном фоне, белый на насыщенном
                      // в режиме подсветки видимые ячейки крестовины поднимаем по насыщенности
                      // (floor 0.45) и обводим акцентом — чтобы «что берут с блюдом» читалось явно
                      const lit = focusMode && !off && shown; // подсвеченная связь (только видимая)
                      const alpha = !shown ? 0 : lit ? Math.max(0.45, 0.12 + intensity * 0.88) : 0.12 + intensity * 0.88;
                      return (
                        <td
                          key={oj}
                          title={tip}
                          style={{
                            width: CELL_W, height: CELL_H, textAlign: "center", borderRadius: 6,
                            background: shown ? `rgba(${PRIMARY_RGB}, ${alpha})` : "var(--bg)",
                            color: alpha > 0.5 ? "#fff" : "var(--text)",
                            fontSize: 14, fontWeight: shown ? 700 : 400,
                            boxShadow: lit ? `inset 0 0 0 2px ${COLORS.primary}` : "none",
                            opacity: off ? 0.12 : 1, filter: off ? "grayscale(1)" : "none",
                            transition: "opacity .15s",
                          }}
                        >
                          {shown ? `${Math.round(pct)}%` : ""}
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
    </div>
  );
}
