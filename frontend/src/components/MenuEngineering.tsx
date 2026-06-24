import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ScatterChart, Scatter, ComposedChart, Bar, Line, Cell, LabelList,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine, ReferenceArea, Legend,
} from "recharts";
import { fetchDishes, rangeKey, type RangeSel, type DishRow } from "../api";
import { CHART_HEIGHT, REFETCH_INTERVAL_MS, COLORS } from "../constants";
import { fmtInt } from "../format";

interface Props {
  range: RangeSel;
  withDelivery?: boolean;
}

// Квадранты меню-инжиниринга: популярность × маржинальность.
const QUAD = {
  star: { label: "⭐ Звёзды", color: COLORS.good, hint: "двигать, держать качество" },
  plow: { label: "🐴 Рабочие лошадки", color: COLORS.warn, hint: "поднять цену / снизить с/с" },
  puzzle: { label: "❓ Загадки", color: COLORS.accent, hint: "продвигать, переставить в меню" },
  dog: { label: "🐕 Собаки", color: COLORS.bad, hint: "переделать или вывести" },
} as const;
type Quad = keyof typeof QUAD;

interface Point { x: number; y: number; name: string; mpct: number; rev: number; quad: Quad; label: string }

const ABC_COLOR: Record<string, string> = { A: COLORS.good, B: COLORS.warn, C: COLORS.bad };

/** Меню-инжиниринг: матрица популярность×маржа (Звёзды/Лошадки/Загадки/Собаки) и
 *  ABC-анализ (Парето). Считается на лету из `/api/dishes` (group_by=dish). */
