import { Fragment, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

import type {
  Period, RangeSel, PnlLine, PnlRating, PnlSection, PnlBreakeven, PnlDay, PnlDayKey, PnlDayCostRow,
} from "../api";
import { fetchPnl, fetchPnlCosts, savePnlCosts, fetchPnlDayCosts, savePnlDayCosts, importPnlSheet, rangeKey } from "../api";
import { fmtInt } from "../format";
import { COLORS, PERIODS, weekdayGroup } from "../constants";

const todayISO = () => new Date().toISOString().slice(0, 10);
const fmtRub = (n: number | undefined) => `${fmtInt(n ?? 0)} ₽`;

/** Цвет бенчмарка строки. */
const rateColor = (r: PnlRating): string | null =>
  r === "green" ? COLORS.good : r === "yellow" ? COLORS.warn : r === "red" ? COLORS.bad : null;

/** Значение метрики (не-денежной строки) в человекочитаемом виде. */
function fmtMetric(l: PnlLine): string {
  const v = l.value ?? 0;
  if (l.unit === "rub") return fmtRub(v);
  if (l.unit === "num") return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 1 }).format(v);
  return String(v);
}

/** Дельта в % между текущим и сопоставимым значением пред. периода (тот же день недели).
 *  Знаменатель — |prev|: направление берём по (cur − prev), иначе при отрицательной базе
 *  (EBITDA у точки отрицательна каждый месяц) знак стрелки инвертируется — рост убытка
 *  показывался бы зелёной ▲. Теперь cur > prev → «+» (лучше), cur < prev → «−» (хуже). */
const delta = (cur: number, prev: number | null | undefined): number | null =>
  prev == null || prev === 0 ? null : Math.round(((cur - prev) / Math.abs(prev)) * 1000) / 10;

function DeltaBadge({ d }: { d: number | null }) {
  if (d == null) return null;
  return (
    <span style={{ fontSize: 11, color: d >= 0 ? COLORS.good : COLORS.bad, marginLeft: 6 }}>
      {d >= 0 ? "▲" : "▼"}{Math.abs(d)}%
    </span>
  );
}

