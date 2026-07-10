import { useState } from "react";
import { useLiveQuery } from "../hooks";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from "recharts";
import { fetchCheckFullness, rangeKey, type RangeSel } from "../api";
import { CHART_HEIGHT, COLORS } from "../constants";
import { fillHourGaps, hourLabel } from "../format";

interface Props {
  range: RangeSel;
  withDelivery?: boolean;
}

// Цвет по числу позиций: от 1 (светлый) к 4+ (насыщенный).
const BUCKET_COLORS: Record<string, string> = {
  "1": COLORS.accent,
  "2": COLORS.good,
  "3": COLORS.warn,
  "4+": COLORS.primary,
};

/** Распределение чеков по числу позиций (1/2/3/4+) по часам (#6).
 *  Режим «доля %» нормирует каждый час к 100% (видно сдвиг состава), «кол-во» — абсолют. */
export function CheckFullness({ range, withDelivery = true }: Props) {
  const [pct, setPct] = useState(false);

  const q = useLiveQuery({
    queryKey: ["check-fullness", rangeKey(range), withDelivery],
    queryFn: () => fetchCheckFullness(range, withDelivery),
  });

  const buckets = q.data?.buckets ?? [];

  // инсайт по апсейлу: доля чеков на 1 позицию за период + час-пик одиночных чеков
  const totals = q.data?.total ?? {};
  const allChecks = buckets.reduce((s, b) => s + (totals[b] ?? 0), 0);
  const singleShare = allChecks ? Math.round(((totals["1"] ?? 0) / allChecks) * 100) : 0;
  let peak: { label: string; sh: number } | null = null;
  for (const r of q.data?.data ?? []) {
    if (!r.total || r.total < 5) continue; // малозначимые часы игнорируем
    const sh = Number(r["1"] ?? 0) / r.total;
    if (!peak || sh > peak.sh) peak = { label: r.label, sh };
  }

  // заполняем пропуски часов → равномерная ось X (часы без чеков не схлопываются)
  type FullnessRow = NonNullable<typeof q.data>["data"][number];
  const rawRows = fillHourGaps(q.data?.data ?? [], (h) => {
    const empty: Record<string, number | string> = { hour: h, label: hourLabel(h), total: 0 };
    buckets.forEach((b) => (empty[b] = 0));
    return empty as unknown as FullnessRow;
  });
  const data = rawRows.map((r) => {
    const row: Record<string, number | string> = { label: r.label };
    buckets.forEach((b) => {
      const v = Number(r[b] ?? 0);
      row[b] = pct && r.total ? Math.round((v / r.total) * 100) : v;
    });
    return row;
  });

  return (
    <div style={{ background: "var(--card)", borderRadius: 12, padding: "20px 24px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8, marginBottom: 16 }}>
        <div style={{ color: "var(--text)", fontWeight: 600 }}>Наполненность чеков по часам (позиций в чеке)</div>
        <div style={{ display: "flex", background: "var(--bg)", borderRadius: 8, padding: 3, gap: 2 }}>
          <button onClick={() => setPct(false)} style={mini(!pct)}>кол-во</button>
          <button onClick={() => setPct(true)} style={mini(pct)}>доля %</button>
        </div>
      </div>

      {q.isLoading ? (
        <div style={{ color: "var(--muted)", textAlign: "center", padding: 48 }}>Загрузка…</div>
      ) : allChecks === 0 ? (
        <div style={{ color: "var(--muted)", textAlign: "center", padding: 48 }}>Нет данных</div>
      ) : (
        <>
          <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
            <BarChart data={data} margin={{ left: 8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--grid)" />
              <XAxis dataKey="label" tick={{ fill: "var(--muted)", fontSize: 12 }} />
              <YAxis unit={pct ? "%" : ""} domain={pct ? [0, 100] : undefined} tick={{ fill: "var(--muted)", fontSize: 12 }} />
              <Tooltip
                contentStyle={{ background: "var(--bg)", border: "1px solid var(--grid)", borderRadius: 8 }}
                labelStyle={{ color: "var(--text)" }}
                formatter={(v, n) => [pct ? `${v}%` : `${v} чек.`, `${n} поз.`]}
              />
              <Legend wrapperStyle={{ fontSize: 12, color: "var(--muted)" }} formatter={(v) => `${v} поз.`} />
              {buckets.map((b) => (
                <Bar key={b} dataKey={b} stackId="full" fill={BUCKET_COLORS[b] ?? COLORS.muted} />
              ))}
            </BarChart>
          </ResponsiveContainer>

          {singleShare > 0 && (
            <div style={{ color: "var(--text)", fontSize: 12, marginTop: 8, padding: "8px 12px", background: "var(--bg)", borderRadius: 8, borderLeft: `3px solid ${COLORS.accent}` }}>
              Чеки на 1 позицию — <b>{singleShare}%</b> от всех
              {peak && <> · пик в <b>{peak.label}</b> ({Math.round(peak.sh * 100)}%)</>}. Часы с одиночными чеками — потенциал апсейла.
            </div>
          )}

          <div style={{ color: "var(--muted)", fontSize: 12, marginTop: 8 }}>
            Всего: {buckets.map((b) => `${b} поз. — ${q.data?.total[b] ?? 0}`).join(" · ")}
          </div>
        </>
      )}
    </div>
  );
}

const mini = (active: boolean): React.CSSProperties => ({
  padding: "5px 12px", borderRadius: 6, border: "none", cursor: "pointer",
  fontSize: 12, fontWeight: 600,
  background: active ? COLORS.primary : "transparent",
  color: active ? "var(--text)" : "var(--muted)",
});
