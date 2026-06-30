import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from "recharts";
import { useLiveQuery } from "../hooks";
import { fetchPaymentStructure, rangeKey, type RangeSel } from "../api";
import { CHART_HEIGHT, COLORS } from "../constants";
import { fmtInt } from "../format";
import type { PaymentTotal } from "../types";

interface Props {
  range: RangeSel;
  withDelivery?: boolean;
}

// Стабильные цвета по группе оплаты (читаемы в обеих темах).
const GROUP_COLORS: Record<string, string> = {
  "Карта": COLORS.primary,
  "Наличные": COLORS.good,
  "Агрегатор": COLORS.warn,
  "Прочее": COLORS.muted,
};
const colorFor = (g: string) => GROUP_COLORS[g] ?? COLORS.accent;

// «2026-06-22» → «22.06» (день.месяц).
const dm = (iso: string) => {
  const [, mm, dd] = iso.split("-");
  return `${dd}.${mm}`;
};

/** Структура выручки по способам оплаты (Карта/Наличные/Агрегатор).
 *  Сверху — две 100%-стопки (Выручка / Чеки) за период; снизу — стек по дням (тренд
 *  структуры). Источник — нормализованные оплаты (`/api/revenue/by-payment`); реагирует
 *  на галку «С доставкой» (агрегатор = доставка → при выкл исчезает). */
export function PaymentStructure({ range, withDelivery = true }: Props) {
  const q = useLiveQuery({
    queryKey: ["payment-structure", rangeKey(range), withDelivery],
    queryFn: () => fetchPaymentStructure(range, withDelivery),
  });

  const groups = q.data?.groups ?? [];
  const totals = q.data?.totals ?? [];
  const daily = q.data?.daily ?? [];
  const chartData = daily.map((d) => ({ ...d, label: dm(String(d.date)) }));

  return (
    <div style={{ background: "var(--card)", borderRadius: 12, padding: "20px 24px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 18 }}>
        <div style={{ color: "var(--text)", fontWeight: 600 }}>Структура выручки по оплате</div>
        <div style={{ color: "var(--muted)", fontSize: 13 }}>
          {fmtInt(q.data?.total_checks ?? 0)} чек. · {fmtInt(q.data?.total_amount ?? 0)} ₽
        </div>
      </div>

      {totals.length > 0 && (
        <>
          <StackBar
            name="Выручка"
            totals={totals}
            valueOf={(t) => t.share}
            label={(t) => `${t.group} · ${fmtInt(t.amount)} ₽ · ${t.share}%`}
          />
          <StackBar
            name="Чеки"
            totals={totals}
            valueOf={(t) => t.check_share}
            label={(t) => `${t.group} · ${fmtInt(t.checks)} чек. · ${t.check_share}%`}
          />

          {/* легенда групп */}
          <div style={{ display: "flex", flexWrap: "wrap", gap: 16, marginTop: 14, marginBottom: 8 }}>
            {totals.map((t) => (
              <div key={t.group} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: "var(--muted)" }}>
                <span style={{ width: 10, height: 10, borderRadius: 2, background: colorFor(t.group) }} />
                {t.group}
              </div>
            ))}
          </div>

          {/* тренд структуры по дням (стек выручки) — только когда дней больше одного */}
          {chartData.length > 1 && (
            <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
              <BarChart data={chartData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--grid)" vertical={false} />
                <XAxis dataKey="label" tick={{ fontSize: 11, fill: "var(--muted)" }} interval="preserveStartEnd" />
                <YAxis tick={{ fontSize: 11, fill: "var(--muted)" }} tickFormatter={(v) => fmtInt(Number(v))} />
                <Tooltip
                  contentStyle={{ background: "var(--card)", border: "1px solid var(--grid)", borderRadius: 8, fontSize: 12 }}
                  labelStyle={{ color: "var(--text)" }}
                  formatter={(v, n) => [`${fmtInt(Number(v))} ₽`, n]}
                />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                {groups.map((g) => (
                  <Bar key={g} dataKey={g} stackId="pay" fill={colorFor(g)} />
                ))}
              </BarChart>
            </ResponsiveContainer>
          )}
        </>
      )}

      {!q.isLoading && totals.length === 0 && (
        <div style={{ color: "var(--muted)", textAlign: "center", padding: 16 }}>Нет данных</div>
      )}
    </div>
  );
}

/** Одна 100%-стопка: подпись слева, сегменты групп с долями (% подписан внутри, если влезает). */
function StackBar({
  name,
  totals,
  valueOf,
  label,
}: {
  name: string;
  totals: PaymentTotal[];
  valueOf: (t: PaymentTotal) => number;
  label: (t: PaymentTotal) => string;
}) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 12 }}>
      <div style={{ flex: "0 0 60px", fontSize: 12, color: "var(--muted)" }}>{name}</div>
      <div style={{ flex: 1, display: "flex", height: 26, borderRadius: 6, overflow: "hidden", background: "var(--bg)" }}>
        {totals.map((t) => {
          const v = valueOf(t);
          if (v <= 0) return null;
          return (
            <div
              key={t.group}
              title={label(t)}
              style={{
                width: `${v}%`,
                background: colorFor(t.group),
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontSize: 11,
                fontWeight: 600,
                color: "#fff",
                whiteSpace: "nowrap",
                overflow: "hidden",
              }}
            >
              {v >= 8 ? `${v}%` : ""}
            </div>
          );
        })}
      </div>
    </div>
  );
}
