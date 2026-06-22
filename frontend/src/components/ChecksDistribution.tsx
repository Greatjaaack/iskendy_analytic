import { useQuery } from "@tanstack/react-query";
import { fetchCheckDistribution, fetchRevenueByChannel, rangeKey, type RangeSel } from "../api";
import { REFETCH_INTERVAL_MS, COLORS } from "../constants";
import { fmtInt } from "../format";

interface Props {
  range: RangeSel;
}

// Цвета по типу обслуживания (стабильные, читаемы в обеих темах).
const TYPE_COLORS: Record<string, string> = {
  "Доставка": COLORS.primary,
  "В зале": COLORS.good,
  "С собой": COLORS.warn,
};
const colorFor = (t: string) => TYPE_COLORS[t] ?? COLORS.accent;

/** Распределение чеков по типу обслуживания (#1): доставка / в зале / с собой.
 *  Данные — уникальные заказы по каналу (OLAP): сумма по типам = числу чеков.
 *  Рядом — доля выручки того же канала: видно перекос (напр. доставка = 30% чеков, но 50% выручки). */
export function ChecksDistribution({ range }: Props) {
  const q = useQuery({
    queryKey: ["check-distribution", rangeKey(range)],
    queryFn: () => fetchCheckDistribution(range),
    refetchInterval: REFETCH_INTERVAL_MS,
  });
  const revQ = useQuery({
    queryKey: ["revenue-by-channel", rangeKey(range)],
    queryFn: () => fetchRevenueByChannel(range),
    refetchInterval: REFETCH_INTERVAL_MS,
  });

  const rows = q.data?.data ?? [];

  // выручка по каналу за период: суммируем по дням. Названия каналов в by-channel — строчные
  // («доставка»/«с собой»/«в зале»), в check-distribution — с заглавной → матчим по lower-case.
  const revByChannel: Record<string, number> = {};
  (revQ.data?.channels ?? []).forEach((c) => {
    revByChannel[c.toLowerCase()] = (revQ.data?.data ?? []).reduce(
      (s, d) => s + Number(d[c] ?? 0),
      0,
    );
  });
  const totalRev = Object.values(revByChannel).reduce((s, v) => s + v, 0);

  return (
    <div style={{ background: "var(--card)", borderRadius: 12, padding: "20px 24px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 16 }}>
        <div style={{ color: "var(--text)", fontWeight: 600 }}>Чеки и выручка по типу обслуживания</div>
        <div style={{ color: "var(--muted)", fontSize: 13 }}>
          {q.data?.total ?? 0} чек. · {fmtInt(totalRev)} ₽
        </div>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        {rows.map((r) => {
          const rev = revByChannel[r.type.toLowerCase()] ?? 0;
          const revShare = totalRev ? Math.round((rev / totalRev) * 1000) / 10 : 0;
          const color = colorFor(r.type);
          return (
            <div key={r.type}>
              <div style={{ color: "var(--text)", fontSize: 13, fontWeight: 600, marginBottom: 6 }}>{r.type}</div>
              {/* чеки */}
              <Metric
                icon="🧾"
                label={`${r.count} чек.`}
                share={r.share}
                color={color}
              />
              {/* выручка того же канала */}
              <Metric
                icon="₽"
                label={`${fmtInt(rev)} ₽`}
                share={revShare}
                color={color}
              />
            </div>
          );
        })}
      </div>

      {!q.isLoading && rows.length === 0 && (
        <div style={{ color: "var(--muted)", textAlign: "center", padding: 16 }}>Нет данных</div>
      )}
    </div>
  );
}

/** Одна метрика канала: иконка + значение слева, доля-полоска, % справа. */
function Metric({ icon, label, share, color }: { icon: string; label: string; share: number; color: string }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
      <div style={{ flex: "0 0 130px", display: "flex", justifyContent: "space-between", fontSize: 12, color: "var(--muted)" }}>
        <span>{icon}</span>
        <span style={{ color: "var(--text)" }}>{label}</span>
      </div>
      <div style={{ flex: 1, height: 8, background: "var(--bg)", borderRadius: 4, overflow: "hidden" }}>
        <div style={{ width: `${share}%`, height: "100%", background: color }} />
      </div>
      <div style={{ flex: "0 0 46px", textAlign: "right", fontSize: 12, fontWeight: 600, color }}>
        {share}%
      </div>
    </div>
  );
}
