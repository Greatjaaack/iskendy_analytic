import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AreaChart, Area, LineChart, Line, BarChart, Bar,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from "recharts";
import { fetchHourly, fetchHourlyByChannel, rangeKey, type RangeSel } from "../api";
import { CHART_HEIGHT, REFETCH_INTERVAL_MS, CHART_TYPES, COLORS, type ChartKind } from "../constants";
import { fmtInt } from "../format";

const chColor = (ch: string) =>
  ch === "доставка" ? COLORS.primary : ch === "с собой" ? COLORS.warn : COLORS.good;

interface Props {
  range: RangeSel;
}

/** Продажи по часам. Режимы: «Сумма» (выручка+чеки) и «По статусам» (зал/с собой/доставка
 *  с переключателями каналов). */
export function HourlyChart({ range }: Props) {
  const [type, setType] = useState<ChartKind>("bar");
  const [byChannel, setByChannel] = useState(false);
  const [hidden, setHidden] = useState<Set<string>>(new Set());

  const sumQ = useQuery({
    queryKey: ["hourly", rangeKey(range)],
    queryFn: () => fetchHourly(range),
    refetchInterval: REFETCH_INTERVAL_MS,
    enabled: !byChannel,
  });
  const chQ = useQuery({
    queryKey: ["hourly-by-channel", rangeKey(range)],
    queryFn: () => fetchHourlyByChannel(range),
    refetchInterval: REFETCH_INTERVAL_MS,
    enabled: byChannel,
  });

  const toggleChannel = (c: string) =>
    setHidden((prev) => {
      const next = new Set(prev);
      if (next.has(c)) next.delete(c);
      else next.add(c);
      return next;
    });

  const channels = chQ.data?.channels ?? [];
  const visible = channels.filter((c) => !hidden.has(c));

  const sumData = (sumQ.data?.data ?? []).map((h) => ({ label: h.label, Выручка: h.revenue, Чеки: h.checks }));
  const chData = (chQ.data?.data ?? []).map((h) => {
    const row: Record<string, number | string> = { label: h.label };
    channels.forEach((c) => (row[c] = Number(h[c] ?? 0)));
    return row;
  });
  const chartData = byChannel ? chData : sumData;
  const loading = byChannel ? chQ.isLoading : sumQ.isLoading;

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

  const render = () => {
    if (byChannel) {
      if (type === "area") return <AreaChart data={chartData}>{grid}{xaxis}{yaxisL}{tooltip}{legend}{channelSeries("area")}</AreaChart>;
      if (type === "line" || type === "step") return <LineChart data={chartData}>{grid}{xaxis}{yaxisL}{tooltip}{legend}{channelSeries("line")}</LineChart>;
      return <BarChart data={chartData}>{grid}{xaxis}{yaxisL}{tooltip}{legend}{channelSeries("bar")}</BarChart>;
    }
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
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <div style={{ display: "flex", background: "var(--bg)", borderRadius: 8, padding: 3, gap: 2 }}>
            <button onClick={() => setByChannel(false)} style={miniBtn(!byChannel)}>Сумма</button>
            <button onClick={() => setByChannel(true)} style={miniBtn(byChannel)}>По статусам</button>
          </div>
          <div style={{ display: "flex", background: "var(--bg)", borderRadius: 8, padding: 3, gap: 2 }}>
            {CHART_TYPES.map((t) => (
              <button key={t.key} onClick={() => setType(t.key)} style={miniBtn(type === t.key)}>{t.label}</button>
            ))}
          </div>
        </div>
      </div>

      {byChannel && channels.length > 0 && (
        <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap", marginBottom: 12 }}>
          <span style={{ color: "var(--muted)", fontSize: 12 }}>Статус:</span>
          {channels.map((c) => (
            <button key={c} onClick={() => toggleChannel(c)} style={chanChip(!hidden.has(c), chColor(c))}>{c}</button>
          ))}
        </div>
      )}

      <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
        {render()}
      </ResponsiveContainer>
      {!loading && chartData.length === 0 && (
        <div style={{ color: "var(--muted)", textAlign: "center", padding: 24 }}>Нет данных</div>
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
const chanChip = (active: boolean, color: string): React.CSSProperties => ({
  padding: "4px 10px", borderRadius: 6, cursor: "pointer", fontSize: 12, fontWeight: 600,
  border: `1px solid ${color}`,
  background: active ? color : "transparent",
  color: active ? "var(--text)" : "var(--muted)",
  opacity: active ? 1 : 0.6,
});
