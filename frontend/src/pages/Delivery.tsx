import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from "recharts";
import { fetchKpiByChannel, fetchRevenueByChannel, rangeKey } from "../api";
import type { Period, RangeSel } from "../api";
import { REFETCH_INTERVAL_MS, COLORS, PERIODS, CHART_HEIGHT } from "../constants";
import { fmtInt } from "../format";

const todayISO = () => new Date().toISOString().slice(0, 10);
const daysAgoISO = (n: number) => new Date(Date.now() - n * 86_400_000).toISOString().slice(0, 10);

const CHANNEL_DELIVERY = "доставка";

/** Дашборд доставки: KPI доставки и выручка по дням. Все цифры — из OLAP
 *  (`kpi-by-channel` + `by-channel`), один источник, поэтому сходятся между собой.
 *  Доставка вынесена сюда из общих KPI, чтобы не смешивать метрики REV_GROSS и OLAP. */
export function Delivery() {
  const [sel, setSel] = useState<RangeSel>({ period: "week" });
  const [showCustom, setShowCustom] = useState(false);
  const [from, setFrom] = useState(daysAgoISO(6));
  const [to, setTo] = useState(todayISO());

  const isCustom = "from" in sel;

  const kpiQ = useQuery({
    queryKey: ["kpi-by-channel", rangeKey(sel)],
    queryFn: () => fetchKpiByChannel(sel),
    refetchInterval: REFETCH_INTERVAL_MS,
  });
  const byDayQ = useQuery({
    queryKey: ["revenue-by-channel", rangeKey(sel)],
    queryFn: () => fetchRevenueByChannel(sel),
    refetchInterval: REFETCH_INTERVAL_MS,
  });

  const pickPreset = (p: Period) => {
    setSel({ period: p });
    setShowCustom(false);
  };
  const applyCustom = () => {
    if (from && to && from <= to) setSel({ from, to });
  };

  const k = kpiQ.data;
  const totalRev = k ? k.delivery.revenue + k.other.revenue : 0;
  const totalChecks = k ? k.delivery.checks + k.other.checks : 0;
  const revShare = totalRev ? Math.round((k!.delivery.revenue / totalRev) * 1000) / 10 : 0;
  const checkShare = totalChecks ? Math.round((k!.delivery.checks / totalChecks) * 1000) / 10 : 0;

  // выручка по дням: доставка отдельно, остальное (зал + с собой) — для контекста доли
  const chartData = (byDayQ.data?.data ?? []).map((d) => {
    const delivery = Number(d[CHANNEL_DELIVERY] ?? 0);
    return {
      label: `${d.day_of_week} ${d.date.slice(5)}`,
      Доставка: delivery,
      "Не доставка": Math.max(0, d.total - delivery),
    };
  });

  const loading = kpiQ.isLoading || byDayQ.isLoading;
  const error = kpiQ.error || byDayQ.error;

  return (
    <div style={{ minHeight: "100vh", background: COLORS.bg, color: "var(--text)", padding: 24 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 12, marginBottom: 24 }}>
        <div>
          <div style={{ fontSize: 22, fontWeight: 700 }}>🛵 Доставка</div>
          <div style={{ color: COLORS.muted, fontSize: 13, marginTop: 2 }}>
            Выручка, чеки и доля доставки в продажах
          </div>
        </div>
        <div style={{ display: "flex", background: COLORS.card, borderRadius: 8, padding: 4, gap: 4 }}>
          {PERIODS.map((p) => {
            const active = !isCustom && sel.period === p.key;
            return (
              <button key={p.key} onClick={() => pickPreset(p.key)} style={tabBtn(active)}>
                {p.label}
              </button>
            );
          })}
          <button onClick={() => setShowCustom((v) => !v)} style={tabBtn(isCustom)}>
            📅 Период
          </button>
        </div>
      </div>

      {showCustom && (
        <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 16, flexWrap: "wrap" }}>
          <span style={{ color: COLORS.muted, fontSize: 13 }}>с</span>
          <input type="date" value={from} max={to} onChange={(e) => setFrom(e.target.value)} style={dateInput} />
          <span style={{ color: COLORS.muted, fontSize: 13 }}>по</span>
          <input type="date" value={to} min={from} max={todayISO()} onChange={(e) => setTo(e.target.value)} style={dateInput} />
          <button onClick={applyCustom} style={{ ...tabBtn(false), background: COLORS.primary, color: "var(--text)" }}>
            Применить
          </button>
          {isCustom && (
            <span style={{ color: COLORS.indigoText, fontSize: 13 }}>
              {sel.from} — {sel.to}
            </span>
          )}
        </div>
      )}

      {error && (
        <div style={{ background: "#2d1e1e", border: `1px solid ${COLORS.bad}`, borderRadius: 8, padding: 12, color: "#fca5a5", marginBottom: 16, fontSize: 13 }}>
          Ошибка загрузки данных. Проверьте, что backend запущен.
        </div>
      )}
      {loading && (
        <div style={{ color: COLORS.muted, textAlign: "center", padding: 48 }}>Загрузка данных...</div>
      )}

      {k && !loading && (
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 16 }}>
            <KpiCard label="Выручка доставки" value={fmtInt(k.delivery.revenue) + " ₽"} color={COLORS.primary} />
            <KpiCard label="Чеков" value={fmtInt(k.delivery.checks)} color={COLORS.warn} />
            <KpiCard label="Средний чек" value={fmtInt(k.delivery.avg_check) + " ₽"} color={COLORS.good} />
            <KpiCard
              label="Доля доставки"
              value={revShare + "%"}
              sub={`выручки · ${checkShare}% чеков`}
              color={COLORS.accent}
            />
          </div>

          <div style={{ background: "var(--card)", borderRadius: 12, padding: "20px 24px" }}>
            <div style={{ color: "var(--text)", fontWeight: 600, marginBottom: 16 }}>
              Выручка по дням: доставка и остальное
            </div>
            <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
              <BarChart data={chartData} margin={{ left: 8 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--grid)" />
                <XAxis dataKey="label" tick={{ fill: "var(--muted)", fontSize: 12 }} />
                <YAxis tickFormatter={fmtInt} tick={{ fill: "var(--muted)", fontSize: 12 }} />
                <Tooltip
                  contentStyle={{ background: "var(--bg)", border: "1px solid var(--grid)", borderRadius: 8 }}
                  labelStyle={{ color: "var(--text)" }}
                  formatter={(v, n) => [`${fmtInt(Number(v))} ₽`, n]}
                />
                <Legend wrapperStyle={{ fontSize: 12, color: "var(--muted)" }} />
                <Bar dataKey="Доставка" stackId="rev" fill={COLORS.primary} />
                <Bar dataKey="Не доставка" stackId="rev" fill="var(--grid)" />
              </BarChart>
            </ResponsiveContainer>
            {chartData.length === 0 && (
              <div style={{ color: "var(--muted)", textAlign: "center", padding: 24 }}>Нет данных за период</div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function KpiCard({ label, value, sub, color }: { label: string; value: string; sub?: string; color: string }) {
  return (
    <div
      style={{
        background: COLORS.card,
        borderRadius: 12,
        padding: "20px 24px",
        borderLeft: `4px solid ${color}`,
      }}
    >
      <div style={{ color: COLORS.muted, fontSize: 13, marginBottom: 8 }}>{label}</div>
      <div style={{ color: "var(--text)", fontSize: 24, fontWeight: 700 }}>{value}</div>
      {sub && <div style={{ color: COLORS.muted, fontSize: 12, marginTop: 6 }}>{sub}</div>}
    </div>
  );
}

const tabBtn = (active: boolean): React.CSSProperties => ({
  padding: "6px 16px", borderRadius: 6, border: "none", cursor: "pointer",
  fontSize: 13, fontWeight: 600,
  background: active ? COLORS.primary : "transparent",
  color: active ? "var(--text)" : COLORS.muted,
});

const dateInput: React.CSSProperties = {
  padding: "6px 10px", borderRadius: 8, border: `1px solid ${COLORS.grid}`,
  background: COLORS.card, color: "var(--text)", fontSize: 13,
};
