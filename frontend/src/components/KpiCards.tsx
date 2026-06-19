import { useQuery } from "@tanstack/react-query";
import { fetchKpiByChannel, rangeKey, type ChannelKpi, type RangeSel, type RevenueSummary } from "../api";
import { COLORS, REFETCH_INTERVAL_MS } from "../constants";
import { fmtInt } from "../format";

interface Props {
  summary: RevenueSummary;
  range: RangeSel;
}

/** Дельта к прошлому периоду в %, либо null если сравнивать не с чем. */
const delta = (cur: number, prev: number | null): number | null =>
  prev == null || prev === 0 ? null : Math.round(((cur - prev) / prev) * 1000) / 10;

export function KpiCards({ summary, range }: Props) {
  const p = summary.prev;
  const chQ = useQuery({
    queryKey: ["kpi-by-channel", rangeKey(range)],
    queryFn: () => fetchKpiByChannel(range),
    refetchInterval: REFETCH_INTERVAL_MS,
  });
  const ch = chQ.data;

  const cards = [
    {
      label: "Выручка",
      value: fmtInt(summary.total_revenue) + " ₽",
      color: COLORS.primary,
      delta: delta(summary.total_revenue, p.total_revenue),
      key: "revenue" as keyof ChannelKpi,
      unit: " ₽",
    },
    {
      label: "Средний чек",
      value: fmtInt(summary.avg_check) + " ₽",
      color: COLORS.good,
      delta: delta(summary.avg_check, p.avg_check),
      key: "avg_check" as keyof ChannelKpi,
      unit: " ₽",
    },
    {
      label: "Чеков",
      value: fmtInt(summary.total_checks),
      color: COLORS.warn,
      delta: delta(summary.total_checks, p.total_checks),
      key: "checks" as keyof ChannelKpi,
      unit: "",
    },
  ];

  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16 }}>
      {cards.map((c) => (
        <div
          key={c.label}
          style={{
            background: COLORS.card,
            borderRadius: 12,
            padding: "20px 24px",
            borderLeft: `4px solid ${c.color}`,
          }}
        >
          <div style={{ color: COLORS.muted, fontSize: 13, marginBottom: 8 }}>{c.label}</div>
          <div style={{ color: "var(--text)", fontSize: 24, fontWeight: 700 }}>{c.value}</div>
          {c.delta != null && (
            <div style={{ fontSize: 12, marginTop: 6, color: c.delta >= 0 ? COLORS.good : COLORS.bad }}>
              {c.delta >= 0 ? "▲" : "▼"} {Math.abs(c.delta)}%
              <span style={{ color: COLORS.muted }}> к пр. периоду</span>
            </div>
          )}
          {ch && (
            <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginTop: 8, fontSize: 12 }}>
              <span title="Доставка (с комиссией)" style={{ color: COLORS.primary }}>
                🛵 {fmtInt(ch.delivery[c.key])}{c.unit}
              </span>
              <span title="Зал + с собой" style={{ color: "var(--muted)" }}>
                🏠 {fmtInt(ch.other[c.key])}{c.unit}
              </span>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