export function MenuEngineering({ range, withDelivery = true }: Props) {
  const [view, setView] = useState<"matrix" | "abc">("matrix");
  const [abcBasis, setAbcBasis] = useState<"rev" | "margin">("rev");

  const q = useQuery({
    queryKey: ["dishes", rangeKey(range), "dish", withDelivery],
    queryFn: () => fetchDishes(range, "dish", withDelivery),
    refetchInterval: REFETCH_INTERVAL_MS,
  });
  const all: DishRow[] = useMemo(() => q.data?.data ?? [], [q.data]);

  // ----- Матрица: только блюда с с/с и продажами -----
  const matrix = useMemo(() => {
    const costed = all.filter((d) => d.quantity > 0 && d.has_cost && d.cost_sum > 0);
    const totalQty = costed.reduce((s, d) => s + d.quantity, 0);
    const totalCM = costed.reduce((s, d) => s + (d.revenue - d.cost_sum), 0);
    const avgCM = totalQty ? totalCM / totalQty : 0; // средняя маржа на единицу, ₽
    const popThr = costed.length ? (totalQty / costed.length) * 0.7 : 0; // правило 70%
    // подписываем на графике только топ-6 по выручке — иначе подписи сливаются;
    // имя укорачиваем, чтобы длинные («Халва с шоко») не наезжали и не переносились
    const topNames = new Set(
      [...costed].sort((a, b) => b.revenue - a.revenue).slice(0, 6).map((d) => d.name),
    );
    const shortName = (s: string) => (s.length > 10 ? s.slice(0, 9) + "…" : s);
    const points: Point[] = costed.map((d) => {
      const cm = (d.revenue - d.cost_sum) / d.quantity;
      const popular = d.quantity >= popThr;
      const highCM = cm >= avgCM;
      const quad: Quad = popular ? (highCM ? "star" : "plow") : highCM ? "puzzle" : "dog";
      return {
        x: d.quantity, y: Math.round(cm), name: d.name, mpct: d.margin_pct ?? 0, rev: d.revenue, quad,
        label: topNames.has(d.name) ? shortName(d.name) : "",
      };
    });
    return { points, avgCM: Math.round(avgCM), popThr: Math.round(popThr), excluded: all.length - costed.length };
  }, [all]);

  // ----- ABC: Парето по выручке или по марже -----
  const abc = useMemo(() => {
    // по прибыли — только блюда с известной с/с (без неё «прибыль» = выручка, искажает)
    const src = abcBasis === "rev" ? all : all.filter((d) => d.has_cost);
    const base = src
      .map((d) => ({ name: d.name, value: abcBasis === "rev" ? d.revenue : d.revenue - d.cost_sum }))
      .filter((d) => d.value > 0)
      .sort((a, b) => b.value - a.value);
    const total = base.reduce((s, d) => s + d.value, 0) || 1;
    const rows: { name: string; value: number; cum: number; cls: string }[] = [];
    let acc = 0;
    for (const d of base) {
      acc += d.value;
      const cum = (acc / total) * 100;
      rows.push({ ...d, cum: Math.round(cum * 10) / 10, cls: cum <= 80 ? "A" : cum <= 95 ? "B" : "C" });
    }
    const summary = (["A", "B", "C"] as const).map((c) => {
      const items = rows.filter((r) => r.cls === c);
      return { cls: c, count: items.length, share: Math.round((items.reduce((s, r) => s + r.value, 0) / total) * 100) };
    });
    return { rows, summary };
  }, [all, abcBasis]);

  const quadCounts = (Object.keys(QUAD) as Quad[]).map((k) => ({
    k, ...QUAD[k], count: matrix.points.filter((p) => p.quad === k).length,
  }));

  return (
    <div style={{ background: "var(--card)", borderRadius: 12, padding: "20px 24px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8, marginBottom: 16 }}>
        <div style={{ color: "var(--text)", fontWeight: 600 }}>Меню-инжиниринг</div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {view === "abc" && (
            <div style={{ display: "flex", background: "var(--bg)", borderRadius: 8, padding: 3, gap: 2 }}>
              <button onClick={() => setAbcBasis("rev")} style={mini(abcBasis === "rev")}>по выручке</button>
              <button onClick={() => setAbcBasis("margin")} style={mini(abcBasis === "margin")}>по прибыли</button>
            </div>
          )}
          <div style={{ display: "flex", background: "var(--bg)", borderRadius: 8, padding: 3, gap: 2 }}>
            <button onClick={() => setView("matrix")} style={mini(view === "matrix")}>Матрица</button>
            <button onClick={() => setView("abc")} style={mini(view === "abc")}>ABC</button>
          </div>
        </div>
      </div>

      {view === "matrix" ? (
        <>
          <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
            <ScatterChart margin={{ top: 10, right: 24, bottom: 28, left: 16 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--grid)" />
              <XAxis
                type="number" dataKey="x" name="Продано" unit=" шт"
                tick={{ fill: "var(--muted)", fontSize: 12 }}
                label={{ value: "Продано за период, шт", position: "insideBottom", offset: -16, fill: "var(--muted)", fontSize: 12 }}
              />
              <YAxis
                type="number" dataKey="y" name="Маржа/шт" unit=" ₽"
                tick={{ fill: "var(--muted)", fontSize: 12 }}
                label={{ value: "Маржа на штуку, ₽", angle: -90, position: "insideLeft", style: { textAnchor: "middle" }, fill: "var(--muted)", fontSize: 12 }}
              />
              {/* бледная заливка квадрантов — зона блюда читается мгновенно, без сверки с осями */}
              <ReferenceArea x1={matrix.popThr} y1={matrix.avgCM} fill={QUAD.star.color} fillOpacity={0.07} />
              <ReferenceArea x1={matrix.popThr} y2={matrix.avgCM} fill={QUAD.plow.color} fillOpacity={0.07} />
              <ReferenceArea x2={matrix.popThr} y1={matrix.avgCM} fill={QUAD.puzzle.color} fillOpacity={0.07} />
              <ReferenceArea x2={matrix.popThr} y2={matrix.avgCM} fill={QUAD.dog.color} fillOpacity={0.07} />
              <ReferenceLine x={matrix.popThr} stroke="var(--muted)" strokeDasharray="4 4" label={{ value: "порог популярности", fill: "var(--muted)", fontSize: 11, position: "insideTopRight" }} />
              <ReferenceLine y={matrix.avgCM} stroke="var(--muted)" strokeDasharray="4 4" label={{ value: "ср. маржа", fill: "var(--muted)", fontSize: 11, position: "insideTopLeft" }} />
              <Tooltip
                cursor={{ strokeDasharray: "3 3" }}
                content={(p: { active?: boolean; payload?: ReadonlyArray<{ payload?: Point }> }) => {
                  const d = p.active ? p.payload?.[0]?.payload : undefined;
                  if (!d) return null;
                  return (
                    <div style={{ background: "var(--bg)", border: "1px solid var(--grid)", borderRadius: 8, padding: "8px 10px", fontSize: 12 }}>
                      <div style={{ fontWeight: 600, color: "var(--text)" }}>{d.name}</div>
                      <div style={{ color: "var(--muted)" }}>продано: {fmtInt(d.x)} шт</div>
                      <div style={{ color: "var(--muted)" }}>маржа: {fmtInt(d.y)} ₽/шт ({d.mpct}%)</div>
                    </div>
                  );
                }}
              />
              {(Object.keys(QUAD) as Quad[]).map((k) => (
                <Scatter key={k} name={QUAD[k].label} data={matrix.points.filter((p) => p.quad === k)} fill={QUAD[k].color}>
                  {/* подписи нижних квадрантов — под точкой, верхних — над: разносит
                      налезающие подписи блюд, скучкованных у порогов */}
                  <LabelList
                    dataKey="label"
                    position={k === "dog" || k === "plow" ? "bottom" : "top"}
                    style={{ fill: "var(--text)", fontSize: 10 }}
                  />
                </Scatter>
              ))}
            </ScatterChart>
          </ResponsiveContainer>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 10, marginTop: 12 }}>
            {quadCounts.map((qd) => (
              <div key={qd.k} style={{ borderLeft: `4px solid ${qd.color}`, padding: "6px 12px", background: "var(--bg)", borderRadius: 8 }}>
                <div style={{ fontWeight: 600, fontSize: 13 }}>{qd.label} · {qd.count}</div>
                <div style={{ color: "var(--muted)", fontSize: 12 }}>{qd.hint}</div>
              </div>
            ))}
          </div>
          <div style={{ color: "var(--muted)", fontSize: 12, marginTop: 8 }}>
            Оси: популярность (порог = 70% от средних продаж) × маржа на штуку (порог = ср. маржа {fmtInt(matrix.avgCM)} ₽).
            {matrix.excluded > 0 && ` Без с/с и не учтено: ${matrix.excluded} блюд (нужна привязка ТТК).`}
          </div>
        </>
      ) : (
        <>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 12 }}>
            {abc.summary.map((s) => (
              <div key={s.cls} style={{ borderLeft: `4px solid ${ABC_COLOR[s.cls]}`, padding: "6px 12px", background: "var(--bg)", borderRadius: 8 }}>
                <div style={{ fontWeight: 600, fontSize: 13 }}>Группа {s.cls}: {s.count} поз.</div>
                <div style={{ color: "var(--muted)", fontSize: 12 }}>{s.share}% {abcBasis === "rev" ? "выручки" : "прибыли"}</div>
              </div>
            ))}
          </div>
          <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
            <ComposedChart data={abc.rows} margin={{ left: 8, right: 8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--grid)" />
              <XAxis dataKey="name" hide />
              <YAxis yAxisId="v" tickFormatter={fmtInt} tick={{ fill: "var(--muted)", fontSize: 12 }} />
              <YAxis yAxisId="cum" orientation="right" domain={[0, 100]} unit="%" tick={{ fill: "var(--muted)", fontSize: 12 }} />
              <Tooltip
                contentStyle={{ background: "var(--bg)", border: "1px solid var(--grid)", borderRadius: 8 }}
                labelStyle={{ color: "var(--text)" }}
                formatter={(v, n) => (n === "Накопительно" ? `${v}%` : `${fmtInt(Number(v))} ₽`)}
              />
              <Legend wrapperStyle={{ fontSize: 12, color: "var(--muted)" }} />
              <Bar yAxisId="v" dataKey="value" name={abcBasis === "rev" ? "Выручка" : "Прибыль"}>
                {abc.rows.map((r, i) => <Cell key={i} fill={ABC_COLOR[r.cls]} />)}
              </Bar>
              <Line yAxisId="cum" dataKey="cum" name="Накопительно" stroke={COLORS.primary} strokeWidth={2} dot={false} />
            </ComposedChart>
          </ResponsiveContainer>
          <div style={{ color: "var(--muted)", fontSize: 12, marginTop: 8 }}>
            A — до 80% {abcBasis === "rev" ? "выручки" : "прибыли"} (ключевые), B — до 95%, C — хвост (кандидаты на вывод/пересмотр).
          </div>
        </>
      )}

      {q.isLoading && <div style={{ color: "var(--muted)", textAlign: "center", padding: 16 }}>Загрузка…</div>}
    </div>
  );
}

const mini = (active: boolean): React.CSSProperties => ({
  padding: "5px 12px", borderRadius: 6, border: "none", cursor: "pointer",
  fontSize: 12, fontWeight: 600,
  background: active ? COLORS.primary : "transparent",
  color: active ? "var(--text)" : "var(--muted)",
});
