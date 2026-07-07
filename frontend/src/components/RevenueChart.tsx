import { useState } from "react";
import { useLiveQuery } from "../hooks";
import {
  BarChart, Bar, Cell, ComposedChart, Line,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend, ReferenceLine,
} from "recharts";
import { fetchRevenueByChannel, rangeKey, type PrevDay, type RangeSel, type RevenueDay } from "../api";
import {
  CHART_HEIGHT, COLORS,
  WEEKDAY_GROUPS, WEEKDAYS_ALL, WEEKDAYS_WEEKEND, WEEKDAYS_WORK,
  weekdayGroup,
} from "../constants";
import { fmtInt } from "../format";

interface Props {
  data: RevenueDay[];
  prevData: PrevDay[];
  range: RangeSel;
  withDelivery?: boolean;
}

type View = "sum" | "channel" | "weather";
const VIEWS: { key: View; label: string }[] = [
  { key: "sum", label: "Сумма" },
  { key: "channel", label: "По статусам" },
  { key: "weather", label: "Погода" },
];

const chColor = (ch: string) =>
  ch === "доставка" ? COLORS.primary : ch === "с собой" ? COLORS.warn : COLORS.good;

// «2026-06-22» → «22.06» (день.месяц — привычный для чтения порядок: видно, какое это число).
const dm = (iso: string) => {
  const [, mm, dd] = iso.split("-");
  return `${dd}.${mm}`;
};
// Подпись дня на оси X: «Пн 22.06» (день недели + число).
const dayLabel = (d: { day_of_week: string; date: string }) => `${d.day_of_week} ${dm(d.date)}`;

