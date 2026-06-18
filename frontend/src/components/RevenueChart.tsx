import { useState } from "react";
import {
  AreaChart, Area, LineChart, Line, BarChart, Bar,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from "recharts";
import type { RevenueDay } from "../api";
import { CHART_HEIGHT, weatherInfo } from "../constants";

interface Props {
  data: RevenueDay[];
}

const fmt = (n: number) =>
  new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(n);

type ChartType = "area" | "line" | "step" | "bar";
const CHART_TYPES: { key: ChartType; label: string }[] = [
  { key: "area", label: "Область" },
  { key: "line", label: "Линия" },
  { key: "step", label: "Ступени" },
  { key: "bar", label: "Столбцы" },
];

const ALL_DAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];
const WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт"];
const WEEKEND = ["Сб", "Вс"];

export function RevenueChart({ data }: Props) {
  const [type, setType] = useState<ChartType>("area");
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

  const chartData = filtered.map((d) => ({
    label: `${d.day_of_week} ${d.date.slice(5)}`,
    Выручка: d.total_sum,
    "Ср. чек": d.avg_check,
    Чеки: d.check_count,
  }));

  const axisProps = {
    tick: { fill: "var(--muted)", fontSize: 12 },
  };
  const grid = <CartesianGrid strokeDasharray="3 3" stroke="var(--grid)" />;
  const xaxis = <XAxis dataKey="label" {...axisProps} />;
  // левая ось — деньги (выручка/ср.чек), правая — количество чеков (другой масштаб)
  const yaxisL = <YAxis yAxisId="money" tickFormatter={fmt} {...axisProps} />;
  const yaxisR = <YAxis yAxisId="checks" orientation="right" allowDecimals={false} {...axisProps} />;
  const tooltip = (
    <Tooltip
      contentStyle={{ background: "var(--bg)", border: "1px solid var(--grid)", borderRadius: 8 }}
      labelStyle={{ color: "var(--text)" }}
      formatter={(val, name) => (name === "Чеки" ? `${val} шт` : `${fmt(Number(val))} ₽`)}
    />
  );
  const legend = <Legend wrapperStyle={{ fontSize: 12, color: "var(--muted)" }} />;

  const renderChart = () => {
    if (type === "bar") {
      return (
        <BarChart data={chartData}>
          {grid}{xaxis}{yaxisL}{yaxisR}{tooltip}{legend}
          <Bar yAxisId="money" dataKey="Выручка" fill="#6366f1" radius={[4, 4, 0, 0]} />
          <Bar yAxisId="money" dataKey="Ср. чек" fill="#22d3ee" radius={[4, 4, 0, 0]} />
          <Bar yAxisId="checks" dataKey="Чеки" fill="#10b981" radius={[4, 4, 0, 0]} />
        </BarChart>
      );
    }
    if (type === "area") {
      return (
        <AreaChart data={chartData}>
          <defs>
            <linearGradient id="revGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#6366f1" stopOpacity={0.4} />
              <stop offset="95%" stopColor="#6366f1" stopOpacity={0} />
            </linearGradient>
          </defs>
          {grid}{xaxis}{yaxisL}{yaxisR}{tooltip}{legend}
          <Area yAxisId="money" type="monotone" dataKey="Выручка" stroke="#6366f1" strokeWidth={2} fill="url(#revGrad)" />
          <Area yAxisId="money" type="monotone" dataKey="Ср. чек" stroke="#22d3ee" strokeWidth={2} fill="transparent" />
          <Area yAxisId="checks" type="monotone" dataKey="Чеки" stroke="#10b981" strokeWidth={2} fill="transparent" />
        </AreaChart>
      );
    }
    // line / step
    return (
      <LineChart data={chartData}>
        {grid}{xaxis}{yaxisL}{yaxisR}{tooltip}{legend}
        <Line yAxisId="money" type={type === "step" ? "stepAfter" : "monotone"} dataKey="Выручка" stroke="#6366f1" strokeWidth={2} dot={false} />
        <Line yAxisId="money" type={type === "step" ? "stepAfter" : "monotone"} dataKey="Ср. чек" stroke="#22d3ee" strokeWidth={2} dot={false} />
        <Line yAxisId="checks" type={type === "step" ? "stepAfter" : "monotone"} dataKey="Чеки" stroke="#10b981" strokeWidth={2} dot={false} />
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
        {ALL_DAYS.map((d) => (
          <button key={d} onClick={() => toggleDay(d)} style={chip(days.has(d))}>
            {d}
          </button>
        ))}
        <span style={{ width: 1, height: 18, background: "var(--grid)", margin: "0 4px" }} />
        <button onClick={() => setPreset([])} style={chip(days.size === 0)}>Все</button>
        <button onClick={() => setPreset(WEEKDAYS)} style={chip(false)}>Будни</button>
        <button onClick={() => setPreset(WEEKEND)} style={chip(false)}>Выходные</button>
      </div>
      <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
        {renderChart()}
      </ResponsiveContainer>

      {/* Погода в Москве по дням (#5) — показываем, если данные есть */}
      {filtered.some((d) => d.weather) && (
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginTop: 12, fontSize: 12, color: "var(--muted)" }}>
          {filtered.map((d) => {
            const w = d.weather;
            if (!w) return null;
            const info = weatherInfo(w.weather_code);
            return (
              <span key={d.date} title={info.label}>
                {d.day_of_week} {d.date.slice(8)}: {info.icon}
                {w.temp_max != null ? ` ${Math.round(w.temp_max)}°` : ""}
              </span>
            );
          })}
        </div>
      )}

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
  background: active ? "#6366f1" : "transparent",
  color: active ? "var(--text)" : "var(--muted)",
});

const chip = (active: boolean): React.CSSProperties => ({
  padding: "4px 10px", borderRadius: 6, cursor: "pointer", fontSize: 12, fontWeight: 600,
  border: `1px solid ${active ? "#6366f1" : "var(--grid)"}`,
  background: active ? "#6366f1" : "transparent",
  color: active ? "var(--text)" : "var(--muted)",
});
