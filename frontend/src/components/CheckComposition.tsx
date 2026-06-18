import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from "recharts";
import { fetchCheckComposition, rangeKey, type RangeSel } from "../api";
import { CHART_HEIGHT, REFETCH_INTERVAL_MS, COLORS } from "../constants";

interface Props {
  range: RangeSel;
}

const PALETTE = [
  COLORS.primary, COLORS.good, COLORS.warn, COLORS.accent, COLORS.bad,
  COLORS.indigoText, "#8b5cf6", "#ec4899", "#14b8a6", "#f97316",
];

/** Состав чека (#5): средняя доля категорий в чеке. Тумблеры: по кол-ву / по выручке;
 *  за период / по часам. Стек 100%. Данные — `/api/dishes/check-composition`. */
export function CheckComposition({ range }: Props) {
  const [by, setBy] = useState<"qty" | "rev">("qty");
  const [mode, setMode] = useState<"total" | "hour">("total");

  const q = useQuery({
    queryKey: ["check-composition", rangeKey(range)],
    queryFn: () => fetchCheckComposition(range),
    refetchInterval: REFETCH_INTERVAL_MS,
  });

  const cats = q.data?.categories ?? [];
  const color = (c: string) => PALETTE[(cats.indexOf(c) + PALETTE.length) % PALETTE.length];
  const rowOf = (bucket: { by: Record<string, { qty: number; rev: number }> }) => {
    const r: Record<string, number | string> = {};
    cats.forEach((c) => (r[c] = bucket.by[c] ? bucket.by[c][by] : 0));
    return r;
  };
  const data =
    mode === "total"
      ? q.data
        ? [{ label: "За период", ...rowOf(q.data.total) }]
        : []
      : (q.data?.hourly ?? []).map((h) => ({ label: h.label, ...rowOf(h) }));

  return (
    <div style={{ background: "var(--card)", borderRadius: 12, padding: "20px 24px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8, marginBottom: 16 }}>
        <div style={{ color: "var(--text)", fontWeight: 600 }}>Состав чека (доля категорий)</div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <div style={{ display: "flex", background: "var(--bg)", borderRadius: 8, padding: 3, gap: 2 }}>
            <button onClick={() => setBy("qty")} style={mini(by === "qty")}>по кол-ву</button>
            <button onClick={() => setBy("rev")} style={mini(by === "rev")}>по выручке</button>
          </div>
          <div style={{ display: "flex", background: "var(--bg)", borderRadius: 8, padding: 3, gap: 2 }}>
            <button onClick={() => setMode("total")} style={mini(mode === "total")}>За период</button>
            <button onClick={() => setMode("hour")} style={mini(mode === "hour")}>По часам</button>
          </div>
        </div>
      </div>

      <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
        <BarChart data={data} margin={{ left: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--grid)" />
          <XAxis dataKey="label" tick={{ fill: "var(--muted)", fontSize: 12 }} />
          <YAxis unit="%" domain={[0, 100]} tick={{ fill: "var(--muted)", fontSize: 12 }} />
          <Tooltip
            contentStyle={{ background: "var(--bg)", border: "1px solid var(--grid)", borderRadius: 8 }}
            labelStyle={{ color: "var(--text)" }}
            formatter={(v, n) => [`${v}%`, n]}
          />
          <Legend wrapperStyle={{ fontSize: 12, color: "var(--muted)" }} />
          {cats.map((c) => (
            <Bar key={c} dataKey={c} stackId="comp" fill={color(c)} />
          ))}
        </BarChart>
      </ResponsiveContainer>

      <div style={{ color: "var(--muted)", fontSize: 12, marginTop: 8 }}>
        Чеков в периоде: {q.data?.total.checks ?? 0}. Доля = средняя по чекам (
        {by === "qty" ? "по количеству позиций" : "по сумме"}).
      </div>
    </div>
  );
}

const mini = (active: boolean): React.CSSProperties => ({
  padding: "5px 12px", borderRadius: 6, border: "none", cursor: "pointer",
  fontSize: 12, fontWeight: 600,
  background: active ? COLORS.primary : "transparent",
  color: active ? "var(--text)" : "var(--muted)",
});
