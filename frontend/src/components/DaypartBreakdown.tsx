import { useQuery } from "@tanstack/react-query";
import {
  BarChart, Bar, Cell, LabelList,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from "recharts";
import { fetchByDaypart, rangeKey, type RangeSel, type DaypartRow } from "../api";
import { CHART_HEIGHT, REFETCH_INTERVAL_MS, COLORS } from "../constants";
import { fmtInt } from "../format";

interface Props {
  range: RangeSel;
  withDelivery?: boolean;
}

// Цвет столбца = операционное окно дня (своя палитра по дейпарту).
const DAYPART_COLORS: Record<string, string> = {
  breakfast: COLORS.accent, // утро — циан
  lunch: COLORS.primary, // ланч — индиго (главный объём)
  afternoon: COLORS.warn, // полдник — жёлтый
  dinner: "#a855f7", // ужин — фиолетовый
  night: COLORS.muted, // ночь — приглушённый
};

function DaypartTooltip({ active, payload }: { active?: boolean; payload?: { payload: DaypartRow }[] }) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <div style={{ background: "var(--bg)", border: "1px solid var(--grid)", borderRadius: 8, padding: "10px 12px", fontSize: 12 }}>
      <div style={{ color: "var(--text)", fontWeight: 600, marginBottom: 6 }}>
        {d.label} <span style={{ color: "var(--muted)", fontWeight: 400 }}>{d.range}</span>
      </div>
      <div style={{ color: "var(--text)" }}>
        {fmtInt(d.revenue)} ₽ <span style={{ color: "var(--muted)" }}>· {d.revenue_share}% выручки</span>
      </div>
      <div style={{ color: "var(--muted)", marginTop: 2 }}>Чеков: {fmtInt(d.checks)}</div>
      <div style={{ color: "var(--muted)" }}>Ср. чек: {fmtInt(d.avg_check)} ₽</div>
    </div>
  );
}

/** Выручка по дейпартам: где зарабатывает день (Завтрак/Ланч/Полдник/Ужин/Ночь). */
export function DaypartBreakdown({ range, withDelivery = true }: Props) {
  const q = useQuery({
    queryKey: ["by-daypart", rangeKey(range), withDelivery],
    queryFn: () => fetchByDaypart(range, withDelivery),
    refetchInterval: REFETCH_INTERVAL_MS,
  });

  // пустые окна (часто Ночь/Завтрак) не показываем — не засоряем ось
  const rows = (q.data?.data ?? []).filter((d) => d.revenue > 0 || d.checks > 0);

  return (
    <div style={{ background: "var(--card)", borderRadius: 12, padding: "20px 24px" }}>
      <div style={{ color: "var(--text)", fontWeight: 600 }}>Выручка по дейпартам</div>
      <div style={{ color: "var(--muted)", fontSize: 12, marginTop: 2, marginBottom: 16 }}>
        Когда зарабатывает день — окна по времени
      </div>

      <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
        <BarChart data={rows} margin={{ top: 20, right: 8, left: 8, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--grid)" vertical={false} />
          <XAxis dataKey="label" tick={{ fill: "var(--muted)", fontSize: 12 }} />
          <YAxis tickFormatter={fmtInt} tick={{ fill: "var(--muted)", fontSize: 12 }} />
          <Tooltip content={<DaypartTooltip />} cursor={{ fill: "var(--grid)", opacity: 0.3 }} />
          <Bar dataKey="revenue" radius={[4, 4, 0, 0]}>
            {rows.map((d) => (
              <Cell key={d.key} fill={DAYPART_COLORS[d.key] ?? COLORS.primary} />
            ))}
            <LabelList
              dataKey="revenue_share"
              position="top"
              formatter={(v) => `${v}%`}
              style={{ fill: "var(--muted)", fontSize: 11 }}
            />
          </Bar>
        </BarChart>
      </ResponsiveContainer>

      {rows.length > 0 && (
        <table style={{ width: "100%", borderCollapse: "collapse", marginTop: 16, fontSize: 13 }}>
          <thead>
            <tr style={{ color: "var(--muted)", textAlign: "right" }}>
              <th style={{ textAlign: "left", fontWeight: 500, padding: "6px 8px" }}>Дейпарт</th>
              <th style={{ fontWeight: 500, padding: "6px 8px" }}>Выручка</th>
              <th style={{ fontWeight: 500, padding: "6px 8px" }}>Доля</th>
              <th style={{ fontWeight: 500, padding: "6px 8px" }}>Чеки</th>
              <th style={{ fontWeight: 500, padding: "6px 8px" }}>Ср. чек</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((d) => (
              <tr key={d.key} style={{ borderTop: "1px solid var(--grid)", color: "var(--text)", textAlign: "right" }}>
                <td style={{ textAlign: "left", padding: "6px 8px" }}>
                  <span style={{
                    display: "inline-block", width: 8, height: 8, borderRadius: 2, marginRight: 8,
                    background: DAYPART_COLORS[d.key] ?? COLORS.primary, verticalAlign: "middle",
                  }} />
                  {d.label} <span style={{ color: "var(--muted)" }}>{d.range}</span>
                </td>
                <td style={{ padding: "6px 8px" }}>{fmtInt(d.revenue)} ₽</td>
                <td style={{ padding: "6px 8px", color: "var(--muted)" }}>{d.revenue_share}%</td>
                <td style={{ padding: "6px 8px" }}>{fmtInt(d.checks)}</td>
                <td style={{ padding: "6px 8px" }}>{fmtInt(d.avg_check)} ₽</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {!q.isLoading && rows.length === 0 && (
        <div style={{ color: "var(--muted)", textAlign: "center", padding: 24 }}>Нет данных</div>
      )}
    </div>
  );
}
