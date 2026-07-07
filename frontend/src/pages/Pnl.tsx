import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

import type { Period, RangeSel, PnlLine, PnlRating, PnlSection, PnlBreakeven } from "../api";
import { fetchPnl, fetchPnlCosts, savePnlCosts, rangeKey } from "../api";
import { fmtInt } from "../format";
import { COLORS, PERIODS } from "../constants";

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

export function Pnl() {
  const [sel, setSel] = useState<RangeSel>({ period: "month" });
  const [showCustom, setShowCustom] = useState(false);
  const [from, setFrom] = useState(todayISO());
  const [to, setTo] = useState(todayISO());
  const [editing, setEditing] = useState(false);

  const isCustom = "from" in sel;

  const pnlQ = useQuery({
    queryKey: ["pnl", rangeKey(sel)],
    queryFn: () => fetchPnl(sel),
  });

  const pickPreset = (p: Period) => {
    setSel({ period: p });
    setShowCustom(false);
  };
  const applyCustom = () => {
    if (from && to && from <= to) setSel({ from, to });
  };

  const data = pnlQ.data;

  return (
    <div className="page" style={{ minHeight: "100vh", background: COLORS.bg, color: "var(--text)" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 12, marginBottom: 24 }}>
        <div>
          <div style={{ fontSize: 22, fontWeight: 700 }}>P&L дня</div>
          <div style={{ color: COLORS.muted, fontSize: 13, marginTop: 2 }}>
            Прибыль за период: выручка и food cost из iiko, прочие затраты — вручную (помесячно)
          </div>
        </div>
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
              📅 Период
            </button>
          </div>
          <button onClick={() => setEditing(true)} style={{ ...tabBtn(false), border: `1px solid ${COLORS.grid}` }}>
            ⚙ Затраты
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
              Затраты за этот период ещё не введены — заполните их через «⚙ Затраты», иначе видно только выручку и food cost.
            </div>
          )}

          {/* Хедер: EBITDA + вердикт по безубыточности */}
          <div style={{ display: "flex", gap: 24, flexWrap: "wrap", alignItems: "flex-end", marginBottom: 16 }}>
            <div>
              <div style={{ color: COLORS.muted, fontSize: 12 }}>EBITDA за период · {data.date_from} — {data.date_to}</div>
              <div style={{ fontSize: 30, fontWeight: 800, color: data.ebitda >= 0 ? COLORS.good : COLORS.bad, marginTop: 2 }}>
                {fmtRub(data.ebitda)} <span style={{ fontSize: 16, fontWeight: 600, color: rateColor(data.ebitda_rating) ?? COLORS.muted }}>({data.ebitda_margin}%)</span>
              </div>
            </div>
            <BreakevenVerdict be={data.breakeven} />
          </div>

          {/* Единая таблица P&L */}
          <div style={{ background: COLORS.card, borderRadius: 12, border: `1px solid ${COLORS.grid}`, overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13, minWidth: 420 }}>
              <thead>
                <tr style={{ color: COLORS.muted, fontSize: 11, textTransform: "uppercase", letterSpacing: 0.4 }}>
                  <th style={{ textAlign: "left", padding: "10px 14px", fontWeight: 500 }}>Показатель</th>
                  <th style={{ textAlign: "right", padding: "10px 14px", fontWeight: 500 }}>₽</th>
                  <th style={{ textAlign: "right", padding: "10px 14px", fontWeight: 500, width: 80 }}>% выр.</th>
                </tr>
              </thead>
              <tbody>
                {data.sections.map((s) => (
                  <SectionRows key={s.key} section={s} />
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {editing && <CostEditor onClose={() => setEditing(false)} />}
    </div>
  );
}

// Строки-подытоги (жирные, с рамкой) — ключевые агрегаты P&L.
const SUBTOTAL = new Set([
  "revenue", "cogs", "prime_cost", "production_cost", "total_opex",
  "contribution_margin", "fixed_alloc", "all_expenses", "ebitda",
]);

/** Секция единой таблицы: строка-заголовок + строки показателей. */
function SectionRows({ section }: { section: PnlSection }) {
  return (
    <>
      <tr>
        <td colSpan={3} style={{ padding: "9px 14px 5px", fontSize: 12, fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.4, color: COLORS.indigoText, background: COLORS.bg, borderTop: `1px solid ${COLORS.grid}` }}>
          {section.label}
        </td>
      </tr>
      {section.lines.map((l) => {
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

/** Модалка ввода помесячных затрат. */
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
    <div onClick={onClose} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.5)", display: "flex", alignItems: "flex-start", justifyContent: "center", padding: 24, zIndex: 100, overflow: "auto" }}>
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
            <div style={{ fontSize: 12, color: COLORS.muted, marginBottom: 8 }}>Суммы за месяц, ₽ (делятся на дни месяца)</div>
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
              style={{ width: "100%", marginTop: 18, padding: "10px", borderRadius: 8, border: "none", background: COLORS.primary, color: "#fff", fontSize: 14, fontWeight: 600, cursor: "pointer" }}
            >
              {saveMut.isPending ? "Сохранение…" : "Сохранить"}
            </button>
          </>
        )}
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
