import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchPlan, savePlan, seedPlanFromHistory, type PlanCell } from "../api";
import { COLORS } from "../constants";

interface Props {
  onClose: () => void;
}

type Metric = "revenue" | "avg_check" | "guests";
const METRICS: { key: Metric; label: string }[] = [
  { key: "revenue", label: "Выручка/день" },
  { key: "avg_check", label: "Средний чек" },
  { key: "guests", label: "Гостей/день" },
];

/**
 * Редактор плана: матрица (дейпарт × группа дня недели) дневных норм по метрике.
 * Нормы задаются на ОДИН день сегмента — отчёт масштабирует на число дней периода.
 * Кнопка «Заполнить из истории» проставляет средние из прошлых месяцев (потом правишь).
 */
export function PlanEditor({ onClose }: Props) {
  const qc = useQueryClient();
  const planQ = useQuery({ queryKey: ["plan"], queryFn: fetchPlan });
  const [metric, setMetric] = useState<Metric>("revenue");
  // правки храним оверлеем поверх загруженных данных (без копирования в эффекте)
  const [edits, setEdits] = useState<Record<string, Partial<PlanCell>>>({});
  const [busy, setBusy] = useState(false);

  const dayparts = planQ.data?.dayparts ?? [];
  const groups = planQ.data?.weekday_groups ?? [];
  const base = planQ.data?.cells ?? {};

  const cellVal = (ck: string, m: Metric): number =>
    edits[ck]?.[m] ?? base[ck]?.[m] ?? 0;
  const setVal = (ck: string, v: number) =>
    setEdits((p) => ({ ...p, [ck]: { ...(p[ck] ?? {}), [metric]: v } }));

  const doSeed = async () => {
    setBusy(true);
    await seedPlanFromHistory(2);
    await planQ.refetch();
    setEdits({}); // нормы перезаписаны из истории — сбрасываем ручные правки
    setBusy(false);
  };

  const doSave = async () => {
    setBusy(true);
    // собираем полную матрицу (база + правки) по всем сегментам
    const merged: Record<string, PlanCell> = {};
    for (const dp of dayparts) {
      for (const g of groups) {
        const ck = `${dp.key}|${g.key}`;
        merged[ck] = {
          revenue: cellVal(ck, "revenue"),
          avg_check: cellVal(ck, "avg_check"),
          guests: cellVal(ck, "guests"),
        };
      }
    }
    await savePlan(merged);
    await qc.invalidateQueries({ queryKey: ["ops-report"] });
    await qc.invalidateQueries({ queryKey: ["plan"] });
    setBusy(false);
    onClose();
  };

  const inp: React.CSSProperties = {
    width: 86, padding: "5px 8px", textAlign: "right", fontSize: 13,
    background: "var(--bg)", color: "var(--text)", border: "1px solid var(--grid)", borderRadius: 6,
    fontVariantNumeric: "tabular-nums",
  };

  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed", inset: 0, background: "rgba(0,0,0,0.55)", zIndex: 50,
        display: "flex", alignItems: "center", justifyContent: "center", padding: 20,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{ background: "var(--card)", borderRadius: 14, padding: 24, maxWidth: 720, width: "100%", maxHeight: "90vh", overflowY: "auto" }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
          <div style={{ color: "var(--text)", fontWeight: 700, fontSize: 16 }}>План по дейпартам</div>
          <button onClick={onClose} style={{ background: "transparent", border: "none", color: "var(--muted)", fontSize: 20, cursor: "pointer" }}>×</button>
        </div>
        <div style={{ color: "var(--muted)", fontSize: 12, marginBottom: 16 }}>
          Норма на <b>один день</b> сегмента (дейпарт × группа дня недели). В отчёте план = норма × число таких дней в периоде, поэтому «% к плану» честен и для недели, и для месяца.
        </div>

        <div style={{ display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: 8, marginBottom: 14 }}>
          <div style={{ display: "flex", gap: 6 }}>
            {METRICS.map((m) => (
              <button
                key={m.key}
                onClick={() => setMetric(m.key)}
                style={{
                  background: metric === m.key ? COLORS.primary : "transparent",
                  color: metric === m.key ? "#fff" : "var(--muted)",
                  border: "1px solid var(--grid)", borderRadius: 6, padding: "5px 12px", fontSize: 12, cursor: "pointer",
                }}
              >
                {m.label}
              </button>
            ))}
          </div>
          <button
            onClick={doSeed}
            disabled={busy}
            style={{ background: "transparent", color: "var(--text)", border: "1px solid var(--grid)", borderRadius: 6, padding: "5px 12px", fontSize: 12, cursor: busy ? "wait" : "pointer" }}
          >
            ↻ Заполнить из истории (2 мес)
          </button>
        </div>

        {planQ.isLoading ? (
          <div style={{ color: "var(--muted)", padding: 20, textAlign: "center" }}>Загрузка…</div>
        ) : (
          <table style={{ borderCollapse: "collapse", width: "100%" }}>
            <thead>
              <tr style={{ color: "var(--muted)", fontSize: 12 }}>
                <th style={{ textAlign: "left", padding: "6px 8px", fontWeight: 500 }}>Дейпарт</th>
                {groups.map((g) => (
                  <th key={g.key} style={{ textAlign: "right", padding: "6px 8px", fontWeight: 500 }}>{g.label}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {dayparts.map((dp) => (
                <tr key={dp.key} style={{ borderTop: "1px solid var(--grid)" }}>
                  <td style={{ padding: "6px 8px", color: "var(--text)", fontSize: 13 }}>
                    {dp.label} <span style={{ color: "var(--muted)", fontSize: 11 }}>{dp.range}</span>
                  </td>
                  {groups.map((g) => {
                    const ck = `${dp.key}|${g.key}`;
                    return (
                      <td key={g.key} style={{ padding: "4px 8px", textAlign: "right" }}>
                        <input
                          type="number"
                          min={0}
                          value={Math.round(cellVal(ck, metric))}
                          onChange={(e) => setVal(ck, Number(e.target.value))}
                          style={inp}
                        />
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        )}

        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 20 }}>
          <button onClick={onClose} style={{ background: "transparent", color: "var(--muted)", border: "1px solid var(--grid)", borderRadius: 8, padding: "8px 16px", fontSize: 13, cursor: "pointer" }}>Отмена</button>
          <button onClick={doSave} disabled={busy} style={{ background: COLORS.primary, color: "#fff", border: "none", borderRadius: 8, padding: "8px 20px", fontSize: 13, cursor: busy ? "wait" : "pointer" }}>
            {busy ? "Сохранение…" : "Сохранить"}
          </button>
        </div>
      </div>
    </div>
  );
}
