import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AreaChart, Area, LineChart, Line, BarChart, Bar, ComposedChart,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from "recharts";
import { fetchRevenueByChannel, rangeKey, type PrevDay, type RangeSel, type RevenueDay } from "../api";
import {
  CHART_HEIGHT, CHART_TYPES, COLORS, REFETCH_INTERVAL_MS,
  WEEKDAYS_ALL, WEEKDAYS_WEEKEND, WEEKDAYS_WORK, weatherInfo, type ChartKind,
} from "../constants";
import { fmtInt } from "../format";

interface Props {
  data: RevenueDay[];
  prevData: PrevDay[];
  range: RangeSel;
}

type View = "sum" | "channel" | "weather";
const VIEWS: { key: View; label: string }[] = [
  { key: "sum", label: "Сумма" },
  { key: "channel", label: "По статусам" },
  { key: "weather", label: "Погода" },
];

const chColor = (ch: string) =>
  ch === "доставка" ? COLORS.primary : ch === "с собой" ? COLORS.warn : COLORS.good;

export function RevenueChart({ data, prevData, range }: Props) {
  const [type, setType] = useState<ChartKind>("area");
  const [days, setDays] = useState<Set<string>>(new Set());
  const [view, setView] = useState<View>("sum");
  const [hidden, setHidden] = useState<Set<string>>(new Set());

  const toggleDay = (d: string) =>
    setDays((prev) => {
      const next = new Set(prev);
      if (next.has(d)) next.delete(d);
      else next.add(d);
      return next;
    });
  const toggleChannel = (c: string) =>
    setHidden((prev) => {
      const next = new Set(prev);
      if (next.has(c)) next.delete(c);
      else next.add(c);
      return next;
    });

  const chQ = useQuery({
    queryKey: ["revenue-by-channel", rangeKey(range)],
    queryFn: () => fetchRevenueByChannel(range),
    refetchInterval: REFETCH_INTERVAL_MS,
    enabled: view === "channel",
  });

  // фильтр по дням недели имеет смысл только когда дней больше одного; для одного дня
  // (период «Сегодня» / диапазон из одной даты) он скрыт и не должен ничего отсекать,
  // иначе стае-выбор (напр. «Будни») оставил бы единственный день пустым (#1).
  const multiDay = data.length > 1;
  const dayOk = (dow: string) => !multiDay || days.size === 0 || days.has(dow);

  // погода под датой на оси X + дельта температуры к тому же дню прошлого периода
  const weatherByLabel: Record<string, string> = {};
  data.forEach((d, i) => {
    const info = d.weather ? weatherInfo(d.weather.weather_code) : null;
    if (!info) return;
    const t = d.weather?.temp_max;
    let s = `${info.icon}${t != null ? ` ${Math.round(t)}°` : ""}`;
    const pt = prevData[i]?.temp_max;
    if (t != null && pt != null) {
      const dl = Math.round(t - pt);
      s += ` ${dl >= 0 ? "+" : ""}${dl}°`;
    }
    weatherByLabel[`${d.day_of_week} ${d.date.slice(5)}`] = s;
  });
  const renderTick = (props: { x?: number | string; y?: number | string; payload?: { value?: string | number } }) => {
    const label = String(props.payload?.value ?? "");
    const w = weatherByLabel[label];
    return (
      <g transform={`translate(${Number(props.x ?? 0)},${Number(props.y ?? 0)})`}>
        <text x={0} y={0} dy={12} textAnchor="middle" fill="var(--muted)" fontSize={12}>{label}</text>
        {w && <text x={0} y={0} dy={28} textAnchor="middle" fill="var(--muted)" fontSize={12}>{w}</text>}
      </g>
    );
  };

  const channels = chQ.data?.channels ?? [];
  const visible = channels.filter((c) => !hidden.has(c));

  const sumData = data.filter((d) => dayOk(d.day_of_week)).map((d) => ({
    label: `${d.day_of_week} ${d.date.slice(5)}`,
    Выручка: d.total_sum,
    "Ср. чек": d.avg_check,
    Чеки: d.check_count,
  }));
  const chData = (chQ.data?.data ?? []).filter((d) => dayOk(d.day_of_week)).map((d) => {
    const row: Record<string, number | string> = { label: `${d.day_of_week} ${d.date.slice(5)}` };
    channels.forEach((c) => (row[c] = Number(d[c] ?? 0)));
    return row;
  });
  // «Погода»: выручка и температура текущего и прошлого периода, выровнены по позиции дня
  const weatherData = data
    .map((d, i) => ({ d, p: prevData[i] }))
    .filter(({ d }) => dayOk(d.day_of_week))
    .map(({ d, p }) => ({
      label: `${d.day_of_week} ${d.date.slice(5)}`,
      Выручка: d.total_sum,
      // NaN → recharts рисует разрыв (нет данных за прошлый день); тип остаётся number
      "Выручка (пр.)": p?.total_sum ?? NaN,
      "t°": d.weather?.temp_max ?? NaN,
      "t° (пр.)": p?.temp_max ?? NaN,
    }));
  const chartData = view === "channel" ? chData : view === "weather" ? weatherData : sumData;

  const grid = <CartesianGrid strokeDasharray="3 3" stroke="var(--grid)" />;
  const xaxis = <XAxis dataKey="label" tick={renderTick} interval={0} height={46} />;
  const yMoney = <YAxis yAxisId="money" tickFormatter={fmtInt} tick={{ fill: "var(--muted)", fontSize: 12 }} />;
  const yChecks = <YAxis yAxisId="checks" orientation="right" allowDecimals={false} tick={{ fill: "var(--muted)", fontSize: 12 }} />;
  const yTemp = <YAxis yAxisId="temp" orientation="right" unit="°" tick={{ fill: "var(--muted)", fontSize: 12 }} />;
  const tooltip = (
    <Tooltip
      contentStyle={{ background: "var(--bg)", border: "1px solid var(--grid)", borderRadius: 8 }}
      labelStyle={{ color: "var(--text)" }}
      formatter={(val, name) =>
        name === "Чеки" ? `${val} шт` : String(name).startsWith("t°") ? `${val}°` : `${fmtInt(Number(val))} ₽`
      }
    />
  );
  const legend = <Legend wrapperStyle={{ fontSize: 12, color: "var(--muted)" }} />;

  const channelSeries = (kind: "area" | "line" | "bar") =>
    visible.map((c) =>
      kind === "bar" ? (
        <Bar key={c} yAxisId="money" dataKey={c} stackId="ch" fill={chColor(c)} />
      ) : kind === "area" ? (
        <Area key={c} yAxisId="money" type="monotone" dataKey={c} stackId="ch" stroke={chColor(c)} fill={chColor(c)} fillOpacity={0.35} />
      ) : (
        <Line key={c} yAxisId="money" type={type === "step" ? "stepAfter" : "monotone"} dataKey={c} stroke={chColor(c)} strokeWidth={2} dot={false} />
      ),
    );

  const renderChart = () => {
    if (view === "weather") {
      return (
        <ComposedChart data={chartData}>
          {grid}{xaxis}{yMoney}{yTemp}{tooltip}{legend}
          <Bar yAxisId="money" dataKey="Выручка" fill={COLORS.primary} radius={[4, 4, 0, 0]} />
          <Line yAxisId="money" type="monotone" dataKey="Выручка (пр.)" stroke={COLORS.accent} strokeWidth={2} strokeDasharray="5 4" dot={false} />
          <Line yAxisId="temp" type="monotone" dataKey="t°" stroke={COLORS.warn} strokeWidth={2} dot={false} />
          <Line yAxisId="temp" type="monotone" dataKey="t° (пр.)" stroke={COLORS.muted} strokeWidth={2} strokeDasharray="5 4" dot={false} />
        </ComposedChart>
      );
    }
    if (view === "channel") {
      if (type === "bar") return <BarChart data={chartData}>{grid}{xaxis}{yMoney}{tooltip}{legend}{channelSeries("bar")}</BarChart>;
      if (type === "area") return <AreaChart data={chartData}>{grid}{xaxis}{yMoney}{tooltip}{legend}{channelSeries("area")}</AreaChart>;
      return <LineChart data={chartData}>{grid}{xaxis}{yMoney}{tooltip}{legend}{channelSeries("line")}</LineChart>;
    }
    if (type === "bar") {
      return (
        <BarChart data={chartData}>
          {grid}{xaxis}{yMoney}{yChecks}{tooltip}{legend}
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
          {grid}{xaxis}{yMoney}{yChecks}{tooltip}{legend}
          <Area yAxisId="money" type="monotone" dataKey="Выручка" stroke={COLORS.primary} strokeWidth={2} fill="url(#revGrad)" />
          <Area yAxisId="money" type="monotone" dataKey="Ср. чек" stroke={COLORS.accent} strokeWidth={2} fill="transparent" />
          <Area yAxisId="checks" type="monotone" dataKey="Чеки" stroke={COLORS.good} strokeWidth={2} fill="transparent" />
        </AreaChart>
      );
    }
    return (
      <LineChart data={chartData}>
        {grid}{xaxis}{yMoney}{yChecks}{tooltip}{legend}
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
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <div style={{ display: "flex", background: "var(--bg)", borderRadius: 8, padding: 3, gap: 2 }}>
            {VIEWS.map((v) => (
              <button key={v.key} onClick={() => setView(v.key)} style={miniBtn(view === v.key)}>{v.label}</button>
            ))}
          </div>
          {view !== "weather" && (
            <div style={{ display: "flex", background: "var(--bg)", borderRadius: 8, padding: 3, gap: 2 }}>
              {CHART_TYPES.map((t) => (
                <button key={t.key} onClick={() => setType(t.key)} style={miniBtn(type === t.key)}>{t.label}</button>
              ))}
            </div>
          )}
        </div>
      </div>

      {(multiDay || (view === "channel" && channels.length > 0)) && (
        <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap", marginBottom: 16 }}>
          {multiDay && (
            <>
              <span style={{ color: "var(--muted)", fontSize: 12, marginRight: 2 }}>Дни:</span>
              {WEEKDAYS_ALL.map((d) => (
                <button key={d} onClick={() => toggleDay(d)} style={chip(days.has(d))}>{d}</button>
              ))}
              <button onClick={() => setDays(new Set())} style={chip(days.size === 0)}>Все</button>
              <button onClick={() => setDays(new Set(WEEKDAYS_WORK))} style={chip(false)}>Будни</button>
              <button onClick={() => setDays(new Set(WEEKDAYS_WEEKEND))} style={chip(false)}>Выходные</button>
            </>
          )}
          {view === "channel" && channels.length > 0 && (
            <>
              {multiDay && <span style={{ width: 1, height: 18, background: "var(--grid)", margin: "0 4px" }} />}
              <span style={{ color: "var(--muted)", fontSize: 12 }}>Статус:</span>
              {channels.map((c) => (
                <button key={c} onClick={() => toggleChannel(c)} style={chanChip(!hidden.has(c), chColor(c))}>{c}</button>
              ))}
            </>
          )}
        </div>
      )}

      <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
        {renderChart()}
      </ResponsiveContainer>

      {view === "channel" && chQ.isLoading && (
        <div style={{ color: "var(--muted)", textAlign: "center", padding: 24 }}>Загрузка разреза по статусам…</div>
      )}
      {chartData.length === 0 && !chQ.isLoading && (
        <div style={{ color: "var(--muted)", textAlign: "center", padding: 24 }}>Нет данных для выбранного фильтра</div>
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
const chanChip = (active: boolean, color: string): React.CSSProperties => ({
  padding: "4px 10px", borderRadius: 6, cursor: "pointer", fontSize: 12, fontWeight: 600,
  border: `1px solid ${color}`,
  background: active ? color : "transparent",
  color: active ? "var(--text)" : "var(--muted)",
  opacity: active ? 1 : 0.6,
});
