import { useQuery } from "@tanstack/react-query";
import { fetchBasket, rangeKey, type RangeSel } from "../api";
import { REFETCH_INTERVAL_MS, COLORS } from "../constants";
import { fmtInt } from "../format";

interface Props {
  range: RangeSel;
  withDelivery?: boolean;
}

/** Матрица сочетаемости (market basket, #14): какие блюда чаще берут вместе в одном чеке.
 *  Тепловая матрица топ-блюд (ячейка = доля чеков, где встречаются оба) + рейтинг
 *  пар. Источник — `/api/dishes/basket` (OLAP по OrderNum), всегда по блюдам. */
export function MenuBasket({ range, withDelivery = true }: Props) {
  const q = useQuery({
    queryKey: ["basket", rangeKey(range), "dish", withDelivery],
    queryFn: () => fetchBasket(range, "dish", withDelivery),
    refetchInterval: REFETCH_INTERVAL_MS,
  });

  const labels = q.data?.labels ?? [];
  const matrix = q.data?.matrix ?? [];
  const orders = q.data?.orders ?? 0;
  const pairs = q.data?.pairs ?? [];

  // нормировка цвета ячейки: по максимальной парной встречаемости (вне диагонали)
  let maxPair = 0;
  matrix.forEach((row, i) => row.forEach((v, j) => { if (i !== j) maxPair = Math.max(maxPair, v); }));

  const short = (s: string, n = 14) => (s.length > n ? s.slice(0, n - 1) + "…" : s);

  return (
    <div style={{ background: COLORS.card, borderRadius: 12, padding: "20px 24px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8, marginBottom: 12 }}>
        <div>
          <div style={{ color: "var(--text)", fontWeight: 600 }}>Сочетаемость в чеке</div>
          <div style={{ color: "var(--muted)", fontSize: 12, marginTop: 2 }}>
            Какие блюда чаще берут вместе · чеков: {fmtInt(orders)}
          </div>
        </div>
      </div>

      {q.isLoading && <div style={{ color: "var(--muted)", textAlign: "center", padding: 24 }}>Загрузка…</div>}
      {!q.isLoading && labels.length === 0 && (
        <div style={{ color: "var(--muted)", textAlign: "center", padding: 24 }}>Нет данных</div>
      )}

      {/* тепловая матрица: строки — позиции, столбцы — те же (по индексу), легенда снизу */}
      {labels.length > 0 && (
        <div style={{ overflowX: "auto" }}>
          <table style={{ borderCollapse: "collapse", fontSize: 12 }}>
            <thead>
              <tr>
                <th style={{ padding: 4 }} />
                {labels.map((colLabel, j) => (
                  <th key={j} title={colLabel} style={{ padding: "4px 2px", color: "var(--muted)", fontWeight: 500, minWidth: 42, textAlign: "center", fontSize: 11, whiteSpace: "nowrap" }}>
                    {short(colLabel, 7)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {labels.map((rowLabel, i) => (
                <tr key={rowLabel}>
                  <td style={{ padding: "2px 8px", color: "var(--text)", whiteSpace: "nowrap" }} title={rowLabel}>
                    {short(rowLabel)}
                  </td>
                  {labels.map((colLabel, j) => {
                    const v = matrix[i]?.[j] ?? 0;
                    const sharePct = orders ? Math.round((v / orders) * 100) : 0;
                    if (i === j) {
                      return (
                        <td key={j} style={{ minWidth: 42, height: 28, textAlign: "center", background: "var(--bg)", color: "var(--muted)", borderRadius: 4 }}
                          title={`${rowLabel}: встречается в ${v} чеках`}>
                          ·
                        </td>
                      );
                    }
                    const intensity = maxPair ? v / maxPair : 0;
                    return (
                      <td
                        key={j}
                        title={`${rowLabel} + ${colLabel}: ${v} чек. (${sharePct}% чеков)`}
                        style={{
                          minWidth: 42, height: 28, textAlign: "center", borderRadius: 4,
                          background: COLORS.primary, opacity: 0.12 + intensity * 0.88,
                          color: intensity > 0.4 ? "#fff" : "var(--muted)", fontSize: 11,
                        }}
                      >
                        {sharePct > 0 ? `${sharePct}%` : ""}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>

          {/* шкала: что значит насыщенность ячейки */}
          <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 10, fontSize: 11, color: "var(--muted)", flexWrap: "wrap" }}>
            <span>реже</span>
            {[0.15, 0.35, 0.55, 0.75, 0.95].map((o) => (
              <span key={o} style={{ width: 18, height: 12, borderRadius: 3, background: COLORS.primary, opacity: o }} />
            ))}
            <span>чаще · ячейка = доля чеков, где брали обе позиции</span>
          </div>
        </div>
      )}

      {/* рейтинг пар — самый читаемый разрез «что с чем» */}
      {pairs.length > 0 && (
        <div style={{ marginTop: 16 }}>
          <div style={{ color: "var(--muted)", fontSize: 12, marginBottom: 8 }}>Топ пар (доля чеков с обеими / «к A берут B»)</div>
          {pairs.slice(0, 8).map((p) => (
            <div key={`${p.a}/${p.b}`} style={{ display: "flex", alignItems: "center", gap: 8, padding: "5px 0", borderTop: "1px solid var(--grid)" }}>
              <div style={{ flex: 1, color: "var(--text)", fontSize: 13, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {p.a} <span style={{ color: "var(--muted)" }}>+</span> {p.b}
              </div>
              <div style={{ flex: "0 0 70px", textAlign: "right", color: COLORS.indigoText, fontSize: 12, fontWeight: 600 }}>
                {p.support}% чеков
              </div>
              <div style={{ flex: "0 0 90px", textAlign: "right", color: "var(--muted)", fontSize: 12 }}>
                к «{short(p.a, 8)}» {p.confidence}%
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
