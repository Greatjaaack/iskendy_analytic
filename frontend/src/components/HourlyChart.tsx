import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AreaChart, Area, LineChart, Line, BarChart, Bar,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from "recharts";
import { fetchHourly, rangeKey, type RangeSel } from "../api";
import { CHART_HEIGHT, REFETCH_INTERVAL_MS, CHART_TYPES, COLORS, type ChartKind } from "../constants";
import { fmtInt } from "../format";

interface Props {
  range: RangeSel;
}

/** Продажи по часам (интервалы 11-12 …). Тип графика переключается (#4),
 *  выручка — на левой оси, чеки — на правой. */
export function HourlyChart({ range }: Props) {
  const [type, setType] = useState<ChartKind>("bar");
  const q = useQuery({
    queryKey: ["hourly", rangeKey(range)],
    queryFn: () => fetchHourly(range),
    refetchInterval: REFETCH_INTERVAL_MS,
  });

  const chartData = (q.data?.data ?? []).map((h) => ({
    label: h.label, Выручка: h.revenue, Чеки: h.checks,
  }));

  const grid = <CartesianGrid strokeDasharray="3 3" stroke="var(--grid)" />;
  const xaxis = <XAxis dataKey="label" tick={{ fill: "var(--muted)", fontSize: 12 }} />;
  const yaxisL = <YAxis yAxisId="money" tickFormatter={fmtInt} tick={{ fill: "var(--muted)", fontSize: 12 }} />;
  const yaxisR = <YAxis yAxisId="checks" orientation="right" allowDecimals={false} tick={{ fill: "var(--muted)", fontSize: 12 }} />;
  const tooltip = (
    <Tooltip
      contentStyle={{ background: "var(--bg)", border: "1px solid var(--grid)", borderRadius: 8 }}
      labelStyle={{ color: "var(--text)" }}
      formatter={(val, name) => (name === "Чеки" ? `${val} шт` : `${fmtInt(Number(val))} ₽`)}
    />
  );
  const legend = <Legend wrapperStyle={{ fontSize: 12, color: "var(--muted)" }} />;

  const render = () => {
    if (type === "area") {
      return (
        <AreaChart data={chartData}>
          {grid}{xaxis}{yaxisL}{yaxisR}{tooltip}{legend}
          <Area yAxisId="money" type="monotone" dataKey="Выручка" stroke={COLORS.primary} strokeWidth={2} fill={COLORS.primary} fillOpacity={0.2} />
          <Area yAxisId="checks" type="monotone" dataKey="Чеки" stroke={COLORS.good} strokeWidth={2} fill="transparent" />
        </AreaChart>
      );
    }
    if (type === "line" || type === "step") {
      const t = type === "step" ? "stepAfter" : "monotone";
      return (
        <LineChart data={chartData}>
          {grid}{xaxis}{yaxisL}{yaxisR}{tooltip}{legend}
          <Line yAxisId="money" type={t} dataKey="Выручка" stroke={COLORS.primary} strokeWidth={2} dot={false} />
          <Line yAxisId="checks" type={t} dataKey="Чеки" stroke={COLORS.good} strokeWidth={2} dot={false} />
        </LineChart>
      );
    }
    return (
      <BarChart data={chartData}>
        {grid}{xaxis}{yaxisL}{yaxisR}{tooltip}{legend}
        <Bar yAxisId="money" dataKey="Выручка" fill={COLORS.primary} radius={[4, 4, 0, 0]} />
        <Bar yAxisId="checks" dataKey="Чеки" fill={COLORS.good} radius={[4, 4, 0, 0]} />
      </BarChart>
    );
  };

  return (
    <div style={{ background: "var(--card)", borderRadius: 12, padding: "20px 24px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8, marginBottom: 16 }}>
        <div style={{ color: "var(--text)", fontWeight: 600 }}>Продажи по часам</div>
        <div style={{ display: "flex", background: "var(--bg)", borderRadius: 8, padding: 3, gap: 2 }}>
          {CHART_TYPES.map((t) => (
            <button
              key={t.key}
              onClick={() => setType(t.key)}
              style={{
                padding: "5px 12px", borderRadius: 6, border: "none", cursor: "pointer",
                fontSize: 12, fontWeight: 600,
                background: type === t.key ? COLORS.primary : "transparent",
                color: type === t.key ? "var(--text)" : "var(--muted)",
              }}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>
      <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
        {render()}
      </ResponsiveContainer>
      {!q.isLoading && (q.data?.data.length ?? 0) === 0 && (
        <div style={{ color: "var(--muted)", textAlign: "center", padding: 24 }}>Нет данных</div>
      )}
    </div>
  );
}
