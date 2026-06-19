import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchServiceBreakdown, rangeKey, type RangeSel, type DishGroupBy } from "../api";
import { REFETCH_INTERVAL_MS, COLORS } from "../constants";
import { fmtInt } from "../format";

interface Props {
  range: RangeSel;
}

const channelColor = (ch: string) =>
  ch === "доставка" ? COLORS.primary : ch === "с собой" ? COLORS.warn : COLORS.good;

/** Что и в каком статусе продаётся: блюдо/категория × зал / с собой / доставка (#4),
 *  с долей позиции в продажах периода и сортировкой по любой колонке.
 *  Данные — OLAP SALES, `/api/dishes/service-breakdown`. */
export function ServiceBreakdown({ range }: Props) {
  const [group, setGroup] = useState<DishGroupBy>("dish");
  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState<string>("total"); // "name" | канал | "total"
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  const q = useQuery({
    queryKey: ["service-breakdown", rangeKey(range), group],
    queryFn: () => fetchServiceBreakdown(range, group),
    refetchInterval: REFETCH_INTERVAL_MS,
  });

  const channels = q.data?.channels ?? [];
  // итог по всем позициям периода — для доли позиции «в рамках периода» (#3)
  const grandTotal = useMemo(
    () => (q.data?.data ?? []).reduce((s, r) => s + Number(r.total ?? 0), 0),
    [q.data],
  );

  const onSort = (k: string) => {
    if (k === sortKey) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setSortKey(k);
      setSortDir(k === "name" ? "asc" : "desc");
    }
  };

  const rows = useMemo(() => {
    const all = q.data?.data ?? [];
    const s = search.trim().toLowerCase();
    const filtered = s ? all.filter((r) => r.name.toLowerCase().includes(s)) : all;
    const dir = sortDir === "asc" ? 1 : -1;
    // «доля» сортируется по total (монотонна ему: total/grandTotal)
    const key = sortKey === "share" ? "total" : sortKey;
    return [...filtered].sort((a, b) => {
      if (key === "name") return String(a.name).localeCompare(String(b.name), "ru") * dir;
      return (Number(a[key] ?? 0) - Number(b[key] ?? 0)) * dir;
    });
  }, [q.data, search, sortKey, sortDir]);

  const arrow = (k: string) => (sortKey === k ? (sortDir === "asc" ? " ↑" : " ↓") : "");

  return (
    <div style={{ background: COLORS.card, borderRadius: 12, padding: "20px 24px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8, marginBottom: 12 }}>
        <div style={{ color: "var(--text)", fontWeight: 600 }}>Что продаётся по статусам</div>
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
              <th style={thSort} onClick={() => onSort("name")}>
                {group === "category" ? "Категория" : "Блюдо"}{arrow("name")}
              </th>
              {channels.map((ch) => (
                <th key={ch} style={{ ...thSort, textAlign: "right", color: channelColor(ch) }} onClick={() => onSort(ch)}>
                  {ch}{arrow(ch)}
                </th>
              ))}
              <th style={{ ...thSort, textAlign: "right" }} onClick={() => onSort("total")}>всего{arrow("total")}</th>
              <th style={{ ...thSort, textAlign: "right" }} onClick={() => onSort("share")}>доля{arrow("share")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              // доля позиции в продажах всего периода (по количеству), а не внутри статуса (#3)
              const share = grandTotal ? Math.round((Number(r.total) / grandTotal) * 100) : 0;
              return (
                <tr key={r.name} style={{ borderTop: `1px solid ${COLORS.grid}` }}>
                  <td style={td}>{r.name}</td>
                  {channels.map((ch) => (
                    <td key={ch} style={tdR}>{fmtInt(Number(r[ch] ?? 0))}</td>
                  ))}
                  <td style={{ ...tdR, fontWeight: 600 }}>{fmtInt(r.total)}</td>
                  <td style={{ ...tdR, color: "var(--muted)" }}>{share}%</td>
                </tr>
              );
            })}
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
const thSort: React.CSSProperties = { padding: "8px 12px", cursor: "pointer", userSelect: "none", whiteSpace: "nowrap" };
