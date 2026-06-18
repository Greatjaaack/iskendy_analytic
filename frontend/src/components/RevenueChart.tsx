import { useState } from "react";
import {
  AreaChart, Area, LineChart, Line, BarChart, Bar,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from "recharts";
import type { RevenueDay } from "../api";
import {
  CHART_HEIGHT,
  CHART_TYPES,
  COLORS,
  WEEKDAYS_ALL,
  WEEKDAYS_WEEKEND,
  WEEKDAYS_WORK,
  weatherInfo,
  type ChartKind,
} from "../constants";
import { fmtInt } from "../format";

interface Props {
  data: RevenueDay[];
}

export function RevenueChart({ data }: Props) {
  const [type, setType] = useState<ChartKind>("area");
  // мультивыбор дней недели; пустое множество = показывать все дни
  const [days, setDays] = useState<Set<string>>(new Set());

  const toggleDay = (d: string) =>
    setDays((prev) => {
      const next = new Set(prev);
      if (next.has(d)) next.delete(d);
      else next.add(d);
      return next;
    });
  const setPreset = (preset: string[]) => setDays(new Set(preset));

  const filtered = days.size === 0 ? data : data.filter((d) => days.has(d.day_of_week));

  const chartData = filtered.map((d) => {
    const info = d.weather ? weatherInfo(d.weather.weather_code) : null;
    const t = d.weather?.temp_max;
    return {
      label: `${d.day_of_week} ${d.date.slice(5)}`,
      weather: info ? `${info.icon}${t != null ? ` ${Math.round(t)}°` : ""}` : "",
      Выручка: d.total_sum,
      "Ср. чек": d.avg_check,
      Чеки: d.check_count,
    };
  });
  // погода прямо под датой на оси X (чтобы не искать в отдельном списке)
  const weatherByLabel: Record<string, string> = {};
  chartData.forEach((d) => {
    if (d.weather) weatherByLabel[d.label] = d.weather;
  });
  const renderTick = (props: {
    x?: number | string;
    y?: number | string;
    payload?: { value?: string | number };
  }) => {
    const label = String(props.payload?.value ?? "");
    const w = weatherByLabel[label];
    return (
      <g transform={`translate(${Number(props.x ?? 0)},${Number(props.y ?? 0)})`}>
        <text x={0} y={0} dy={12} textAnchor="middle" fill="var(--muted)" fontSize={12}>{label}</text>
        {w && (
          <text x={0} y={0} dy={28} textAnchor="middle" fill="var(--muted)" fontSize={12}>{w}</text>
        )}
      </g>
    );
  };

  const axisProps = {
    tick: { fill: "var(--muted)", fontSize: 12 },
  };
  const grid = <CartesianGrid strokeDasharray="3 3" stroke="var(--grid)" />;
  const xaxis = <XAxis dataKey="label" tick={renderTick} interval={0} height={46} />;
  // левая ось — деньги (выручка/ср.чек), правая — количество чеков (другой масштаб)
  const yaxisL = <YAxis yAxisId="money" tickFormatter={fmtInt} {...axisProps} />;
  const yaxisR = <YAxis yAxisId="checks" orientation="right" allowDecimals={false} {...axisProps} />;
  const tooltip = (
    <Tooltip
      contentStyle={{ background: "var(--bg)", border: "1px solid var(--grid)", borderRadius: 8 }}
      labelStyle={{ color: "var(--text)" }}
      formatter={(val, name) => (name === "Чеки" ? `${val} шт` : `${fmtInt(Number(val))} ₽`)}
    />
  );
  const legend = <Legend wrapperStyle={{ fontSize: 12, color: "var(--muted)" }} />;

  const renderChart = () => {
    if (type === "bar") {
      return (
        <BarChart data={chartData}>
          {grid}{xaxis}{yaxisL}{yaxisR}{tooltip}{legend}
          <Bar yAxisId="money" dataKey="Выручка" fill={COLORS.primary} radius={[4, 4, 0, 0]} />
          <Bar yAxisId="money" dataKey="Ср. чек" fill={COLORS.accent} radius={[4, 4, 0, 0]} />
          <Bar yAxisId="checks" dataKey="Чеки" fill={COLORS.good} radius={[4, 4, 0, 0]} />
        </BarChart>
      );
    }
    if (type === "area") {
      return (
        <AreaChart data={chartData}>
          <defs>
            <linearGradient id="revGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor={COLORS.primary} stopOpacity={0.4} />
              <stop offset="95%" stopColor={COLORS.primary} stopOpacity={0} />
            </linearGradient>
          </defs>
          {grid}{xaxis}{yaxisL}{yaxisR}{tooltip}{legend}
          <Area yAxisId="money" type="monotone" dataKey="Выручка" stroke={COLORS.primary} strokeWidth={2} fill="url(#revGrad)" />
          <Area yAxisId="money" type="monotone" dataKey="Ср. чек" stroke={COLORS.accent} strokeWidth={2} fill="transparent" />
          <Area yAxisId="checks" type="monotone" dataKey="Чеки" stroke={COLORS.good} strokeWidth={2} fill="transparent" />
        </AreaChart>
      );
    }
    // line / step
    return (
      <LineChart data={chartData}>
        {grid}{xaxis}{yaxisL}{yaxisR}{tooltip}{legend}
        <Line yAxisId="money" type={type === "step" ? "stepAfter" : "monotone"} dataKey="Выручка" stroke={COLORS.primary} strokeWidth={2} dot={false} />
        <Line yAxisId="money" type={type === "step" ? "stepAfter" : "monotone"} dataKey="Ср. чек" stroke={COLORS.accent} strokeWidth={2} dot={false} />
        <Line yAxisId="checks" type={type === "step" ? "stepAfter" : "monotone"} dataKey="Чеки" stroke={COLORS.good} strokeWidth={2} dot={false} />
      </LineChart>
    );
  };

  return (
    <div style={{ background: "var(--card)", borderRadius: 12, padding: "20px 24px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8, marginBottom: 12 }}>
        <div style={{ color: "var(--text)", fontWeight: 600 }}>Выручка по дням</div>
        <div style={{ display: "flex", background: "var(--bg)", borderRadius: 8, padding: 3, gap: 2 }}>
          {CHART_TYPES.map((t) => (
            <button key={t.key} onClick={() => setType(t.key)} style={miniBtn(type === t.key)}>
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {/* Мультивыбор дней недели: пусто = все дни */}
      <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap", marginBottom: 16 }}>
        <span style={{ color: "var(--muted)", fontSize: 12, marginRight: 2 }}>Дни:</span>
        {WEEKDAYS_ALL.map((d) => (
          <button key={d} onClick={() => toggleDay(d)} style={chip(days.has(d))}>
            {d}
          </button>
        ))}
        <span style={{ width: 1, height: 18, background: "var(--grid)", margin: "0 4px" }} />
        <button onClick={() => setPreset([])} style={chip(days.size === 0)}>Все</button>
        <button onClick={() => setPreset(WEEKDAYS_WORK)} style={chip(false)}>Будни</button>
        <button onClick={() => setPreset(WEEKDAYS_WEEKEND)} style={chip(false)}>Выходные</button>
      </div>
      <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
        {renderChart()}
      </ResponsiveContainer>

      {chartData.length === 0 && (
        <div style={{ color: "var(--muted)", textAlign: "center", padding: 24 }}>
          Нет данных для выбранного фильтра
        </div>
      )}
    </div>
  );
}

const miniBtn = (active: boolean): React.CSSProperties => ({
  padding: "5px 12px", borderRadius: 6, border: "none", cursor: "pointer",
  fontSize: 12, fontWeight: 600,
  background: active ? COLORS.primary : "transparent",
  color: active ? "var(--text)" : "var(--muted)",
});

const chip = (active: boolean): React.CSSProperties => ({
  padding: "4px 10px", borderRadius: 6, cursor: "pointer", fontSize: 12, fontWeight: 600,
  border: `1px solid ${active ? COLORS.primary : "var(--grid)"}`,
  background: active ? COLORS.primary : "transparent",
  color: active ? "var(--text)" : "var(--muted)",
});
