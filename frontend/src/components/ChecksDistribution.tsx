import { useLiveQuery } from "../hooks";
import { fetchCheckDistribution, fetchRevenueByChannel, rangeKey, type RangeSel } from "../api";
import { COLORS } from "../constants";
import { fmtInt } from "../format";

interface Props {
  range: RangeSel;
  withDelivery?: boolean;
}

// Цвета по типу обслуживания (стабильные, читаемы в обеих темах).
const TYPE_COLORS: Record<string, string> = {
  "Доставка": COLORS.primary,
  "В зале": COLORS.good,
  "С собой": COLORS.warn,
};
const colorFor = (t: string) => TYPE_COLORS[t] ?? COLORS.accent;

interface Seg {
  type: string;
  color: string;
  count: number;
  countShare: number;
  rev: number;
  revShare: number;
}

/** Распределение чеков по типу обслуживания (#1): доставка / в зале / с собой.
 *  Данные — уникальные заказы по каналу (OLAP): сумма по типам = числу чеков.
 *  Две 100%-стопки (Чеки / Выручка), сегменты — каналы (один цвет в обеих полосах):
 *  видно перекос (напр. доставка = 30% чеков, но 50% выручки). */
export function ChecksDistribution({ range, withDelivery = true }: Props) {
  const q = useLiveQuery({
    queryKey: ["check-distribution", rangeKey(range), withDelivery],
    queryFn: () => fetchCheckDistribution(range, withDelivery),
  });
  const revQ = useLiveQuery({
    queryKey: ["revenue-by-channel", rangeKey(range), withDelivery],
    queryFn: () => fetchRevenueByChannel(range, withDelivery),
  });

  const isDelivery = (t: string) => t.toLowerCase() === "доставка";
  // при выключенной галке «С доставкой» строку доставки не показываем вовсе
  const rows = (q.data?.data ?? []).filter((r) => withDelivery || !isDelivery(r.type));

  // выручка по каналу за период: суммируем по дням. Названия каналов в by-channel — строчные
  // («доставка»/«с собой»/«в зале»), в check-distribution — с заглавной → матчим по lower-case.
  const revByChannel: Record<string, number> = {};
  (revQ.data?.channels ?? [])
    .filter((c) => withDelivery || !isDelivery(c))
    .forEach((c) => {
      revByChannel[c.toLowerCase()] = (revQ.data?.data ?? []).reduce(
        (s, d) => s + Number(d[c] ?? 0),
        0,
      );
    });
  const totalRev = Object.values(revByChannel).reduce((s, v) => s + v, 0);

  const segs: Seg[] = rows.map((r) => {
    const rev = revByChannel[r.type.toLowerCase()] ?? 0;
    return {
      type: r.type,
      color: colorFor(r.type),
      count: r.count,
      countShare: r.share,
      rev,
      revShare: totalRev ? Math.round((rev / totalRev) * 1000) / 10 : 0,
    };
  });

  return (
    <div style={{ background: "var(--card)", borderRadius: 12, padding: "20px 24px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 18 }}>
        <div style={{ color: "var(--text)", fontWeight: 600 }}>Чеки и выручка по типу обслуживания</div>
        <div style={{ color: "var(--muted)", fontSize: 13 }}>
          {q.data?.total ?? 0} чек. · {fmtInt(totalRev)} ₽
        </div>
      </div>

      {segs.length > 0 && (
        <>
          <StackBar
            name="Чеки"
            segs={segs}
            valueOf={(s) => s.countShare}
            label={(s) => `${s.type} · ${fmtInt(s.count)} чек. · ${s.countShare}%`}
          />
          <StackBar
            name="Выручка"
            segs={segs}
            valueOf={(s) => s.revShare}
            label={(s) => `${s.type} · ${fmtInt(s.rev)} ₽ · ${s.revShare}%`}
          />

          {/* легенда каналов */}
          <div style={{ display: "flex", flexWrap: "wrap", gap: 16, marginTop: 14 }}>
            {segs.map((s) => (
              <div key={s.type} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: "var(--muted)" }}>
                <span style={{ width: 10, height: 10, borderRadius: 2, background: s.color }} />
                {s.type}
              </div>
            ))}
          </div>
        </>
      )}

      {!q.isLoading && segs.length === 0 && (
        <div style={{ color: "var(--muted)", textAlign: "center", padding: 16 }}>Нет данных</div>
      )}
    </div>
  );
}

/** Одна 100%-стопка: подпись слева, сегменты каналов с долями (% подписан внутри, если влезает). */
function StackBar({
  name,
  segs,
  valueOf,
  label,
}: {
  name: string;
  segs: Seg[];
  valueOf: (s: Seg) => number;
  label: (s: Seg) => string;
}) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 12 }}>
      <div style={{ flex: "0 0 60px", fontSize: 12, color: "var(--muted)" }}>{name}</div>
      <div style={{ flex: 1, display: "flex", height: 26, borderRadius: 6, overflow: "hidden", background: "var(--bg)" }}>
        {segs.map((s) => {
          const v = valueOf(s);
          if (v <= 0) return null;
          return (
            <div
              key={s.type}
              title={label(s)}
              style={{
                width: `${v}%`,
                background: s.color,
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