export function RevenueChart({ data, prevData, range, withDelivery = true }: Props) {
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

  const chQ = useLiveQuery({
    queryKey: ["revenue-by-channel", rangeKey(range), withDelivery],
    queryFn: () => fetchRevenueByChannel(range, withDelivery),
    enabled: view === "channel",
  });

  // фильтр по дням недели имеет смысл только когда дней больше одного; для одного дня
  // (период «Сегодня» / диапазон из одной даты) он скрыт и не должен ничего отсекать,
  // иначе стае-выбор (напр. «Будни») оставил бы единственный день пустым (#1).
  const multiDay = data.length > 1;
  const dayOk = (dow: string) => !multiDay || days.size === 0 || days.has(dow);

  // погода под датой на оси X (структурно: иконка / температура / дельта к тому же дню
  // прошлого периода) — чтобы на оси было ясно, что есть что
  interface Wx { temp: number | null; delta: number | null }
  const weatherByLabel: Record<string, Wx> = {};
  data.forEach((d, i) => {
    const t = d.weather?.temp_max;
    if (t == null) return;
    const pt = prevData[i]?.temp_max;
    weatherByLabel[dayLabel(d)] = {
      temp: Math.round(t),
      delta: pt != null ? Math.round(t - pt) : null,
    };
  });
  // дельта теплее → тёплый цвет (warn), холоднее → холодный (accent), без изменения — приглушённо
  const deltaColor = (dl: number) => (dl > 0 ? COLORS.warn : dl < 0 ? COLORS.accent : "var(--muted)");
  const renderTick = (props: { x?: number | string; y?: number | string; payload?: { value?: string | number } }) => {
    const label = String(props.payload?.value ?? "");
    const w = weatherByLabel[label];
    return (
      <g transform={`translate(${Number(props.x ?? 0)},${Number(props.y ?? 0)})`}>
        <text x={0} y={0} dy={12} textAnchor="middle" fill="var(--muted)" fontSize={12}>{label}</text>
        {w && (
          <text x={0} y={0} dy={28} textAnchor="middle" fontSize={12}>
            {w.temp != null && <tspan fill="var(--text)" fontWeight={600}>{w.temp}°</tspan>}
            {w.delta != null && (
              <tspan dx={5} fill={deltaColor(w.delta)}>
                ({w.delta >= 0 ? "+" : ""}{w.delta}°)
              </tspan>
            )}
          </text>
        )}
      </g>
    );
  };

  // при выкл «С доставкой» канал доставки убираем из разреза целиком (как в ChecksDistribution)
  const channels = (chQ.data?.channels ?? []).filter((c) => withDelivery || c !== "доставка");
  const visible = channels.filter((c) => !hidden.has(c));

  const sumData = data.filter((d) => dayOk(d.day_of_week)).map((d) => ({
    label: dayLabel(d),
    dow: d.day_of_week,
    Выручка: d.total_sum,
    "Ср. чек": d.avg_check,
    Чеки: d.check_count,
  }));
  // среднесуточная выручка за период — опорная линия, чтобы видеть дни выше/ниже нормы
  const avgRev = sumData.length
    ? Math.round(sumData.reduce((s, r) => s + r.Выручка, 0) / sumData.length)
    : 0;
  const chData = (chQ.data?.data ?? []).filter((d) => dayOk(d.day_of_week)).map((d) => {
    const row: Record<string, number | string> = { label: dayLabel(d) };
    channels.forEach((c) => (row[c] = Number(d[c] ?? 0)));
    return row;
  });
  // «Погода»: выручка и температура текущего и прошлого периода, выровнены по позиции дня
  const weatherData = data
    .map((d, i) => ({ d, p: prevData[i] }))
    .filter(({ d }) => dayOk(d.day_of_week))
    .map(({ d, p }) => ({
      label: dayLabel(d),
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
  // подсказка режима «Сумма»: выручка + ср. чек + чеки одного дня (последние два
  // больше не рисуются столбцами, поэтому собираем их из строки данных вручную)
  const sumTooltip = <Tooltip cursor={{ fill: "var(--grid)", opacity: 0.3 }} content={SumTooltip} />;
  // опорная линия среднего рисуется только когда дней > 1 (для одного дня бессмысленна)
  const avgLine = sumData.length > 1 && (
    <ReferenceLine
      yAxisId="money"
      y={avgRev}
      stroke="var(--muted)"
      strokeDasharray="6 4"
      label={{ value: `ср. ${fmtInt(avgRev)} ₽`, fill: "var(--muted)", fontSize: 11, position: "insideTopRight" }}
    />
  );

  // Дни и часы — дискретные корзины, поэтому форма всегда столбчатая (линия/область
  // рисовали бы ложную непрерывность и не несли раскраску по группам дней недели).
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
      return (
        <BarChart data={chartData}>
          {grid}{xaxis}{yMoney}{tooltip}{legend}
          {visible.map((c) => (
            <Bar key={c} yAxisId="money" dataKey={c} stackId="ch" fill={chColor(c)} />
          ))}
        </BarChart>
      );
    }
    // Режим «Сумма»: один ряд «Выручка», окрашенный по группе дня недели
    // (Пн / Вт-Ср / Чт / выходные Пт-Вс). Ср. чек и Чеки — не отдельные столбцы,
    // а строки во всплывающей подсказке (sumTooltip), чтобы не дробить график.
    return (
      <BarChart data={chartData}>
        {grid}{xaxis}{yMoney}{sumTooltip}{avgLine}
        <Bar yAxisId="money" dataKey="Выручка" radius={[4, 4, 0, 0]}>
          {sumData.map((r) => (
            <Cell key={r.label} fill={weekdayGroup(r.dow).color} />
          ))}
        </Bar>
      </BarChart>
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

      {view === "sum" && (
        <div style={{ display: "flex", gap: 14, alignItems: "center", flexWrap: "wrap", marginBottom: 12 }}>
          {WEEKDAY_GROUPS.map((g) => (
            <span key={g.key} style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12, color: "var(--muted)" }}>
              <span style={{ width: 10, height: 10, borderRadius: 3, background: g.color, display: "inline-block" }} />
              {g.label}
            </span>
          ))}
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

interface SumRow {
  label: string;
  dow: string;
  Выручка: number;
  "Ср. чек": number;
  Чеки: number;
}

// Всплывающая подсказка режима «Сумма»: выручка дня + ср. чек + число чеков
// (в самом графике остаётся только столбец выручки, окрашенный по группе дня).
function SumTooltip({ active, payload }: { active?: boolean; payload?: readonly { payload?: SumRow }[] }) {
  const r = active ? payload?.[0]?.payload : undefined;
  if (!r) return null;
  const g = weekdayGroup(r.dow);
  const row = (label: string, value: string) => (
    <div style={{ display: "flex", justifyContent: "space-between", gap: 16 }}>
      <span style={{ color: "var(--muted)" }}>{label}</span>
      <span style={{ color: "var(--text)", fontWeight: 600 }}>{value}</span>
    </div>
  );
  return (
    <div style={{ background: "var(--bg)", border: "1px solid var(--grid)", borderRadius: 8, padding: "8px 12px", fontSize: 12, minWidth: 160 }}>
      <div style={{ color: "var(--text)", fontWeight: 600, marginBottom: 6 }}>
        {r.label} · <span style={{ color: g.color }}>{g.label}</span>
      </div>
      {row("Выручка", `${fmtInt(r["Выручка"])} ₽`)}
      {row("Ср. чек", `${fmtInt(r["Ср. чек"])} ₽`)}
      {row("Чеки", `${r["Чеки"]} шт`)}
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
