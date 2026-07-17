import { type RevenueSummary } from "../api";
import { COLORS } from "../constants";
import { fmtInt } from "../format";

interface Props {
  summary: RevenueSummary;
}

/** Дельта к прошлому периоду в %, либо null если сравнивать не с чем. */
const delta = (cur: number, prev: number | null): number | null =>
  prev == null || prev === 0 ? null : Math.round(((cur - prev) / prev) * 1000) / 10;

/** Верхние KPI: выручка / средний чек / чеки с дельтой к прошлому периоду.
 *  «Выручка» — ЧИСТАЯ (после комиссии агрегатора, то что реально упало в карман);
 *  средний чек и все производные считаются от неё. Под чистой — сырая выручка и
 *  размер удержания агрегатора, если доставка была. */
export function KpiCards({ summary }: Props) {
  const p = summary.prev;
  const commission = summary.aggregator_commission;

  const cards = [
    {
      label: "Выручка (чистая)",
      value: fmtInt(summary.total_revenue) + " ₽",
      color: COLORS.primary,
      delta: delta(summary.total_revenue, p.total_revenue),
      // подстрока: сырая выручка и сколько удержал агрегатор (только если была доставка)
      sub:
        commission > 0
          ? `сырая ${fmtInt(summary.gross_revenue)} ₽ · −агрегатору ${fmtInt(commission)} ₽`
          : null,
    },
    {
      label: "Средний чек",
      value: fmtInt(summary.avg_check) + " ₽",
      color: COLORS.good,
      delta: delta(summary.avg_check, p.avg_check),
      sub: null,
    },
    {
      label: "Чеков",
      value: fmtInt(summary.total_checks),
      color: COLORS.warn,
      delta: delta(summary.total_checks, p.total_checks),
      sub: null,
    },
  ];

  return (
    <div className="kpi-grid">
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
          {c.sub && (
            <div style={{ fontSize: 11, marginTop: 6, color: COLORS.muted }}>{c.sub}</div>
          )}
          {c.delta != null && (
            <div style={{ fontSize: 12, marginTop: 6, color: c.delta >= 0 ? COLORS.good : COLORS.bad }}>
              {c.delta >= 0 ? "▲" : "▼"} {Math.abs(c.delta)}%
              <span style={{ color: COLORS.muted }}> к пр. периоду</span>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
