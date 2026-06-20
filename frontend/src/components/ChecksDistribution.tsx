import { useQuery } from "@tanstack/react-query";
import { fetchCheckDistribution, rangeKey, type RangeSel } from "../api";
import { REFETCH_INTERVAL_MS, COLORS } from "../constants";

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
 *  Данные — уникальные заказы по каналу (OLAP): сумма по типам = числу чеков. */
export function ChecksDistribution({ range }: Props) {
  const q = useQuery({
    queryKey: ["check-distribution", rangeKey(range)],
    queryFn: () => fetchCheckDistribution(range),
    refetchInterval: REFETCH_INTERVAL_MS,
  });

  const rows = q.data?.data ?? [];

  return (
    <div style={{ background: "var(--card)", borderRadius: 12, padding: "20px 24px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 16 }}>
        <div style={{ color: "var(--text)", fontWeight: 600 }}>Чеки по типу обслуживания</div>
        <div style={{ color: "var(--muted)", fontSize: 13 }}>всего: {q.data?.total ?? 0}</div>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {rows.map((r) => (
          <div key={r.type}>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, marginBottom: 4 }}>
              <span style={{ color: "var(--text)" }}>{r.type}</span>
              <span style={{ color: "var(--muted)" }}>
                {r.count} <span style={{ color: colorFor(r.type), fontWeight: 600 }}>· {r.share}%</span>
              </span>
            </div>
            <div style={{ height: 8, background: "var(--bg)", borderRadius: 4, overflow: "hidden" }}>
              <div style={{ width: `${r.share}%`, height: "100%", background: colorFor(r.type) }} />
            </div>
          </div>
        ))}
      </div>

      {!q.isLoading && rows.length === 0 && (
        <div style={{ color: "var(--muted)", textAlign: "center", padding: 16 }}>Нет данных</div>
      )}
    </div>
  );
}
