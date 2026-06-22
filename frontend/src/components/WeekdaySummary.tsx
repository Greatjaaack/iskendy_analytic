import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchRevenueByWeekday, rangeKey, type RangeSel } from "../api";
import { REFETCH_INTERVAL_MS, COLORS } from "../constants";
import { fmtInt } from "../format";

interface Props {
  range: RangeSel;
}

type SortKey = "days" | "revenue" | "avg_day_revenue" | "checks" | "avg_check";

/** Свод выручки по дням недели (#7): суммирует дни одного дня недели за период.
 *  Видно, какие дни недели «вытягивают» выручку. Данные — `/api/revenue/by-weekday`. */
export function WeekdaySummary({ range }: Props) {
  // null = естественный порядок Пн…Вс (как пришло с бэкенда)
  const [sortKey, setSortKey] = useState<SortKey | null>(null);
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  const q = useQuery({
    queryKey: ["revenue-by-weekday", rangeKey(range)],
    queryFn: () => fetchRevenueByWeekday(range),
    refetchInterval: REFETCH_INTERVAL_MS,
  });

  const onSort = (k: SortKey) => {
    if (k === sortKey) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setSortKey(k);
      setSortDir("desc");
    }
  };

  const rows = useMemo(() => {
    const all = q.data?.data ?? [];
    if (!sortKey) return all; // null → естественный порядок Пн…Вс с бэкенда
    const dir = sortDir === "asc" ? 1 : -1;
    return [...all].sort((a, b) => (Number(a[sortKey]) - Number(b[sortKey])) * dir);
  }, [q.data, sortKey, sortDir]);

  const arrow = (k: SortKey) => (sortKey === k ? (sortDir === "asc" ? " ↑" : " ↓") : "");

  // максимум для нормировки встроенных баров в колонке «Ср. за день»
  const maxAvg = useMemo(() => Math.max(0, ...rows.map((r) => r.avg_day_revenue)), [rows]);

  return (
    <div style={{ background: COLORS.card, borderRadius: 12, padding: "20px 24px" }}>
      <div style={{ color: "var(--text)", fontWeight: 600, marginBottom: 12 }}>
        Свод по дням недели
      </div>

      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr style={{ color: COLORS.muted, textAlign: "left" }}>
              <th style={th}>День недели</th>
              <th style={{ ...thSort, textAlign: "right" }} onClick={() => onSort("days")}>Дней{arrow("days")}</th>
              <th style={{ ...thSort, textAlign: "right" }} onClick={() => onSort("revenue")}>Выручка, ₽{arrow("revenue")}</th>
              <th style={{ ...thSort, textAlign: "right" }} onClick={() => onSort("avg_day_revenue")}>Ср. за день, ₽{arrow("avg_day_revenue")}</th>
              <th style={{ ...thSort, textAlign: "right" }} onClick={() => onSort("checks")}>Чеки{arrow("checks")}</th>
              <th style={{ ...thSort, textAlign: "right" }} onClick={() => onSort("avg_check")}>Ср. чек, ₽{arrow("avg_check")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.weekday} style={{ borderTop: `1px solid ${COLORS.grid}` }}>
                <td style={{ ...td, fontWeight: 600 }}>{r.weekday}</td>
                <td style={tdR}>{r.days}</td>
                <td style={tdR}>{fmtInt(r.revenue)}</td>
                <td style={td}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <div style={{ flex: 1, height: 8, background: COLORS.bg, borderRadius: 4, overflow: "hidden" }}>
                      <div style={{ width: `${maxAvg ? (r.avg_day_revenue / maxAvg) * 100 : 0}%`, height: "100%", background: COLORS.primary }} />
                    </div>
                    <span style={{ flex: "0 0 64px", textAlign: "right" }}>{fmtInt(r.avg_day_revenue)}</span>
                  </div>
                </td>
                <td style={tdR}>{r.checks}</td>
                <td style={tdR}>{fmtInt(r.avg_check)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {q.isLoading && <div style={{ color: COLORS.muted, textAlign: "center", padding: 24 }}>Загрузка…</div>}
        {!q.isLoading && rows.length === 0 && (
          <div style={{ color: COLORS.muted, textAlign: "center", padding: 24 }}>Нет данных</div>
        )}
      </div>
    </div>
  );
}

const td: React.CSSProperties = { padding: "8px 12px" };
const tdR: React.CSSProperties = { padding: "8px 12px", textAlign: "right" };
const th: React.CSSProperties = { padding: "8px 12px", whiteSpace: "nowrap" };
const thSort: React.CSSProperties = { ...th, cursor: "pointer", userSelect: "none" };
