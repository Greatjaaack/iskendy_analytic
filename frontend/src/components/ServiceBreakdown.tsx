import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchServiceBreakdown, rangeKey, type RangeSel, type DishGroupBy } from "../api";
import { REFETCH_INTERVAL_MS, COLORS } from "../constants";
import { fmtInt } from "../format";

interface Props {
  range: RangeSel;
}

// Цвет канала (совпадает с «Чеки по типу обслуживания»).
const channelColor = (ch: string) =>
  ch === "доставка" ? COLORS.primary : ch === "с собой" ? COLORS.warn : COLORS.good;

/** Сколько каждого блюда/категории берут в зале / с собой / в доставку (#4).
 *  Данные — OLAP SALES (блюдо × тип заказа), `/api/dishes/service-breakdown`. */
export function ServiceBreakdown({ range }: Props) {
  const [group, setGroup] = useState<DishGroupBy>("dish");
  const [search, setSearch] = useState("");

  const q = useQuery({
    queryKey: ["service-breakdown", rangeKey(range), group],
    queryFn: () => fetchServiceBreakdown(range, group),
    refetchInterval: REFETCH_INTERVAL_MS,
  });

  const channels = q.data?.channels ?? [];
  const rows = useMemo(() => {
    const all = q.data?.data ?? [];
    const s = search.trim().toLowerCase();
    return s ? all.filter((r) => r.name.toLowerCase().includes(s)) : all;
  }, [q.data, search]);

  return (
    <div style={{ background: COLORS.card, borderRadius: 12, padding: "20px 24px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8, marginBottom: 12 }}>
        <div style={{ color: "var(--text)", fontWeight: 600 }}>Продажи по статусам</div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <input
            placeholder={group === "category" ? "Поиск категорий…" : "Поиск блюд…"}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{ padding: "6px 10px", borderRadius: 8, border: `1px solid ${COLORS.grid}`, background: COLORS.bg, color: "var(--text)", fontSize: 12, width: 200 }}
          />
          <div style={{ display: "flex", background: COLORS.bg, borderRadius: 8, padding: 3, gap: 2 }}>
            {(["dish", "category"] as DishGroupBy[]).map((g) => (
              <button
                key={g}
                onClick={() => setGroup(g)}
                style={{
                  padding: "5px 12px", borderRadius: 6, border: "none", cursor: "pointer",
                  fontSize: 12, fontWeight: 600,
                  background: group === g ? COLORS.primary : "transparent",
                  color: group === g ? "var(--text)" : COLORS.muted,
                }}
              >
                {g === "dish" ? "Блюда" : "Категории"}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr style={{ color: COLORS.muted, textAlign: "left" }}>
              <th style={td}>{group === "category" ? "Категория" : "Блюдо"}</th>
              {channels.map((ch) => (
                <th key={ch} style={{ ...tdR, color: channelColor(ch) }}>{ch}</th>
              ))}
              <th style={tdR}>всего</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.name} style={{ borderTop: `1px solid ${COLORS.grid}` }}>
                <td style={td}>{r.name}</td>
                {channels.map((ch) => {
                  const v = Number(r[ch] ?? 0);
                  const pct = r.total ? Math.round((v / r.total) * 100) : 0;
                  return (
                    <td key={ch} style={tdR}>
                      {fmtInt(v)}
                      <span style={{ color: "var(--muted)", marginLeft: 6 }}>{pct}%</span>
                    </td>
                  );
                })}
                <td style={{ ...tdR, fontWeight: 600 }}>{fmtInt(r.total)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {q.isLoading && <div style={{ color: COLORS.muted, textAlign: "center", padding: 24 }}>Загрузка…</div>}
        {!q.isLoading && rows.length === 0 && (
          <div style={{ color: COLORS.muted, textAlign: "center", padding: 24 }}>Нет данных</div>
        )}
      </div>
    </div>
  );
}

const td: React.CSSProperties = { padding: "8px 12px" };
const tdR: React.CSSProperties = { padding: "8px 12px", textAlign: "right" };
