import { useMemo, useState } from "react";
import { useLiveQuery } from "../hooks";
import { fetchDishes, rangeKey, type RangeSel, type DishGroupBy, type DishRow } from "../api";
import { MARGIN_GOOD, MARGIN_OK, COLORS } from "../constants";
import { fmtInt } from "../format";

interface Props {
  range: RangeSel;
  withDelivery?: boolean;
}

type SortKey = keyof Pick<DishRow, "name" | "group_name" | "quantity" | "qty_share" | "revenue" | "revenue_share" | "cost_sum" | "cost_pct" | "margin_pct">;

export function DishTable({ range, withDelivery = true }: Props) {
  const [groupBy, setGroupBy] = useState<DishGroupBy>("dish");
  const [search, setSearch] = useState("");
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  // выбранные категории (режим «Блюда»): можно одновременно набрать и категории,
  // и отдельные товары — таблица показывает блюда выбранных категорий ∪ выбранные блюда
  const [selCats, setSelCats] = useState<Set<string>>(new Set());
  const [sortKey, setSortKey] = useState<SortKey>("revenue");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  const q = useLiveQuery({
    queryKey: ["dishes", rangeKey(range), groupBy, withDelivery],
    queryFn: () => fetchDishes(range, groupBy, withDelivery),
  });

  // sortable=false — колонки фактического с/с (пока не считаем, показываем «—»; позже
  // подключим расчёт по накладным/расходу). «Кост %» = с/с ÷ цена реализации (=cost_pct).
  const cols: { key: string; label: string; num?: boolean; sortable?: boolean }[] = [
    { key: "name", label: groupBy === "category" ? "Категория" : "Блюдо" },
    ...(groupBy === "dish" ? [{ key: "group_name", label: "Группа" }] : []),
    { key: "quantity", label: "Кол-во", num: true },
    { key: "revenue", label: "Выручка", num: true },
    { key: "qty_share", label: "Доля кол-ва", num: true },
    { key: "revenue_share", label: "Доля продаж", num: true },
    { key: "cost_sum", label: "План с/с", num: true },
    { key: "cost_sum_fact", label: "Факт с/с", num: true, sortable: false },
    { key: "cost_pct", label: "План кост %", num: true },
    { key: "cost_pct_fact", label: "Факт кост %", num: true, sortable: false },
    { key: "cost_delta", label: "Δ кост", num: true, sortable: false },
    { key: "margin_pct", label: "Маржа %", num: true },
  ];

  const all = useMemo(() => q.data?.data ?? [], [q.data]);

  // список категорий блюд (режим «Блюда»: фильтр по group_name)
  const catList = useMemo(() => {
    const s = new Set<string>();
    for (const d of all) if (d.group_name) s.add(d.group_name);
    return [...s].sort((a, b) => a.localeCompare(b, "ru"));
  }, [all]);

  // подсказки-категории дропдауна (только режим «Блюда»), исключая уже выбранные
  const catOptions = useMemo(() => {
    if (groupBy !== "dish") return [];
    const s = search.trim().toLowerCase();
    return catList.filter((c) => !selCats.has(c) && (!s || c.toLowerCase().includes(s)));
  }, [groupBy, catList, search, selCats]);

  // подсказки-блюда: по поиску, исключая выбранные; в режиме «Блюда» сужаются
  // выбранными категориями («товары из выбранных категорий»)
  const options = useMemo(() => {
    const s = search.trim().toLowerCase();
    return all
      .filter(
        (d) =>
          !selected.has(d.name) &&
          (!s || d.name.toLowerCase().includes(s)) &&
          (groupBy !== "dish" || selCats.size === 0 || selCats.has(d.group_name)),
      )
      .slice(0, 30);
  }, [all, search, selected, groupBy, selCats]);

  // строки таблицы: при выборе — блюда выбранных категорий ∪ выбранные блюда;
  // иначе фильтр по тексту
  const rows = useMemo(() => {
    let r = all;
    const useCats = groupBy === "dish" && selCats.size > 0;
    const hasSel = selected.size > 0 || useCats;
    if (hasSel) {
      r = r.filter((d) => selected.has(d.name) || (useCats && selCats.has(d.group_name)));
    } else if (search.trim()) {
      const f = search.toLowerCase();
      r = r.filter((d) => d.name.toLowerCase().includes(f) || d.group_name.toLowerCase().includes(f));
    }
    const dir = sortDir === "asc" ? 1 : -1;
    return [...r].sort((a, b) => {
      // null (нет с/с) сортируем как самое маленькое, чтобы такие строки уходили вниз
      const va = a[sortKey] ?? -Infinity, vb = b[sortKey] ?? -Infinity;
      if (typeof va === "number" && typeof vb === "number") return (va - vb) * dir;
      return String(va).localeCompare(String(vb), "ru") * dir;
    });
  }, [all, search, selected, selCats, groupBy, sortKey, sortDir]);

  const addSel = (name: string) => {
    setSelected((p) => new Set(p).add(name));
    setSearch("");
  };
  const removeSel = (name: string) =>
    setSelected((p) => {
      const n = new Set(p);
      n.delete(name);
      return n;
    });
  const addCat = (name: string) => {
    setSelCats((p) => new Set(p).add(name));
    setSearch("");
  };
  const removeCat = (name: string) =>
    setSelCats((p) => {
      const n = new Set(p);
      n.delete(name);
      return n;
    });

  const onSort = (k: SortKey) => {
    if (k === sortKey) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else { setSortKey(k); setSortDir(k === "name" || k === "group_name" ? "asc" : "desc"); }
  };

  return (
    <div style={{ background: COLORS.card, borderRadius: 12, padding: "20px 24px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8, marginBottom: 12 }}>
        <div style={{ color: "var(--text)", fontWeight: 600 }}>Продажи блюд</div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <div style={{ position: "relative" }}>
            <input
              placeholder={groupBy === "category" ? "Поиск категорий…" : "Поиск категорий и блюд…"}
              value={search}
              onChange={(e) => { setSearch(e.target.value); setOpen(true); }}
              onFocus={() => setOpen(true)}
              onBlur={() => setTimeout(() => setOpen(false), 150)}
              style={{ padding: "6px 10px", borderRadius: 8, border: `1px solid ${COLORS.grid}`, background: COLORS.bg, color: "var(--text)", fontSize: 12, width: 200 }}
            />
            {open && (catOptions.length > 0 || options.length > 0) && (
              <div style={dropdown}>
                {catOptions.map((c) => (
                  <div key={`cat:${c}`} onMouseDown={() => addCat(c)} style={dropItem}>
                    <span style={catTag}>категория</span> {c}
                  </div>
                ))}
                {options.map((o) => (
                  <div key={o.key} onMouseDown={() => addSel(o.name)} style={dropItem}>
                    {o.name}
                  </div>
                ))}
              </div>
            )}
          </div>
          <div style={{ display: "flex", background: COLORS.bg, borderRadius: 8, padding: 3, gap: 2 }}>
            {(["dish", "category"] as DishGroupBy[]).map((g) => (
              <button
                key={g}
                onClick={() => { setGroupBy(g); setSelected(new Set()); setSelCats(new Set()); }}
                style={{
                  padding: "5px 12px", borderRadius: 6, border: "none", cursor: "pointer",
                  fontSize: 12, fontWeight: 600,
                  background: groupBy === g ? COLORS.primary : "transparent",
                  color: groupBy === g ? "var(--text)" : COLORS.muted,
                }}
              >
                {g === "dish" ? "Блюда" : "Категории"}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* выбранные категории + позиции (мультивыбор) */}
      {(selected.size > 0 || selCats.size > 0) && (
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 12 }}>
          {[...selCats].map((name) => (
            <span key={`cat:${name}`} style={catChip}>
              <span style={catTag}>кат.</span> {name}
              <span onClick={() => removeCat(name)} style={{ cursor: "pointer", color: COLORS.muted }}>✕</span>
            </span>
          ))}
          {[...selected].map((name) => (
            <span key={name} style={selChip}>
              {name}
              <span onClick={() => removeSel(name)} style={{ cursor: "pointer", color: COLORS.muted }}>✕</span>
            </span>
          ))}
          <button onClick={() => { setSelected(new Set()); setSelCats(new Set()); }} style={{ ...selChip, cursor: "pointer", color: COLORS.muted }}>
            очистить
          </button>
        </div>
      )}

      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr style={{ color: COLORS.muted, textAlign: "left" }}>
              {cols.map((c) => {
                const sortable = c.sortable !== false;
                return (
                  <th
                    key={c.key}
                    onClick={sortable ? () => onSort(c.key as SortKey) : undefined}
                    style={{ padding: "8px 12px", textAlign: c.num ? "right" : "left", cursor: sortable ? "pointer" : "default", userSelect: "none", whiteSpace: "nowrap" }}
                  >
                    {c.label}{sortable && sortKey === c.key ? (sortDir === "asc" ? " ↑" : " ↓") : ""}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {rows.map((d) => (
              <tr key={d.key} style={{ borderTop: `1px solid ${COLORS.grid}` }}>
                <td style={td}>{d.name}</td>
                {groupBy === "dish" && <td style={{ ...td, color: COLORS.muted }}>{d.group_name}</td>}
                <td style={tdR}>{d.quantity}</td>
                <td style={tdR}>{fmtInt(d.revenue)}</td>
                <td style={{ ...tdR, color: COLORS.muted }}>{d.qty_share}%</td>
                <td style={{ ...tdR, color: COLORS.indigoText }}>{d.revenue_share}%</td>
                <td style={{ ...tdR, color: d.has_cost ? "var(--text)" : COLORS.muted }}>
                  {d.has_cost ? fmtInt(d.cost_sum) : "—"}
                </td>
                {/* факт с/с — пока не считаем (заглушка) */}
                <td style={{ ...tdR, color: COLORS.muted }} title="Фактический с/с — появится после учёта накладных">—</td>
                <td style={{ ...tdR, color: COLORS.muted }}>{d.cost_pct == null ? "—" : `${d.cost_pct}%`}</td>
                {/* факт кост % / Δ — пока не считаем (заглушки) */}
                <td style={{ ...tdR, color: COLORS.muted }} title="Фактический кост — появится после учёта накладных">—</td>
                <td style={{ ...tdR, color: COLORS.muted }} title="Дельта план↔факт — появится после учёта накладных">—</td>
                {d.margin_pct == null ? (
                  <td style={{ ...tdR, color: COLORS.muted }} title="Нет с/с — нужна привязка ТТК">—</td>
                ) : (
                  <td style={{ ...tdR, color: d.margin_pct >= MARGIN_GOOD ? COLORS.good : d.margin_pct >= MARGIN_OK ? COLORS.warn : COLORS.bad, fontWeight: 600 }}>
                    {d.margin_pct}%
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
        {q.isLoading && <div style={{ color: COLORS.muted, textAlign: "center", padding: 32 }}>Загрузка…</div>}
        {!q.isLoading && rows.length === 0 && (
          <div style={{ color: COLORS.muted, textAlign: "center", padding: 32 }}>Нет данных</div>
        )}
      </div>
    </div>
  );
}

const td: React.CSSProperties = { padding: "8px 12px" };
const tdR: React.CSSProperties = { padding: "8px 12px", textAlign: "right" };
const dropdown: React.CSSProperties = {
  position: "absolute", top: "calc(100% + 4px)", left: 0, right: 0, zIndex: 10,
  background: COLORS.bg, border: `1px solid ${COLORS.grid}`, borderRadius: 8,
  maxHeight: 240, overflowY: "auto", boxShadow: "0 8px 24px rgba(0,0,0,0.4)",
};
const dropItem: React.CSSProperties = {
  padding: "8px 12px", fontSize: 13, color: "var(--text)", cursor: "pointer", whiteSpace: "nowrap",
};
const selChip: React.CSSProperties = {
  display: "inline-flex", alignItems: "center", gap: 6, padding: "4px 10px",
  borderRadius: 6, background: COLORS.bg, border: `1px solid ${COLORS.grid}`,
  fontSize: 12, color: "var(--text)",
};
// чип категории — акцентная рамка, чтобы отличать от чипа товара
const catChip: React.CSSProperties = { ...selChip, borderColor: COLORS.primary };
const catTag: React.CSSProperties = {
  fontSize: 10, textTransform: "uppercase", letterSpacing: 0.4,
  color: COLORS.primary, fontWeight: 700,
};
