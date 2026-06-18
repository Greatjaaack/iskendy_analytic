import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchHourlyBreakdown, rangeKey, type RangeSel, type DishGroupBy } from "../api";
import { REFETCH_INTERVAL_MS, COLORS } from "../constants";
import { fmtInt } from "../format";

interface Props {
  range: RangeSel;
}

/** Что и когда берут: разбивка продаж по блюдам/категориям за каждый часовой интервал (#3).
 *  Данные — из OLAP-движка iiko (`/api/dishes/hourly-breakdown`). */
export function HourlyBreakdown({ range }: Props) {
  const [group, setGroup] = useState<DishGroupBy>("category");
  const [hour, setHour] = useState<number | null>(null);

  const q = useQuery({
    queryKey: ["hourly-breakdown", rangeKey(range), group],
    queryFn: () => fetchHourlyBreakdown(range, group),
    refetchInterval: REFETCH_INTERVAL_MS,
  });

  const data = useMemo(() => q.data?.data ?? [], [q.data]);
  // выбранный час (или первый доступный)
  const current = useMemo(
    () => data.find((h) => h.hour === hour) ?? data[0],
    [data, hour],
  );

  return (
    <div style={{ background: COLORS.card, borderRadius: 12, padding: "20px 24px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8, marginBottom: 12 }}>
        <div style={{ color: "var(--text)", fontWeight: 600 }}>Что берут по часам</div>
        <div style={{ display: "flex", background: "var(--bg)", borderRadius: 8, padding: 3, gap: 2 }}>
          {(["category", "dish"] as DishGroupBy[]).map((g) => (
            <button
              key={g}
              onClick={() => setGroup(g)}
              style={{
                padding: "5px 12px", borderRadius: 6, border: "none", cursor: "pointer",
                fontSize: 12, fontWeight: 600,
                background: group === g ? COLORS.primary : "transparent",
                color: group === g ? "var(--text)" : "var(--muted)",
              }}
            >
              {g === "category" ? "Категории" : "Блюда"}
            </button>
          ))}
        </div>
      </div>

      {/* выбор часового интервала */}
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 14 }}>
        {data.map((h) => {
          const active = current?.hour === h.hour;
          return (
            <button
              key={h.hour}
              onClick={() => setHour(h.hour)}
              style={{
                padding: "4px 10px", borderRadius: 6, fontSize: 12, fontWeight: 600, cursor: "pointer",
                border: `1px solid ${active ? COLORS.primary : "var(--grid)"}`,
                background: active ? COLORS.primary : "transparent",
                color: active ? "var(--text)" : "var(--muted)",
              }}
            >
              {h.label}
            </button>
          );
        })}
      </div>

      {current && (
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr style={{ color: "var(--muted)", textAlign: "left" }}>
              <th style={td}>{group === "category" ? "Категория" : "Блюдо"} · {current.label}</th>
              <th style={{ ...td, textAlign: "right" }}>Кол-во</th>
              <th style={{ ...td, textAlign: "right" }}>Выручка, ₽</th>
              <th style={{ ...td, textAlign: "right" }}>Доля</th>
            </tr>
          </thead>
          <tbody>
            {current.items.map((it) => (
              <tr key={it.name} style={{ borderTop: "1px solid var(--grid)" }}>
                <td style={td}>{it.name}</td>
                <td style={{ ...td, textAlign: "right" }}>{it.quantity}</td>
                <td style={{ ...td, textAlign: "right" }}>{fmtInt(it.revenue)}</td>
                <td style={{ ...td, textAlign: "right", color: COLORS.indigoText }}>
                  {current.revenue ? Math.round((it.revenue / current.revenue) * 100) : 0}%
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {q.isLoading && <div style={{ color: "var(--muted)", textAlign: "center", padding: 24 }}>Загрузка…</div>}
      {!q.isLoading && data.length === 0 && (
        <div style={{ color: "var(--muted)", textAlign: "center", padding: 24 }}>Нет данных</div>
      )}
    </div>
  );
}

const td: React.CSSProperties = { padding: "7px 10px" };
