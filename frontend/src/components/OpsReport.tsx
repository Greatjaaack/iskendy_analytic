import { useState } from "react";
import { useLiveQuery } from "../hooks";
import { fetchOpsReport, rangeKey, type RangeSel, type OpsCell, type OpsDaypart } from "../api";
import { COLORS, FOOD_COST_THRESHOLDS, weekdayGroup } from "../constants";
import { fmtInt } from "../format";
import { PlanEditor } from "./PlanEditor";

interface Props {
  range: RangeSel;
  withDelivery?: boolean;
}

// цвет % выполнения плана: ≥100 — зелёный, 90–99 — жёлтый, <90 — красный
const planPctColor = (v: number | null): string => {
  if (v == null) return "var(--muted)";
  if (v >= 100) return COLORS.good;
  if (v >= 90) return COLORS.warn;
  return COLORS.bad;
};

// цвет food cost %: зелёный — норма, жёлтый — пограничный, красный — высокий
const costColor = (v: number | null): string => {
  if (v == null) return "var(--muted)";
  if (v < FOOD_COST_THRESHOLDS.good) return COLORS.good;
  if (v <= FOOD_COST_THRESHOLDS.warn) return COLORS.warn;
  return COLORS.bad;
};

// метрики-подстроки под каждым дейпартом
type MetricKey = "revenue" | "avg_check" | "guests" | "food_cost_pct";
const METRICS: { key: MetricKey; label: string }[] = [
  { key: "revenue", label: "Выручка" },
  { key: "avg_check", label: "Ср. чек" },
  { key: "guests", label: "Гости" },
  { key: "food_cost_pct", label: "Кост %" },
];

function cellText(c: OpsCell | undefined, m: MetricKey): string {
  if (!c) return "—";
  if (m === "revenue") return c.revenue ? fmtInt(c.revenue) : "—";
  if (m === "avg_check") return c.avg_check ? fmtInt(c.avg_check) : "—";
  if (m === "guests") return c.guests ? String(c.guests) : "—";
  return c.food_cost_pct == null ? "—" : `${c.food_cost_pct}%`;
}

