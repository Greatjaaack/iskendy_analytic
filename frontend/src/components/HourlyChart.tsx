import { useQuery } from "@tanstack/react-query";
import {
  BarChart, Bar,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from "recharts";
import { fetchHourly, rangeKey, type RangeSel, type HourRow } from "../api";
import { CHART_HEIGHT, REFETCH_INTERVAL_MS, COLORS } from "../constants";
import { fmtInt, fillHourGaps, hourLabel } from "../format";

interface Props {
  range: RangeSel;
  withDelivery?: boolean;
}

/** Выручка по часам: выручка + число чеков по каждому часу. */
export function HourlyChart({ range, withDelivery = true }: Props) {
  const sumQ = useQuery({
    queryKey: ["hourly", rangeKey(range), withDelivery],
    queryFn: () => fetchHourly(range, withDelivery),
    refetchInterval: REFETCH_INTERVAL_MS,
  });

  // заполняем пропуски часов → равномерная ось X (часы без продаж не схлопываются)
  const sumRaw = fillHourGaps(sumQ.data?.data ?? [], (h): HourRow => ({
    hour: h, label: hourLabel(h), revenue: 0, checks: 0, avg_check: 0,
  }));
  const chartData = sumRaw.map((h) => ({ label: h.label, Выручка: h.revenue, Чеки: h.checks }));

  return (
    <div style={{ background: "var(--card)", borderRadius: 12, padding: "20px 24px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8, marginBottom: 16 }}>
        <div style={{ color: "var(--text)", fontWeight: 600 }}>Выручка по часам</div>
      </div>

      <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
        <BarChart data={chartData}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--grid)" />
          <XAxis dataKey="label" tick={{ fill: "var(--muted)", fontSize: 12 }} />
          <YAxis yAxisId="money" tickFormatter={fmtInt} tick={{ fill: "var(--muted)", fontSize: 12 }} />
          <YAxis yAxisId="checks" orientation="right" allowDecimals={false} tick={{ fill: "var(--muted)", fontSize: 12 }} />
          <Tooltip
            contentStyle={{ background: "var(--bg)", border: "1px solid var(--grid)", borderRadius: 8 }}
            labelStyle={{ color: "var(--text)" }}
            formatter={(val, name) => (name === "Чеки" ? `${val} шт` : `${fmtInt(Number(val))} ₽`)}
          />
          <Legend wrapperStyle={{ fontSize: 12, color: "var(--muted)" }} />
          <Bar yAxisId="money" dataKey="Выручка" fill={COLORS.primary} radius={[4, 4, 0, 0]} />
          <Bar yAxisId="checks" dataKey="Чеки" fill={COLORS.good} radius={[4, 4, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
      {!sumQ.isLoading && chartData.length === 0 && (
        <div style={{ color: "var(--muted)", textAlign: "center", padding: 24 }}>Нет данных</div>
      )}
    </div>
  );
}
