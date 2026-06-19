import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from "recharts";
import { fetchCheckComposition, fetchDishes, rangeKey, type RangeSel } from "../api";
import { CHART_HEIGHT, REFETCH_INTERVAL_MS, COLORS } from "../constants";
import { fmtInt } from "../format";

interface Props {
  range: RangeSel;
}

const PALETTE = [
  COLORS.primary, COLORS.good, COLORS.warn, COLORS.accent, COLORS.bad,
  COLORS.indigoText, "#8b5cf6", "#ec4899", "#14b8a6", "#f97316",
];

/** Состав чека (#5): средняя доля категорий в чеке. Тумблеры: по кол-ву / по выручке;
 *  за период / по часам. Стек 100%. Данные — `/api/dishes/check-composition`.
 *  Клик по категории (столбик/легенда) — провал в товары этой категории (доля товара
 *  в категории за период, источник `/api/dishes`). */
export function CheckComposition({ range }: Props) {
  const [by, setBy] = useState<"qty" | "rev">("qty");
  const [mode, setMode] = useState<"total" | "hour">("total");
  const [drillCat, setDrillCat] = useState<string | null>(null);

  const q = useQuery({
    queryKey: ["check-composition", rangeKey(range)],
    queryFn: () => fetchCheckComposition(range),
    refetchInterval: REFETCH_INTERVAL_MS,
  });

  const cats = q.data?.categories ?? [];
  const color = (c: string) => PALETTE[(cats.indexOf(c) + PALETTE.length) % PALETTE.length];

  // провал в категорию (#): товары внутри неё с долей «товар / итог категории» за период.
  // Переиспользуем `/api/dishes` (group_by=dish) — там есть category (group_name) и кол-во/выручка.
  const dishQ = useQuery({
    queryKey: ["check-composition-drill", rangeKey(range)],
    queryFn: () => fetchDishes(range, "dish"),
    refetchInterval: REFETCH_INTERVAL_MS,
    enabled: drillCat !== null,
  });

  const drillRows = useMemo(() => {
    if (!drillCat) return [];
    const inCat = (dishQ.data?.data ?? []).filter((d) => d.group_name === drillCat);
    const total = inCat.reduce((s, d) => s + (by === "qty" ? d.quantity : d.revenue), 0);
    return inCat
      .map((d) => {
        const val = by === "qty" ? d.quantity : d.revenue;
        return { name: d.name, val, share: total ? (val / total) * 100 : 0 };
      })
      .sort((a, b) => b.val - a.val);
  }, [drillCat, dishQ.data, by]);
  const rowOf = (bucket: { by: Record<string, { qty: number; rev: number }> }) => {
    const r: Record<string, number | string> = {};
    cats.forEach((c) => (r[c] = bucket.by[c] ? bucket.by[c][by] : 0));
    return r;
  };
  const data =
    mode === "total"
      ? q.data
        ? [{ label: "За период", ...rowOf(q.data.total) }]
        : []
      : (q.data?.hourly ?? []).map((h) => ({ label: h.label, ...rowOf(h) }));

  return (
    <div style={{ background: "var(--card)", borderRadius: 12, padding: "20px 24px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8, marginBottom: 16 }}>
        <div style={{ color: "var(--text)", fontWeight: 600 }}>Состав чека (доля категорий)</div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <div style={{ display: "flex", background: "var(--bg)", borderRadius: 8, padding: 3, gap: 2 }}>
            <button onClick={() => setBy("qty")} style={mini(by === "qty")}>по кол-ву</button>
            <button onClick={() => setBy("rev")} style={mini(by === "rev")}>по выручке</button>
          </div>
          <div style={{ display: "flex", background: "var(--bg)", borderRadius: 8, padding: 3, gap: 2 }}>
            <button onClick={() => setMode("total")} style={mini(mode === "total")}>За период</button>
            <button onClick={() => setMode("hour")} style={mini(mode === "hour")}>По часам</button>
          </div>
        </div>
      </div>

      <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
        <BarChart data={data} margin={{ left: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--grid)" />
          <XAxis dataKey="label" tick={{ fill: "var(--muted)", fontSize: 12 }} />
          <YAxis unit="%" domain={[0, 100]} tick={{ fill: "var(--muted)", fontSize: 12 }} />
          <Tooltip
            contentStyle={{ background: "var(--bg)", border: "1px solid var(--grid)", borderRadius: 8 }}
            labelStyle={{ color: "var(--text)" }}
            formatter={(v, n) => [`${v}%`, n]}
          />
          <Legend
            wrapperStyle={{ fontSize: 12, color: "var(--muted)", cursor: "pointer" }}
            onClick={(e) => setDrillCat(String((e as { value?: string }).value ?? ""))}
          />
          {cats.map((c) => (
            <Bar key={c} dataKey={c} stackId="comp" fill={color(c)} cursor="pointer" onClick={() => setDrillCat(c)} />
          ))}
        </BarChart>
      </ResponsiveContainer>

      <div style={{ color: "var(--muted)", fontSize: 12, marginTop: 8 }}>
        Чеков в периоде: {q.data?.total.checks ?? 0}. Доля = средняя по чекам (
        {by === "qty" ? "по количеству позиций" : "по сумме"}). Клик по категории — разбивка по товарам.
      </div>

      {drillCat && (
        <div style={{ marginTop: 16, borderTop: "1px solid var(--grid)", paddingTop: 16 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
            <div style={{ color: "var(--text)", fontWeight: 600 }}>
              <span style={{ color: color(drillCat) }}>●</span> {drillCat} → товары
              <span style={{ color: "var(--muted)", fontWeight: 400, marginLeft: 8, fontSize: 12 }}>
                (доля в категории, {by === "qty" ? "по кол-ву" : "по выручке"})
              </span>
            </div>
            <button onClick={() => setDrillCat(null)} style={mini(false)}>✕ закрыть</button>
          </div>

          {dishQ.isLoading && <div style={{ color: "var(--muted)", padding: 12 }}>Загрузка…</div>}
          {!dishQ.isLoading && drillRows.length === 0 && (
            <div style={{ color: "var(--muted)", padding: 12 }}>Нет товаров в категории за период</div>
          )}
          {drillRows.map((r) => (
            <div key={r.name} style={{ display: "flex", alignItems: "center", gap: 10, padding: "5px 0" }}>
              <div style={{ flex: "0 0 40%", color: "var(--text)", fontSize: 13, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {r.name}
              </div>
              <div style={{ flex: 1, background: "var(--bg)", borderRadius: 4, height: 14, overflow: "hidden" }}>
                <div style={{ width: `${r.share}%`, height: "100%", background: color(drillCat) }} />
              </div>
              <div style={{ flex: "0 0 64px", textAlign: "right", color: "var(--muted)", fontSize: 12 }}>
                {by === "qty" ? `${fmtInt(r.val)} шт` : `${fmtInt(r.val)} ₽`}
              </div>
              <div style={{ flex: "0 0 48px", textAlign: "right", color: "var(--text)", fontSize: 12, fontWeight: 600 }}>
                {Math.round(r.share)}%
              </div>
            </div>
          ))}
        </div>
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
