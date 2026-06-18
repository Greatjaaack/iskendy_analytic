import type { RevenueSummary } from "../api";
import { COLORS, FOODCOST_GOOD, FOODCOST_WARN } from "../constants";
import { fmtInt } from "../format";

interface Props {
  summary: RevenueSummary;
}

const foodCostColor = (pct: number) =>
  pct <= FOODCOST_GOOD ? COLORS.good : pct <= FOODCOST_WARN ? COLORS.warn : COLORS.bad;

export function KpiCards({ summary }: Props) {
  const cards = [
    { label: "Выручка", value: fmtInt(summary.total_revenue) + " ₽", color: COLORS.primary },
    { label: "Средний чек", value: fmtInt(summary.avg_check) + " ₽", color: COLORS.good },
    { label: "Чеков", value: fmtInt(summary.total_checks), color: COLORS.warn },
    { label: "Food cost", value: summary.food_cost_pct + " %", color: foodCostColor(summary.food_cost_pct) },
  ];

  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 16 }}>
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
        </div>
      ))}
    </div>
  );
}
