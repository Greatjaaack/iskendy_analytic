import { useCallback, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Bar, BarChart, Cell, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { fetchHourlyBreakdown, rangeKey, type RangeSel, type DishGroupBy } from "../api";
import { REFETCH_INTERVAL_MS, COLORS } from "../constants";
import { fmtInt, fillHourGaps, hourLabel } from "../format";

interface Props {
  range: RangeSel;
  withDelivery?: boolean;
}

type SortKey = "name" | "quantity" | "revenue" | "share";
type Metric = "revenue" | "quantity";

// палитра для сегментов-категорий в столбчатой диаграмме (стек)
const PALETTE = [
  COLORS.primary, COLORS.good, COLORS.warn, COLORS.accent, COLORS.bad,
  COLORS.indigoText, "#8b5cf6", "#ec4899", "#14b8a6", "#f97316",
];

/** Продажи по часам: разбивка продаж по блюдам/категориям за каждый часовой интервал (#3).
 *  Столбчатая диаграмма по часам (выручка/кол-во, клик по столбцу — выбор часа) + таблица
 *  по выбранному часу. Данные — из OLAP-движка iiko (`/api/dishes/hourly-breakdown`). */
export function HourlyBreakdown({ range, withDelivery = true }: Props) {
  const [group, setGroup] = useState<DishGroupBy>("category");
  const [hour, setHour] = useState<number | null>(null);
  const [metric, setMetric] = useState<Metric>("revenue");
  const [chartMode, setChartMode] = useState<"abs" | "share">("abs");
  const [sortKey, setSortKey] = useState<SortKey>("revenue");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  const q = useQuery({
    queryKey: ["hourly-breakdown", rangeKey(range), group, withDelivery],
    queryFn: () => fetchHourlyBreakdown(range, group, withDelivery),
    refetchInterval: REFETCH_INTERVAL_MS,
  });
  // для диаграммы всегда нужен разрез по КАТЕГОРИЯМ (стек читаем); когда таблица тоже
  // в режиме «Категории» — это тот же queryKey, и React Query не делает второй запрос.
  const catQ = useQuery({
    queryKey: ["hourly-breakdown", rangeKey(range), "category", withDelivery],
    queryFn: () => fetchHourlyBreakdown(range, "category", withDelivery),
    refetchInterval: REFETCH_INTERVAL_MS,
  });

  const data = useMemo(() => q.data?.data ?? [], [q.data]);
  // выбранный час (или первый доступный)
  const current = useMemo(
    () => data.find((h) => h.hour === hour) ?? data[0],
    [data, hour],
  );

  const val = useCallback(
    (it: { revenue: number; quantity: number }) => (metric === "revenue" ? it.revenue : it.quantity),
    [metric],
  );
  // список категорий для стека, отсортирован по суммарной метрике (стабильный порядок/цвет)
  const cats = useMemo(() => {
    const totals: Record<string, number> = {};
    (catQ.data?.data ?? []).forEach((h) => h.items.forEach((it) => (totals[it.name] = (totals[it.name] ?? 0) + val(it))));
    return Object.keys(totals).sort((a, b) => totals[b] - totals[a]);
  }, [catQ.data, val]);
  const color = (c: string) => PALETTE[(cats.indexOf(c) + PALETTE.length) % PALETTE.length];
  // строки диаграммы: на каждый час — значение каждой категории по выбранной метрике (стек)
  const chartData = useMemo(
    () =>
      // пропуски часов заполняем пустыми барами → ось X совпадает с другими почасовыми графиками
      fillHourGaps(catQ.data?.data ?? [], (h) => ({
        hour: h, label: hourLabel(h), revenue: 0, quantity: 0, items: [],
      })).map((h) => {
        // __total — итог часа по выбранной метрике; нужен тултипу в режиме «Доли»
        // (recharts stackOffset="expand" отдаёт в формат-функцию сырое значение, не долю)
        const row: Record<string, number | string> = { label: h.label, hour: h.hour, __total: 0 };
        let total = 0;
        h.items.forEach((it) => {
          const v = val(it);
          row[it.name] = v;
          total += v;
        });
        row.__total = total;
        return row;
      }),
    [catQ.data, val],
  );

  const onSort = (k: SortKey) => {
    if (k === sortKey) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setSortKey(k);
      setSortDir(k === "name" ? "asc" : "desc");
    }
  };
  const arrow = (k: SortKey) => (sortKey === k ? (sortDir === "asc" ? " ↑" : " ↓") : "");

  // доля = значение по выбранной метрике / итог часа по ней; сортировка по «доле»
  // эквивалентна сортировке по самой метрике (в пределах часа доля ей монотонна)
  const items = useMemo(() => {
    const list = current?.items ?? [];
    const dir = sortDir === "asc" ? 1 : -1;
    const byMetric = (k: SortKey) => (k === "share" ? metric : k);
    return [...list].sort((a, b) =>
      sortKey === "name"
        ? String(a.name).localeCompare(String(b.name), "ru") * dir
        : (Number(a[byMetric(sortKey)]) - Number(b[byMetric(sortKey)])) * dir,
    );
  }, [current, sortKey, sortDir, metric]);

  // база и лидер часа по выбранной метрике — для процента и длины инлайн-бара доли
  const hourTotal = current ? (metric === "revenue" ? current.revenue : current.quantity) : 0;
  const maxVal = items.length
    ? Math.max(...items.map((it) => (metric === "revenue" ? it.revenue : it.quantity)))
    : 0;

  return (
    <div style={{ background: COLORS.card, borderRadius: 12, padding: "20px 24px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8, marginBottom: 12 }}>
        <div style={{ color: "var(--text)", fontWeight: 600 }}>Продажи по часам</div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <div style={{ display: "flex", background: "var(--bg)", borderRadius: 8, padding: 3, gap: 2 }}>
            <button onClick={() => setMetric("revenue")} style={mini(metric === "revenue")}>Выручка</button>
            <button onClick={() => setMetric("quantity")} style={mini(metric === "quantity")}>Кол-во</button>
          </div>
          <div style={{ display: "flex", background: "var(--bg)", borderRadius: 8, padding: 3, gap: 2 }}>
            <button onClick={() => setChartMode("abs")} style={mini(chartMode === "abs")}>Объём</button>
            <button onClick={() => setChartMode("share")} style={mini(chartMode === "share")}>Доли</button>
          </div>
          <div style={{ display: "flex", background: "var(--bg)", borderRadius: 8, padding: 3, gap: 2 }}>
            {(["category", "dish"] as DishGroupBy[]).map((g) => (
              <button key={g} onClick={() => setGroup(g)} style={mini(group === g)}>
                {g === "category" ? "Категории" : "Блюда"}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* столбчатая диаграмма по часам, стек по категориям; клик по столбцу — выбор часа.
          Выбранный час подсвечен (остальные приглушены). */}
      {chartData.length > 0 && (
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={chartData} margin={{ left: 8 }} stackOffset={chartMode === "share" ? "expand" : "none"}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--grid)" />
            <XAxis dataKey="label" tick={{ fill: "var(--muted)", fontSize: 11 }} interval={0} />
            <YAxis
              tickFormatter={chartMode === "share" ? (v) => `${Math.round(Number(v) * 100)}%` : fmtInt}
              tick={{ fill: "var(--muted)", fontSize: 11 }}
              width={48}
              domain={chartMode === "share" ? [0, 1] : undefined}
            />
            <Tooltip
              cursor={{ fill: "var(--grid)", opacity: 0.3 }}
              contentStyle={{ background: "var(--bg)", border: "1px solid var(--grid)", borderRadius: 8 }}
              labelStyle={{ color: "var(--text)" }}
              formatter={(v, n, item) => {
                const num = Number(v);
                const base = metric === "revenue" ? `${fmtInt(num)} ₽` : `${fmtInt(num)} шт`;
                if (chartMode === "share") {
                  const t = Number((item?.payload as { __total?: number })?.__total ?? 0);
                  return [`${t ? Math.round((num / t) * 100) : 0}% · ${base}`, n];
                }
                return [base, n];
              }}
            />
            <Legend wrapperStyle={{ fontSize: 11, color: "var(--muted)" }} />
            {cats.map((c) => (
              <Bar
                key={c}
                dataKey={c}
                stackId="h"
                fill={color(c)}
                cursor="pointer"
                onClick={(d) => setHour((d as unknown as { hour: number }).hour)}
              >
                {chartData.map((row) => (
                  <Cell key={row.hour} fillOpacity={current?.hour === row.hour ? 1 : 0.45} />
                ))}
              </Bar>
            ))}
          </BarChart>
        </ResponsiveContainer>
      )}

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
              <th style={thSort} onClick={() => onSort("name")}>
                {group === "category" ? "Категория" : "Блюдо"} · {current.label}{arrow("name")}
              </th>
              <th style={{ ...thSort, textAlign: "right" }} onClick={() => onSort("quantity")}>Кол-во{arrow("quantity")}</th>
              <th style={{ ...thSort, textAlign: "right" }} onClick={() => onSort("revenue")}>Выручка, ₽{arrow("revenue")}</th>
              <th style={{ ...thSort, textAlign: "right" }} onClick={() => onSort("share")}>
                Доля {metric === "revenue" ? "(₽)" : "(шт)"}{arrow("share")}
              </th>
            </tr>
          </thead>
          <tbody>
            {items.map((it) => {
              const v = metric === "revenue" ? it.revenue : it.quantity;
              const share = hourTotal ? v / hourTotal : 0;
              const rel = maxVal ? v / maxVal : 0; // длина бара: относительно лидера часа
              return (
                <tr key={it.name} style={{ borderTop: "1px solid var(--grid)" }}>
                  <td style={td}>{it.name}</td>
                  <td style={{ ...td, textAlign: "right" }}>{it.quantity}</td>
                  <td style={{ ...td, textAlign: "right" }}>{fmtInt(it.revenue)}</td>
                  <td style={td}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, justifyContent: "flex-end" }}>
                      <div style={{ flex: 1, maxWidth: 90, height: 6, background: "var(--grid)", borderRadius: 3, overflow: "hidden" }}>
                        <div style={{ width: `${rel * 100}%`, height: "100%", background: COLORS.indigoText, borderRadius: 3 }} />
                      </div>
                      <span style={{ color: COLORS.indigoText, minWidth: 34, textAlign: "right" }}>
                        {Math.round(share * 100)}%
                      </span>
                    </div>
                  </td>
                </tr>
              );
            })}
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
const thSort: React.CSSProperties = { padding: "7px 10px", cursor: "pointer", userSelect: "none", whiteSpace: "nowrap" };
const mini = (active: boolean): React.CSSProperties => ({
  padding: "5px 12px", borderRadius: 6, border: "none", cursor: "pointer",
  fontSize: 12, fontWeight: 600,
  background: active ? COLORS.primary : "transparent",
  color: active ? "var(--text)" : "var(--muted)",
});