const COL_DAYPART = 96; // ширина липкой колонки «Дейпарт»
const COL_METRIC = 84; // ширина липкой колонки «Метрика»
const TH: React.CSSProperties = { padding: "8px 10px", fontWeight: 500, fontSize: 12, whiteSpace: "nowrap" };
const TD: React.CSSProperties = { padding: "8px 10px", fontSize: 13, textAlign: "right", fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap", minWidth: 44 };
// липкие левые колонки (дейпарт + метрика) — не уезжают при горизонтальной прокрутке.
// zIndex: дейпарт (рамка-угол) выше метрики, обе выше ячеек дней.
const stick = (left: number, width: number, z = 2): React.CSSProperties => ({
  position: "sticky", left, width, minWidth: width, maxWidth: width,
  background: "var(--card)", zIndex: z,
});

/**
 * Ежедневный операционный отчёт (аналог Excel-свода «ОП»): дни месяца по горизонтали,
 * дейпарты по вертикали, под каждым — Выручка / Ср. чек / Гости / Кост %. Справа —
 * Факт за период, Среднее на активный день, доля % дейпарта. Источник —
 * `/api/revenue/ops-report`. Реагирует на галку «С доставкой».
 */
export function OpsReport({ range, withDelivery = true }: Props) {
  const q = useLiveQuery({
    queryKey: ["ops-report", rangeKey(range), withDelivery],
    queryFn: () => fetchOpsReport(range, withDelivery),
  });

  const d = q.data;
  const days = d?.days ?? [];
  const [planOpen, setPlanOpen] = useState(false);
  const ready = !q.isLoading && days.length > 0;
  const hasPlan = !!d?.has_plan;

  // значение метрики в правых колонках (Факт / Среднее)
  const sumVal = (dp: OpsDaypart, m: MetricKey): string => cellText(dp.total, m);
  const avgVal = (dp: OpsDaypart, m: MetricKey): string => {
    if (m === "food_cost_pct") return dp.total.food_cost_pct == null ? "—" : `${dp.total.food_cost_pct}%`;
    const a = dp.avg_per_day;
    const v = m === "revenue" ? a.revenue : m === "avg_check" ? a.avg_check : a.guests;
    return v ? (m === "guests" ? String(Math.round(v)) : fmtInt(v)) : "—";
  };
  // план/факт: план есть только у метрик revenue/avg_check/guests (не у кост%)
  const planVal = (p: { revenue: number; avg_check: number; guests: number }, m: MetricKey): string => {
    if (m === "food_cost_pct") return "";
    const v = m === "revenue" ? p.revenue : m === "avg_check" ? p.avg_check : p.guests;
    return v ? (m === "guests" ? String(Math.round(v)) : fmtInt(v)) : "—";
  };
  const pctVal = (pp: { revenue: number | null; avg_check: number | null; guests: number | null }, m: MetricKey): number | null =>
    m === "food_cost_pct" ? null : m === "revenue" ? pp.revenue : m === "avg_check" ? pp.avg_check : pp.guests;

  return (
    <div style={{ background: "var(--card)", borderRadius: 12, padding: "20px 24px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", flexWrap: "wrap", gap: 8, marginBottom: 4 }}>
        <div style={{ color: "var(--text)", fontWeight: 600 }}>Ежедневный отчёт по дейпартам</div>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          {d && <div style={{ color: "var(--muted)", fontSize: 12 }}>{d.date_from} — {d.date_to}</div>}
          <button
            onClick={() => setPlanOpen(true)}
            style={{ background: "transparent", color: "var(--text)", border: "1px solid var(--grid)", borderRadius: 6, padding: "4px 12px", fontSize: 12, cursor: "pointer" }}
          >
            План
          </button>
        </div>
      </div>
      {planOpen && <PlanEditor onClose={() => setPlanOpen(false)} />}
      <div style={{ color: "var(--muted)", fontSize: 12, marginBottom: 14 }}>
        Дни по горизонтали, дейпарты по вертикали. Под каждым окном — выручка, средний чек, гости и кост % (iiko-с/с ÷ выручка окна).
      </div>

      {ready && (
        <div style={{ overflowX: "auto" }}>
          <table style={{ borderCollapse: "collapse", fontVariantNumeric: "tabular-nums", minWidth: "100%" }}>
            <thead>
              <tr style={{ color: "var(--muted)" }}>
                <th style={{ ...TH, ...stick(0, COL_DAYPART), textAlign: "left" }}>Дейпарт</th>
                <th style={{ ...TH, ...stick(COL_DAYPART, COL_METRIC, 1), textAlign: "left" }}>Метрика</th>
                {days.map((day) => (
                  <th key={day.date} style={{ ...TH, textAlign: "right", color: weekdayGroup(day.weekday).color }}>
                    <div>{day.dom}</div>
                    <div style={{ fontSize: 10, fontWeight: 400 }}>{day.weekday}</div>
                  </th>
                ))}
                <th style={{ ...TH, textAlign: "right", color: "var(--text)", borderLeft: "2px solid var(--grid)" }}>Факт</th>
                {hasPlan && <th style={{ ...TH, textAlign: "right" }}>План</th>}
                {hasPlan && <th style={{ ...TH, textAlign: "right" }}>% плана</th>}
                <th style={{ ...TH, textAlign: "right" }}>Среднее</th>
                <th style={{ ...TH, textAlign: "right" }}>Доля</th>
              </tr>
            </thead>
            <tbody>
              {d!.dayparts.map((dp) => (
                METRICS.map((metric, mi) => (
                  <tr key={`${dp.key}-${metric.key}`} style={{ borderTop: mi === 0 ? "1px solid var(--grid)" : undefined }}>
                    {mi === 0 && (
                      <td rowSpan={METRICS.length} style={{ ...TD, ...stick(0, COL_DAYPART), textAlign: "left", verticalAlign: "top", color: "var(--text)", fontWeight: 600 }}>
                        {dp.label}
                        <div style={{ color: "var(--muted)", fontSize: 10, fontWeight: 400 }}>{dp.range}</div>
                      </td>
                    )}
                    <td style={{ ...TD, ...stick(COL_DAYPART, COL_METRIC, 1), textAlign: "left", color: "var(--muted)" }}>{metric.label}</td>
                    {days.map((day) => {
                      const c = dp.cells[day.date];
                      const txt = cellText(c, metric.key);
                      const col = metric.key === "food_cost_pct" ? costColor(c?.food_cost_pct ?? null)
                        : metric.key === "revenue" ? "var(--text)" : "var(--muted)";
                      return <td key={day.date} style={{ ...TD, color: txt === "—" ? "var(--grid)" : col }}>{txt}</td>;
                    })}
                    <td style={{ ...TD, color: metric.key === "food_cost_pct" ? costColor(dp.total.food_cost_pct) : "var(--text)", fontWeight: 600, borderLeft: "2px solid var(--grid)" }}>{sumVal(dp, metric.key)}</td>
                    {hasPlan && <td style={{ ...TD, color: "var(--muted)" }}>{planVal(dp.plan, metric.key)}</td>}
                    {hasPlan && (() => {
                      const pp = pctVal(dp.plan_pct, metric.key);
                      return <td style={{ ...TD, color: planPctColor(pp) }}>{pp == null ? "" : `${pp}%`}</td>;
                    })()}
                    <td style={{ ...TD, color: "var(--muted)" }}>{avgVal(dp, metric.key)}</td>
                    <td style={{ ...TD, color: "var(--muted)" }}>{metric.key === "revenue" ? `${dp.revenue_share}%` : ""}</td>
                  </tr>
                ))
              ))}
              {/* Итого по дню */}
              <tr style={{ borderTop: "2px solid var(--grid)" }}>
                <td colSpan={2} style={{ ...TD, ...stick(0, COL_DAYPART + COL_METRIC), textAlign: "left", color: "var(--text)", fontWeight: 700 }}>Итого выручка</td>
                {days.map((day) => {
                  const c = d!.totals.cells[day.date];
                  return <td key={day.date} style={{ ...TD, color: c ? "var(--text)" : "var(--grid)", fontWeight: 600 }}>{c ? fmtInt(c.revenue) : "—"}</td>;
                })}
                <td style={{ ...TD, color: "var(--text)", fontWeight: 700, borderLeft: "2px solid var(--grid)" }}>{fmtInt(d!.totals.total.revenue)}</td>
                {hasPlan && <td style={{ ...TD, color: "var(--muted)" }}>{fmtInt(d!.totals.plan.revenue)}</td>}
                {hasPlan && (
                  <td style={{ ...TD, color: planPctColor(d!.totals.plan_pct.revenue), fontWeight: 700 }}>
                    {d!.totals.plan_pct.revenue == null ? "" : `${d!.totals.plan_pct.revenue}%`}
                  </td>
                )}
                <td style={{ ...TD, color: "var(--muted)" }}>{fmtInt(d!.totals.avg_per_day.revenue)}</td>
                <td style={{ ...TD }} />
              </tr>
            </tbody>
          </table>
        </div>
      )}

      {/* нижний блок: food cost % по дейпартам × группам категорий (Еда/Напитки/…) */}
      {ready && d!.category_groups.length > 0 && (
        <div style={{ marginTop: 22 }}>
          <div style={{ color: "var(--text)", fontWeight: 600, marginBottom: 10 }}>Food cost % по дейпартам и категориям</div>
          <table style={{ borderCollapse: "collapse", fontVariantNumeric: "tabular-nums", width: "100%" }}>
            <thead>
              <tr style={{ color: "var(--muted)" }}>
                <th style={{ ...TH, textAlign: "left", minWidth: 110 }}>Дейпарт</th>
                {d!.category_groups.map((g) => (
                  <th key={g} style={{ ...TH, textAlign: "right", minWidth: 96 }}>{g}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {d!.dayparts.map((dp) => (
                <tr key={dp.key} style={{ borderTop: "1px solid var(--grid)" }}>
                  <td style={{ ...TD, textAlign: "left", color: "var(--text)" }}>{dp.label}</td>
                  {d!.category_groups.map((g) => {
                    const c = dp.categories[g];
                    if (!c || c.food_cost_pct == null)
                      return <td key={g} style={{ ...TD, color: "var(--grid)" }}>—</td>;
                    return (
                      <td key={g} style={{ ...TD, color: costColor(c.food_cost_pct) }}
                        title={`Выручка ${fmtInt(c.revenue)} ₽ · покрыто костом ${c.coverage}%`}>
                        {c.food_cost_pct}%
                      </td>
                    );
                  })}
                </tr>
              ))}
              <tr style={{ borderTop: "2px solid var(--grid)" }}>
                <td style={{ ...TD, textAlign: "left", color: "var(--text)", fontWeight: 700 }}>Итого</td>
                {d!.category_groups.map((g) => {
                  const c = d!.category_totals[g];
                  return (
                    <td key={g} style={{ ...TD, color: costColor(c?.food_cost_pct ?? null), fontWeight: 700 }}
                      title={c ? `Выручка ${fmtInt(c.revenue)} ₽ · доля ${c.revenue_share}% · покрыто костом ${c.coverage}%` : ""}>
                      {c && c.food_cost_pct != null ? `${c.food_cost_pct}%` : "—"}
                    </td>
                  );
                })}
              </tr>
            </tbody>
          </table>
          <div style={{ color: "var(--muted)", fontSize: 11, marginTop: 8 }}>
            Кост % = iiko-с/с (ProductCostBase) ÷ выручка окна. «Покрыто костом» — доля выручки с известной с/с (ниже 100% там, где у позиции нет коста в iiko, напр. доставочные дубли). Наведите на ячейку.
          </div>
        </div>
      )}

      {!q.isLoading && !ready && (
        <div style={{ color: "var(--muted)", textAlign: "center", padding: 24 }}>Нет данных</div>
      )}
    </div>
  );
}
