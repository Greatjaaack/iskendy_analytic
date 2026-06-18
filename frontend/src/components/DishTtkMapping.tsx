import { useMemo } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchDishes, fetchTtkList, fetchDishMappings, saveDishMapping, deleteDishMapping,
  type DishMapping,
} from "../api";

const norm = (s: string) => s.trim().toLowerCase().replace(/ё/g, "е").replace(/\s+/g, " ");

/** Привязка проданных блюд (названия из продаж iiko) к ТТК — чтобы считалась с/с по блюду.
 *  POS-названия не совпадают с названиями ТТК, поэтому сопоставляем вручную один раз. */
export function DishTtkMapping() {
  const qc = useQueryClient();
  // список проданных блюд за месяц (источник названий продаж)
  const dishesQ = useQuery({ queryKey: ["dishes", "month", "dish"], queryFn: () => fetchDishes({ period: "month" }, "dish") });
  const ttkQ = useQuery({ queryKey: ["ttk"], queryFn: fetchTtkList });
  const mapQ = useQuery({ queryKey: ["dish-mappings"], queryFn: fetchDishMappings });

  // ТТК, отсортированные: сперва с известной с/с порции
  const ttkOptions = useMemo(
    () => [...(ttkQ.data ?? [])].sort((a, b) => a.name.localeCompare(b.name, "ru")),
    [ttkQ.data],
  );

  // текущая привязка по нормализованному имени продажи
  const mapByName = useMemo(() => {
    const m = new Map<string, DishMapping>();
    (mapQ.data ?? []).forEach((x) => m.set(norm(x.sale_name), x));
    return m;
  }, [mapQ.data]);

  const onChange = async (saleName: string, ttkId: string) => {
    const existing = mapByName.get(norm(saleName));
    if (ttkId) await saveDishMapping(saleName, Number(ttkId));
    else if (existing) await deleteDishMapping(existing.id);
    await qc.invalidateQueries({ queryKey: ["dish-mappings"] });
    await qc.invalidateQueries({ queryKey: ["dishes"] });
  };

  const names = useMemo(
    () => [...new Set((dishesQ.data?.data ?? []).map((d) => d.name))].sort((a, b) => a.localeCompare(b, "ru")),
    [dishesQ.data],
  );

  return (
    <div style={{ background: "var(--card)", borderRadius: 12, padding: "16px 20px" }}>
      <div style={{ color: "var(--muted)", fontSize: 13, marginBottom: 12 }}>
        Свяжите название блюда из продаж с тех-картой — тогда в «Продажах блюд» появится с/с %.
      </div>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
        <thead>
          <tr style={{ color: "var(--muted)", textAlign: "left" }}>
            <td style={td}>Блюдо в продажах</td>
            <td style={td}>Тех-карта (ТТК)</td>
            <td style={{ ...td, textAlign: "right" }}>С/с порции, ₽</td>
          </tr>
        </thead>
        <tbody>
          {names.map((name) => {
            const cur = mapByName.get(norm(name));
            return (
              <tr key={name} style={{ borderTop: "1px solid var(--grid)" }}>
                <td style={td}>{name}</td>
                <td style={td}>
                  <select
                    value={cur?.ttk_id ?? ""}
                    onChange={(e) => onChange(name, e.target.value)}
                    style={{ width: "100%", maxWidth: 360, padding: "5px 8px", borderRadius: 6, border: "1px solid var(--grid)", background: "var(--bg)", color: "var(--text)", fontSize: 13 }}
                  >
                    <option value="">— не привязано —</option>
                    {ttkOptions.map((t) => (
                      <option key={t.id} value={t.id}>{t.name}</option>
                    ))}
                  </select>
                </td>
                <td style={{ ...td, textAlign: "right", color: cur?.cost_full ? "var(--text)" : "var(--muted)" }}>
                  {cur?.cost_full != null ? cur.cost_full.toFixed(2) : "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {(dishesQ.isLoading || ttkQ.isLoading) && <div style={{ color: "var(--muted)", padding: 16 }}>Загрузка…</div>}
    </div>
  );
}

const td: React.CSSProperties = { padding: "7px 10px" };