export function Pnl() {
  const qc = useQueryClient();
  const [sel, setSel] = useState<RangeSel>({ period: "month" });
  const [showCustom, setShowCustom] = useState(false);
  const [from, setFrom] = useState(todayISO());
  const [to, setTo] = useState(todayISO());
  const [editing, setEditing] = useState(false);
  const [dayEditing, setDayEditing] = useState(false);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [importMsg, setImportMsg] = useState<string | null>(null);

  const isCustom = "from" in sel;

  const pnlQ = useQuery({
    queryKey: ["pnl", rangeKey(sel)],
    queryFn: () => fetchPnl(sel),
  });

  const importMut = useMutation({
    mutationFn: importPnlSheet,
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["pnl"] });
      qc.invalidateQueries({ queryKey: ["pnlCosts"] });
      setImportMsg(`Загружено месяцев: ${r.months}. Пропущено без данных: ${r.skipped.length}.`);
    },
    onError: () => setImportMsg("Не удалось прочитать таблицу — проверь доступ «по ссылке»."),
  });

  const pickPreset = (p: Period) => {
    setSel({ period: p });
    setShowCustom(false);
  };
  const applyCustom = () => {
    if (from && to && from <= to) setSel({ from, to });
  };
  const toggleSection = (key: string) =>
    setCollapsed((s) => {
      const next = new Set(s);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  const data = pnlQ.data;
  const ps = data?.prev_summary;

  return (
    <div className="page" style={{ minHeight: "100vh", background: COLORS.bg, color: "var(--text)" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 12, marginBottom: 24 }}>
        <div style={{ fontSize: 22, fontWeight: 700 }}>P&L дня</div>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
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
              Период
            </button>
          </div>
          <button
            onClick={() => { setImportMsg(null); importMut.mutate(); }}
            disabled={importMut.isPending}
            style={{ ...tabBtn(false), border: `1px solid ${COLORS.grid}` }}
            title="Тянет помесячные затраты из твоей Google-таблицы P&L"
          >
            {importMut.isPending ? "Обновляю…" : "Обновить из таблицы"}
          </button>
          <button onClick={() => setDayEditing(true)} style={{ ...tabBtn(false), border: `1px solid ${COLORS.grid}` }}>
            Затраты по дням
          </button>
          <button onClick={() => setEditing(true)} style={{ ...tabBtn(false), border: `1px solid ${COLORS.grid}` }}>
            Затраты за месяц
          </button>
        </div>
      </div>

      {importMsg && (
        <div style={{ background: COLORS.card, border: `1px solid ${COLORS.grid}`, borderRadius: 8, padding: "8px 14px", color: COLORS.muted, fontSize: 13, marginBottom: 16 }}>
          {importMsg}
        </div>
      )}

      {showCustom && (
        <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 16, flexWrap: "wrap" }}>
          <span style={{ color: COLORS.muted, fontSize: 13 }}>с</span>
          <input type="date" value={from} max={to} onChange={(e) => setFrom(e.target.value)} style={dateInput} />
          <span style={{ color: COLORS.muted, fontSize: 13 }}>по</span>
          <input type="date" value={to} min={from} max={todayISO()} onChange={(e) => setTo(e.target.value)} style={dateInput} />
          <button onClick={applyCustom} style={{ ...tabBtn(false), background: COLORS.primary, color: "var(--text)" }}>
            Применить
          </button>
        </div>
      )}

      {pnlQ.isLoading && <div style={{ color: COLORS.muted }}>Загрузка…</div>}
      {pnlQ.error && (
        <div style={{ background: "#2d1e1e", border: `1px solid ${COLORS.bad}`, borderRadius: 8, padding: 12, color: "#fca5a5", fontSize: 13 }}>
          Не удалось загрузить P&L
        </div>
      )}

      {data && (
        <>
          {!data.has_costs && (
            <div style={{ background: COLORS.card, border: `1px solid ${COLORS.warn}`, borderRadius: 8, padding: "10px 14px", color: COLORS.warn, fontSize: 13, marginBottom: 16 }}>
              Затраты за этот период ещё не введены — заполните их через «Затраты за месяц» (аренда, ФОТ…) и «Затраты по дням» (списания, упаковка, химия), иначе видно только выручку и food cost.
            </div>
          )}

          {/* Хедер: EBITDA + вердикт по безубыточности */}
          <div style={{ display: "flex", gap: 24, flexWrap: "wrap", alignItems: "flex-end", marginBottom: 16 }}>
            <div>
              <div style={{ color: COLORS.muted, fontSize: 12 }}>EBITDA за период · {data.date_from} — {data.date_to}</div>
              <div style={{ fontSize: 30, fontWeight: 800, color: data.ebitda >= 0 ? COLORS.good : COLORS.bad, marginTop: 2 }}>
                {fmtRub(data.ebitda)} <span style={{ fontSize: 16, fontWeight: 600, color: rateColor(data.ebitda_rating) ?? COLORS.muted }}>({data.ebitda_margin}%)</span>
                {ps && <DeltaBadge d={delta(data.ebitda, ps.ebitda)} />}
              </div>
              {ps && (
                <div style={{ fontSize: 11, color: COLORS.muted, marginTop: 2 }}>
                  vs {ps.date_from} — {ps.date_to} (тот же день недели): {fmtRub(ps.ebitda)}
                </div>
              )}
            </div>
            <BreakevenVerdict be={data.breakeven} />
          </div>

          {/* Подневный P&L — главный вид: дни × все статьи (только период дольше дня) */}
          {data.daily.length > 1 && <DailyMatrix days={data.daily} />}

          {/* Единая таблица P&L (итог за период) — узкая, число рядом с названием (#2) */}
          <div style={{ maxWidth: 560, marginTop: 20 }}>
            <div style={{ color: COLORS.muted, fontSize: 12, marginBottom: 6 }}>Итог за период — с бенчмарками</div>
            <div style={{ background: COLORS.card, borderRadius: 12, border: `1px solid ${COLORS.grid}`, overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
                <thead>
                  <tr style={{ color: COLORS.muted, fontSize: 11, textTransform: "uppercase", letterSpacing: 0.4 }}>
                    <th style={{ textAlign: "left", padding: "10px 14px", fontWeight: 500 }}>Показатель</th>
                    <th style={{ textAlign: "right", padding: "10px 14px", fontWeight: 500 }}>₽</th>
                    <th style={{ textAlign: "right", padding: "10px 14px", fontWeight: 500, width: 64 }}>% выр.</th>
                  </tr>
                </thead>
                <tbody>
                  {data.sections.map((s) => (
                    <SectionRows key={s.key} section={s} collapsed={collapsed.has(s.key)} onToggle={() => toggleSection(s.key)} />
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}

      {editing && <CostEditor onClose={() => setEditing(false)} />}
      {dayEditing && <DayCostEditor onClose={() => setDayEditing(false)} />}
    </div>
  );
}

// Строки-подытоги (жирные, с рамкой) — ключевые агрегаты P&L.
const SUBTOTAL = new Set([
  "revenue", "cogs", "prime_cost", "production_cost", "total_opex",
  "contribution_margin", "fixed_alloc", "all_expenses", "ebitda",
]);

/** Секция единой таблицы: сворачиваемый заголовок + строки показателей. */
function SectionRows({ section, collapsed, onToggle }: { section: PnlSection; collapsed: boolean; onToggle: () => void }) {
  return (
    <>
      <tr>
        <td
          colSpan={3}
          onClick={onToggle}
          style={{
            padding: "9px 14px 5px", fontSize: 12, fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.4,
            color: COLORS.indigoText, background: COLORS.bg, borderTop: `1px solid ${COLORS.grid}`,
            cursor: "pointer", userSelect: "none",
          }}
        >
          <span style={{ display: "inline-block", transition: "transform 0.15s", transform: collapsed ? "rotate(-90deg)" : "none", marginRight: 6 }}>
            ▾
          </span>
          {section.label}
        </td>
      </tr>
      {!collapsed && section.lines.map((l) => {
        const rc = rateColor(l.rating);
        const isMoney = l.kind === "money";
        const sub = SUBTOTAL.has(l.key);
        const indent = l.label.startsWith("—");
        return (
          <tr key={l.key} style={{ borderTop: `1px solid ${COLORS.grid}`, background: sub ? "rgba(99,102,241,0.06)" : "transparent" }}>
            <td style={{ padding: "7px 14px", paddingLeft: indent ? 26 : 14, color: sub ? "var(--text)" : COLORS.muted, fontWeight: sub ? 700 : 400 }}>
              {l.label}
            </td>
            <td style={{ padding: "7px 14px", textAlign: "right", fontWeight: sub ? 800 : 500, fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap", color: isMoney ? "var(--text)" : (rc ?? "var(--text)") }}>
              {isMoney ? fmtRub(l.rub) : fmtMetric(l)}
            </td>
            <td style={{ padding: "7px 14px", textAlign: "right", fontVariantNumeric: "tabular-nums", color: rc ?? COLORS.muted, fontWeight: rc ? 700 : 400, whiteSpace: "nowrap" }}>
              {isMoney ? `${l.pct}%` : ""}
            </td>
          </tr>
        );
      })}
    </>
  );
}

/** Вердикт по безубыточности рядом с EBITDA. */
function BreakevenVerdict({ be }: { be: PnlBreakeven }) {
  if (be.revenue_day == null) {
    return (
      <div style={{ fontSize: 13, color: COLORS.muted }}>
        Точка безубыточности: <b>—</b>
        <div style={{ fontSize: 12 }}>{be.cm_ratio <= 0 ? "маржинальность ≤ 0 — не окупается ни при каком объёме" : "введите постоянные затраты"}</div>
      </div>
    );
  }
  const gap = be.avg_rev_day - be.revenue_day; // + запас, − недобор
  const ok = gap >= 0;
  return (
    <div style={{ fontSize: 13, color: COLORS.muted }}>
      <div>
        Точка безубыточности: <b style={{ color: "var(--text)" }}>{fmtRub(be.revenue_month ?? 0)}/мес</b> · {fmtRub(be.revenue_day)}/сутки
        <span style={{ color: COLORS.muted }}> (маржинальность {be.cm_ratio}%)</span>
      </div>
      <div style={{ marginTop: 2 }}>
        Средний день делает <b style={{ color: "var(--text)" }}>{fmtRub(be.avg_rev_day)}</b> →{" "}
        <b style={{ color: ok ? COLORS.good : COLORS.bad }}>
          {ok ? `запас +${fmtRub(gap)}/сутки` : `недобор ${fmtRub(gap)}/сутки`}
        </b>
      </div>
    </div>
  );
}

// ─── Подневная матрица (#1, #3): дни по горизонтали, ВСЕ статьи P&L по вертикали ──
type MatrixRow = {
  key: PnlDayKey;
  label: string;
  indent?: boolean;   // подстрока (Зал/Доставка)
  strong?: boolean;   // подытог/итог
  profit?: boolean;   // EBITDA — красим по знаку
  variable?: boolean; // дневная переменная статья — ловим всплеск
};
type MatrixGroup = { title: string; rows: MatrixRow[] };

const MATRIX: MatrixGroup[] = [
  { title: "Выручка", rows: [
    { key: "revenue", label: "Выручка", strong: true },
    { key: "revenue_hall", label: "Зал", indent: true },
    { key: "revenue_delivery", label: "Доставка", indent: true },
    { key: "agg_revenue", label: "Через агрегатора", indent: true },
  ] },
  { title: "Себестоимость (COGS)", rows: [
    { key: "food_cost", label: "Food cost" },
    { key: "writeoffs", label: "Списания", variable: true },
    { key: "packaging", label: "Упаковка", variable: true },
    { key: "cogs", label: "Итого COGS", strong: true },
  ] },
  { title: "ФОТ", rows: [
    { key: "labor", label: "ФОТ (операционный)" },
    { key: "admin_fot", label: "Админ. ФОТ (управляющий)" },
  ] },
  { title: "Операционные расходы", rows: [
    { key: "chemicals", label: "Химия / моющие", variable: true },
    { key: "supplies", label: "Расходники", variable: true },
    { key: "rent", label: "Аренда" },
    { key: "utilities", label: "Коммуналка" },
    { key: "other_opex", label: "Прочие (IT/ОФД/эквайр/аморт)" },
    { key: "contingency", label: "Непредвиденные" },
    { key: "cap_reserve", label: "Кап-резерв" },
    { key: "tax", label: "Налог (УСН)" },
    { key: "aggregator", label: "Агрегатор" },
  ] },
  { title: "Результат", rows: [
    { key: "total_expenses", label: "Все расходы (без марк.)", strong: true },
    { key: "ebitda", label: "EBITDA (без маркетинга)", strong: true, profit: true },
  ] },
];

const COL_METRIC = 150;
const mTH: React.CSSProperties = { padding: "5px 7px", fontWeight: 500, fontSize: 11, whiteSpace: "nowrap" };
const mTD: React.CSSProperties = { padding: "4px 7px", fontSize: 12, textAlign: "right", fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap" };
const stickCol = (z = 1): React.CSSProperties => ({
  position: "sticky", left: 0, width: COL_METRIC, minWidth: COL_METRIC, maxWidth: COL_METRIC,
  background: "var(--card)", zIndex: z,
});

function DailyMatrix({ days }: { days: PnlDay[] }) {
  // какой показатель крупный и цветной: абсолют (₽) или относительный (% выручки)
  const [emph, setEmph] = useState<"rub" | "pct">("rub");
  const periodRev = days.reduce((s, d) => s + d.revenue, 0);
  const activeDays = days.filter((d) => d.revenue > 0).length || 1;

  // среднесуточная сумма переменной статьи — база для детекции всплеска
  const mean: Partial<Record<PnlDayKey, number>> = {};
  MATRIX.forEach((g) => g.rows.forEach((r) => {
    if (r.variable) {
      const sum = days.reduce((s, d) => s + (d[r.key] as number), 0);
      mean[r.key] = sum / activeDays;
    }
  }));

  const sumOf = (k: PnlDayKey) => days.reduce((s, d) => s + (d[k] as number), 0);

  // всплеск: дневное значение статьи заметно выше её же среднесуточного
  const isSpike = (r: MatrixRow, v: number): boolean =>
    !!r.variable && v > 0 && (mean[r.key] ?? 0) > 0 && v >= (mean[r.key] as number) * 1.75;

  return (
    <div style={{ background: COLORS.card, borderRadius: 12, padding: "20px 24px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", flexWrap: "wrap", gap: 8, marginBottom: 4 }}>
        <div style={{ color: "var(--text)", fontWeight: 600 }}>Подневный P&L — все статьи</div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ color: COLORS.muted, fontSize: 12 }}>Крупно:</span>
          <div style={{ display: "flex", background: COLORS.bg, borderRadius: 8, padding: 3, gap: 3 }}>
            {(["rub", "pct"] as const).map((m) => (
              <button key={m} onClick={() => setEmph(m)} style={{ ...tabBtn(emph === m), fontSize: 12, padding: "4px 12px" }}>
                {m === "rub" ? "₽" : "% выручки"}
              </button>
            ))}
          </div>
        </div>
      </div>
      <div style={{ color: COLORS.muted, fontSize: 12, marginBottom: 14 }}>
        Дни по горизонтали, статьи расходов по вертикали. В клетке — <b style={{ color: "var(--text)" }}>₽ за день</b> и <b style={{ color: "var(--text)" }}>доля от выручки дня</b>; тумблер «Крупно» выбирает, что крупнее и цветом. Справа — Факт за период, Среднее на активный день и доля от выручки.
        Переменные статьи (списания, упаковка, химия, расходники) вводятся по дням — <b style={{ color: COLORS.warn }}>всплеск</b> выше нормы подсвечен. Маркетинг не разносится по дням (учтён в EBITDA за период сверху), поэтому EBITDA в матрице — «без маркетинга» и выше итоговой ровно на сумму маркетинга. Комиссия агрегатора — от фактической выручки через агрегатора.
      </div>
      <div style={{ overflowX: "auto" }}>
        <table style={{ borderCollapse: "collapse", minWidth: "100%", fontVariantNumeric: "tabular-nums" }}>
          <thead>
            <tr style={{ color: COLORS.muted }}>
              <th style={{ ...mTH, ...stickCol(2), textAlign: "left" }}>Статья</th>
              {days.map((day) => (
                <th key={day.date} style={{ ...mTH, textAlign: "right", color: weekdayGroup(day.day_of_week).color }}>
                  <div>{day.date.slice(8, 10)}.{day.date.slice(5, 7)}</div>
                  <div style={{ fontSize: 9, fontWeight: 400 }}>{day.day_of_week}</div>
                </th>
              ))}
              <th style={{ ...mTH, textAlign: "right", color: "var(--text)", borderLeft: "2px solid var(--grid)" }}>Факт</th>
              <th style={{ ...mTH, textAlign: "right" }}>Среднее</th>
              <th style={{ ...mTH, textAlign: "right" }}>Доля</th>
            </tr>
          </thead>
          <tbody>
            {MATRIX.map((g) => (
              <Fragment key={g.title}>
                <tr>
                  <td colSpan={days.length + 4} style={{ padding: "7px 7px 3px", fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.4, color: COLORS.indigoText, background: COLORS.bg }}>
                    {g.title}
                  </td>
                </tr>
                {g.rows.map((r) => {
                  const sum = sumOf(r.key);
                  const avg = sum / activeDays;
                  const share = periodRev ? Math.round((sum / periodRev) * 1000) / 10 : 0;
                  return (
                    <tr key={r.key} style={{ borderTop: `1px solid ${COLORS.grid}` }}>
                      <td style={{ ...mTD, ...stickCol(1), textAlign: "left", paddingLeft: r.indent ? 20 : 7, color: r.indent ? COLORS.muted : "var(--text)", fontWeight: r.strong ? 700 : r.indent ? 400 : 500 }}>
                        {r.label}
                      </td>
                      {days.map((day) => {
                        const v = day[r.key] as number;
                        const spike = isSpike(r, v);
                        // цвет КРУПНОГО значения: прибыль — по знаку, всплеск — красный,
                        // ноль — бледный, иначе полный цвет текста (а не серый — чтобы выделялось)
                        const primaryColor = r.profit ? (v >= 0 ? COLORS.good : COLORS.bad)
                          : spike ? COLORS.bad
                          : v === 0 ? "var(--grid)"
                          : "var(--text)";
                        const pctv = day.revenue ? Math.round((v / day.revenue) * 1000) / 10 : null;
                        const rubStr = v ? fmtInt(v) : "—";
                        const pctStr = r.key !== "revenue" && pctv != null && v !== 0 ? `${pctv}%` : null;
                        // крупный+цветной = выбранный тумблером; второй — мелкий серый под ним
                        const bigIsRub = emph === "rub" || !pctStr;
                        const primary = bigIsRub ? rubStr : (pctStr as string);
                        const secondary = bigIsRub ? pctStr : rubStr;
                        return (
                          <td
                            key={day.date}
                            title={spike ? `Всплеск: ${fmtRub(v)} при норме ~${fmtRub(mean[r.key])}` : undefined}
                            style={{ ...mTD, padding: "5px 8px", background: spike ? "rgba(239,68,68,0.12)" : undefined }}
                          >
                            <div style={{ fontSize: 14, fontWeight: r.strong || spike ? 800 : 600, color: primaryColor, lineHeight: 1.15 }}>
                              {primary}
                            </div>
                            {secondary && (
                              <div style={{ fontSize: 10, fontWeight: 400, color: COLORS.muted }}>{secondary}</div>
                            )}
                          </td>
                        );
                      })}
                      <td style={{ ...mTD, color: r.profit ? (sum >= 0 ? COLORS.good : COLORS.bad) : "var(--text)", fontWeight: 700, borderLeft: "2px solid var(--grid)" }}>
                        {sum ? fmtInt(sum) : "—"}
                      </td>
                      <td style={{ ...mTD, color: COLORS.muted }}>{avg ? fmtInt(avg) : "—"}</td>
                      <td style={{ ...mTD, color: COLORS.muted }}>
                        {r.key === "revenue" ? "" : periodRev ? `${share}%` : "—"}
                      </td>
                    </tr>
                  );
                })}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** Модалка ввода помесячных затрат (постоянные: аренда, ФОТ, маркетинг…). */
function CostEditor({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const now = new Date();
  const [year, setYear] = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth() + 1);
  const [draft, setDraft] = useState<Record<string, number>>({});

  const costsQ = useQuery({
    queryKey: ["pnlCosts", year, month],
    queryFn: () => fetchPnlCosts(year, month),
  });

  // при загрузке/смене месяца — подставляем сохранённые значения в форму
  const loadedKey = `${year}-${month}`;
  const [syncedKey, setSyncedKey] = useState("");
  if (costsQ.data && syncedKey !== loadedKey) {
    setDraft({ ...costsQ.data.values });
    setSyncedKey(loadedKey);
  }

  const saveMut = useMutation({
    mutationFn: () => savePnlCosts({ ...draft, year, month }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["pnl"] });
      qc.invalidateQueries({ queryKey: ["pnlCosts"] });
      onClose();
    },
  });

  const set = (k: string, v: string) => setDraft((d) => ({ ...d, [k]: Number(v) || 0 }));

  const MONTHS = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"];

  return (
    <div onClick={onClose} style={modalBackdrop}>
      <div onClick={(e) => e.stopPropagation()} style={{ background: COLORS.card, borderRadius: 12, padding: 24, width: 460, maxWidth: "100%", border: `1px solid ${COLORS.grid}` }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
          <div style={{ fontSize: 17, fontWeight: 700 }}>Затраты за месяц</div>
          <button onClick={onClose} style={{ ...tabBtn(false), border: `1px solid ${COLORS.grid}` }}>✕</button>
        </div>

        <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
          <select value={month} onChange={(e) => setMonth(Number(e.target.value))} style={dateInput}>
            {MONTHS.map((m, i) => <option key={i} value={i + 1}>{m}</option>)}
          </select>
          <select value={year} onChange={(e) => setYear(Number(e.target.value))} style={dateInput}>
            {[now.getFullYear() - 1, now.getFullYear()].map((y) => <option key={y} value={y}>{y}</option>)}
          </select>
        </div>

        {costsQ.isLoading && <div style={{ color: COLORS.muted, fontSize: 13 }}>Загрузка…</div>}
        {costsQ.data && (
          <>
            <div style={{ fontSize: 12, color: COLORS.muted, marginBottom: 8 }}>Постоянные суммы за месяц, ₽ (делятся на дни месяца). Списания/упаковка теперь вводятся по дням — тут это резерв на дни без ввода.</div>
            {costsQ.data.manual_fields.map((f) => (
              <Field key={f.key} label={f.label} value={draft[f.key] ?? 0} onChange={(v) => set(f.key, v)} />
            ))}
            <div style={{ fontSize: 12, color: COLORS.muted, margin: "14px 0 8px" }}>Ставки и конфиг</div>
            {costsQ.data.rate_fields.map((f) => (
              <Field key={f.key} label={f.label} value={draft[f.key] ?? 0} onChange={(v) => set(f.key, v)} />
            ))}

            <button
              onClick={() => saveMut.mutate()}
              disabled={saveMut.isPending}
              style={saveBtn}
            >
              {saveMut.isPending ? "Сохранение…" : "Сохранить"}
            </button>
          </>
        )}
      </div>
    </div>
  );
}

/** Модалка ввода ДНЕВНЫХ переменных затрат: месяц → сетка дни×статьи. */
function DayCostEditor({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const now = new Date();
  const [year, setYear] = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth() + 1);
  const [rows, setRows] = useState<PnlDayCostRow[]>([]);

  const df = `${year}-${String(month).padStart(2, "0")}-01`;
  const lastDay = new Date(year, month, 0).getDate();
  const dt = `${year}-${String(month).padStart(2, "0")}-${String(lastDay).padStart(2, "0")}`;

  const q = useQuery({
    queryKey: ["pnlDayCosts", year, month],
    queryFn: () => fetchPnlDayCosts(df, dt),
  });

  const loadedKey = `${year}-${month}`;
  const [syncedKey, setSyncedKey] = useState("");
  if (q.data && syncedKey !== loadedKey) {
    setRows(q.data.days.map((d) => ({ ...d })));
    setSyncedKey(loadedKey);
  }

  const fields = q.data?.fields ?? [];

  const setCell = (idx: number, key: string, v: string) =>
    setRows((rs) => rs.map((r, i) => (i === idx ? { ...r, [key]: Number(v) || 0, has_row: true } : r)));

  const saveMut = useMutation({
    mutationFn: () => savePnlDayCosts(rows),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["pnl"] });
      qc.invalidateQueries({ queryKey: ["pnlDayCosts"] });
      onClose();
    },
  });

  const MONTHS = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"];

  return (
    <div onClick={onClose} style={modalBackdrop}>
      <div onClick={(e) => e.stopPropagation()} style={{ background: COLORS.card, borderRadius: 12, padding: 24, width: 720, maxWidth: "100%", border: `1px solid ${COLORS.grid}`, maxHeight: "88vh", display: "flex", flexDirection: "column" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
          <div style={{ fontSize: 17, fontWeight: 700 }}>Затраты по дням</div>
          <button onClick={onClose} style={{ ...tabBtn(false), border: `1px solid ${COLORS.grid}` }}>✕</button>
        </div>

        <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
          <select value={month} onChange={(e) => setMonth(Number(e.target.value))} style={dateInput}>
            {MONTHS.map((m, i) => <option key={i} value={i + 1}>{m}</option>)}
          </select>
          <select value={year} onChange={(e) => setYear(Number(e.target.value))} style={dateInput}>
            {[now.getFullYear() - 1, now.getFullYear()].map((y) => <option key={y} value={y}>{y}</option>)}
          </select>
        </div>

        <div style={{ fontSize: 12, color: COLORS.muted, marginBottom: 10 }}>
          Фактические суммы за день, ₽. Значения серым — черновик из помесячного резерва (пока не введены руками); впишите факт, чтобы ловить всплески.
        </div>

        {q.isLoading && <div style={{ color: COLORS.muted, fontSize: 13 }}>Загрузка…</div>}
        {q.data && (
          <div style={{ overflow: "auto", flex: 1 }}>
            <table style={{ borderCollapse: "collapse", width: "100%", fontVariantNumeric: "tabular-nums" }}>
              <thead>
                <tr style={{ color: COLORS.muted, position: "sticky", top: 0, background: COLORS.card }}>
                  <th style={{ ...mTH, textAlign: "left" }}>Дата</th>
                  {fields.map((f) => (
                    <th key={f.key} style={{ ...mTH, textAlign: "right" }}>{f.label}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((r, idx) => (
                  <tr key={r.date} style={{ borderTop: `1px solid ${COLORS.grid}` }}>
                    <td style={{ ...mTD, textAlign: "left", color: weekdayGroup(r.day_of_week).color, whiteSpace: "nowrap" }}>
                      {r.date.slice(8, 10)}.{r.date.slice(5, 7)} <span style={{ fontSize: 10 }}>{r.day_of_week}</span>
                    </td>
                    {fields.map((f) => (
                      <td key={f.key} style={{ padding: "2px 4px", textAlign: "right" }}>
                        <input
                          type="number"
                          value={(r[f.key as keyof PnlDayCostRow] as number) || 0}
                          onChange={(e) => setCell(idx, f.key, e.target.value)}
                          style={{ ...dateInput, width: 96, textAlign: "right", padding: "4px 8px", color: r.has_row ? "var(--text)" : COLORS.muted, fontVariantNumeric: "tabular-nums" }}
                        />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <button onClick={() => saveMut.mutate()} disabled={saveMut.isPending} style={saveBtn}>
          {saveMut.isPending ? "Сохранение…" : "Сохранить"}
        </button>
      </div>
    </div>
  );
}

function Field({ label, value, onChange }: { label: string; value: number; onChange: (v: string) => void }) {
  return (
    <label style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, padding: "5px 0" }}>
      <span style={{ fontSize: 13, color: "var(--text)" }}>{label}</span>
      <input
        type="number"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        style={{ ...dateInput, width: 130, textAlign: "right", fontVariantNumeric: "tabular-nums" }}
      />
    </label>
  );
}

const tabBtn = (active: boolean): React.CSSProperties => ({
  padding: "6px 14px",
  borderRadius: 6,
  border: "none",
  background: active ? COLORS.primary : "transparent",
  color: active ? "#fff" : "var(--text)",
  fontSize: 13,
  cursor: "pointer",
  fontWeight: active ? 600 : 400,
});

const dateInput: React.CSSProperties = {
  padding: "6px 10px",
  borderRadius: 8,
  border: `1px solid ${COLORS.grid}`,
  background: COLORS.bg,
  color: "var(--text)",
  fontSize: 13,
};

const modalBackdrop: React.CSSProperties = {
  position: "fixed", inset: 0, background: "rgba(0,0,0,.5)", display: "flex",
  alignItems: "flex-start", justifyContent: "center", padding: 24, zIndex: 100, overflow: "auto",
};

const saveBtn: React.CSSProperties = {
  width: "100%", marginTop: 16, padding: "10px", borderRadius: 8, border: "none",
  background: COLORS.primary, color: "#fff", fontSize: 14, fontWeight: 600, cursor: "pointer",
};
