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
  // какая выпадашка открыта (одна за раз)
  const [openMenu, setOpenMenu] = useState<null | "cats" | "items">(null);
  // отмеченные галочками товары и категории (можно одновременно и то, и другое)
  const [selected, setSelected] = useState<Set<string>>(new Set());
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

  // список категорий (режим «Блюда» — по group_name блюд)
  const catList = useMemo(() => {
    const s = new Set<string>();
    for (const d of all) if (d.group_name) s.add(d.group_name);
    return [...s].sort((a, b) => a.localeCompare(b, "ru"));
  }, [all]);

  // товары для чеклиста (режим «Блюда»): сужены выбранными категориями
  // («товары из выбранных категорий»); если категории не выбраны — все товары
  const itemList = useMemo(() => {
    if (groupBy !== "dish") return [];
    const items = selCats.size > 0 ? all.filter((d) => selCats.has(d.group_name)) : all;
    return [...items].sort((a, b) => a.name.localeCompare(b.name, "ru"));
  }, [all, groupBy, selCats]);

  // строки таблицы: блюда выбранных категорий ∪ выбранные товары (режим «Блюда»);
  // в режиме «Категории» — отмеченные категории
  const rows = useMemo(() => {
    let r = all;
    if (groupBy === "category") {
      if (selected.size > 0) r = r.filter((d) => selected.has(d.name));
    } else {
      const useCats = selCats.size > 0, useItems = selected.size > 0;
      if (useCats || useItems) {
        r = r.filter((d) => (useCats && selCats.has(d.group_name)) || (useItems && selected.has(d.name)));
      }
    }
    const dir = sortDir === "asc" ? 1 : -1;
    return [...r].sort((a, b) => {
      // null (нет с/с) сортируем как самое маленькое, чтобы такие строки уходили вниз
      const va = a[sortKey] ?? -Infinity, vb = b[sortKey] ?? -Infinity;
      if (typeof va === "number" && typeof vb === "number") return (va - vb) * dir;
      return String(va).localeCompare(String(vb), "ru") * dir;
    });
  }, [all, selected, selCats, groupBy, sortKey, sortDir]);

  const toggleSel = (name: string) =>
    setSelected((p) => {
      const n = new Set(p);
      if (n.has(name)) n.delete(name); else n.add(name);
      return n;
    });
  const toggleCat = (name: string) =>
    setSelCats((p) => {
      const n = new Set(p);
      if (n.has(name)) n.delete(name); else n.add(name);
      return n;
    });
  const clearFilter = () => { setSelected(new Set()); setSelCats(new Set()); };

  const onSort = (k: SortKey) => {
    if (k === sortKey) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else { setSortKey(k); setSortDir(k === "name" || k === "group_name" ? "asc" : "desc"); }
  };

  const closeMenu = () => setOpenMenu(null);
  const filterCount = selCats.size + selected.size;
  // в режиме «Категории» галочки категорий = строки таблицы (множество `selected`)
  const catRows = useMemo(
    () => (groupBy === "category" ? [...all].sort((a, b) => a.name.localeCompare(b.name, "ru")) : []),
    [all, groupBy],
  );

  return (
    <div style={{ background: COLORS.card, borderRadius: 12, padding: "20px 24px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8, marginBottom: 12 }}>
        <div style={{ color: "var(--text)", fontWeight: 600 }}>Продажи блюд</div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {/* отдельные кнопки-выпадашки с галочками */}
          {groupBy === "dish" ? (
            <>
              <Dropdown
                label="Категории" count={selCats.size}
                open={openMenu === "cats"} onToggle={() => setOpenMenu(openMenu === "cats" ? null : "cats")}
                onClose={closeMenu} onClear={() => setSelCats(new Set())}
              >
                {catList.map((c) => (
                  <CheckRow key={c} label={c} checked={selCats.has(c)} onToggle={() => toggleCat(c)} />
                ))}
                {catList.length === 0 && <Empty />}
              </Dropdown>
              <Dropdown
                label="Товары" count={selected.size}
                open={openMenu === "items"} onToggle={() => setOpenMenu(openMenu === "items" ? null : "items")}
                onClose={closeMenu} onClear={() => setSelected(new Set())}
              >
                {itemList.map((d) => (
                  <CheckRow key={d.key} label={d.name} checked={selected.has(d.name)} onToggle={() => toggleSel(d.name)} />
                ))}
                {itemList.length === 0 && <Empty />}
              </Dropdown>
            </>
          ) : (
            <Dropdown
              label="Категории" count={selected.size}
              open={openMenu === "cats"} onToggle={() => setOpenMenu(openMenu === "cats" ? null : "cats")}
              onClose={closeMenu} onClear={() => setSelected(new Set())}
            >
              {catRows.map((d) => (
                <CheckRow key={d.key} label={d.name} checked={selected.has(d.name)} onToggle={() => toggleSel(d.name)} />
              ))}
              {catRows.length === 0 && <Empty />}
            </Dropdown>
          )}
          <div style={{ display: "flex", background: COLORS.bg, borderRadius: 8, padding: 3, gap: 2 }}>
            {(["dish", "category"] as DishGroupBy[]).map((g) => (
              <button
                key={g}
                onClick={() => { setGroupBy(g); clearFilter(); closeMenu(); }}
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

      {/* активные фильтры — чипы (видны и при закрытых выпадашках) */}
      {filterCount > 0 && (
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 12 }}>
          {[...selCats].map((name) => (
            <span key={`cat:${name}`} style={catChip}>
              <span style={catTag}>кат.</span> {name}
              <span onClick={() => toggleCat(name)} style={{ cursor: "pointer", color: COLORS.muted }}>✕</span>
            </span>
          ))}
          {[...selected].map((name) => (
            <span key={name} style={selChip}>
              {name}
              <span onClick={() => toggleSel(name)} style={{ cursor: "pointer", color: COLORS.muted }}>✕</span>
            </span>
          ))}
          <button onClick={clearFilter} style={{ ...selChip, cursor: "pointer", color: COLORS.muted }}>
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

/** Кнопка-выпадашка с галочками: триггер со стрелкой ▾ + панель чеклиста. */
function Dropdown({
  label, count, open, onToggle, onClose, onClear, children,
}: {
  label: string; count: number; open: boolean;
  onToggle: () => void; onClose: () => void; onClear: () => void;
  children: React.ReactNode;
}) {
  return (
    <div style={{ position: "relative" }}>
      <button onClick={onToggle} style={ddBtn(count > 0 || open)}>
        {label}{count > 0 ? ` (${count})` : ""} <span style={{ fontSize: 10, opacity: 0.7 }}>▾</span>
      </button>
      {open && (
        <>
          {/* подложка-перехватчик клика вне панели */}
          <div onClick={onClose} style={backdrop} />
          <div style={panel}>
            <div style={{ maxHeight: 260, overflowY: "auto", padding: "4px 0" }}>{children}</div>
            {count > 0 && (
              <div style={{ borderTop: `1px solid ${COLORS.grid}`, padding: "6px 12px", textAlign: "right" }}>
                <button onClick={onClear} style={linkBtn}>Сбросить</button>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}

/** Строка-галочка чеклиста. */
function CheckRow({ label, checked, onToggle }: { label: string; checked: boolean; onToggle: () => void }) {
  return (
    <label style={checkItem}>
      <input type="checkbox" checked={checked} onChange={onToggle} style={{ cursor: "pointer" }} />
      <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{label}</span>
    </label>
  );
}

const Empty = () => <div style={{ padding: "6px 12px", fontSize: 12, color: COLORS.muted }}>—</div>;

const td: React.CSSProperties = { padding: "8px 12px" };
const tdR: React.CSSProperties = { padding: "8px 12px", textAlign: "right" };

const ddBtn = (active: boolean): React.CSSProperties => ({
  padding: "6px 12px", borderRadius: 8, fontSize: 12, fontWeight: 600, cursor: "pointer",
  border: `1px solid ${active ? COLORS.primary : COLORS.grid}`,
  background: COLORS.bg, color: active ? COLORS.indigoText : "var(--text)", whiteSpace: "nowrap",
});
const backdrop: React.CSSProperties = { position: "fixed", inset: 0, zIndex: 9 };
const panel: React.CSSProperties = {
  position: "absolute", top: "calc(100% + 4px)", right: 0, zIndex: 10, width: 240,
  background: COLORS.bg, border: `1px solid ${COLORS.grid}`, borderRadius: 8,
  boxShadow: "0 8px 24px rgba(0,0,0,0.4)", overflow: "hidden",
};
const checkItem: React.CSSProperties = {
  display: "flex", alignItems: "center", gap: 8, padding: "5px 12px",
  fontSize: 13, color: "var(--text)", cursor: "pointer",
};
const linkBtn: React.CSSProperties = {
  background: "none", border: "none", cursor: "pointer", fontSize: 12, fontWeight: 600,
  color: COLORS.indigoText, padding: 0,
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
