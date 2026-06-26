import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { fetchTtkList, fetchIngredients } from "../api";
import { DishTtkMapping } from "../components/DishTtkMapping";
import { COLORS } from "../constants";
import { fmtNum } from "../format";

/** Номенклатура: вкладки ТТК, Ингредиенты и Блюда↔ТТК (привязка продаж к тех-картам). */
export function Nomenclature() {
  const [tab, setTab] = useState<"ttk" | "ing" | "map">("ttk");
  const ttkQ = useQuery({ queryKey: ["ttk"], queryFn: fetchTtkList });
  const ingQ = useQuery({ queryKey: ["ingredients"], queryFn: fetchIngredients });

  return (
    <div className="page" style={{ color: "var(--text)" }}>
      <div style={{ fontSize: 22, fontWeight: 700, marginBottom: 16 }}>Номенклатура ↔ ТТК</div>

      <div style={{ display: "flex", gap: 4, background: "var(--card)", borderRadius: 8, padding: 4, width: "fit-content", marginBottom: 16 }}>
        <Tab active={tab === "ttk"} onClick={() => setTab("ttk")}>
          ТТК ({ttkQ.data?.length ?? 0})
        </Tab>
        <Tab active={tab === "ing"} onClick={() => setTab("ing")}>
          Ингредиенты ({ingQ.data?.length ?? 0})
        </Tab>
        <Tab active={tab === "map"} onClick={() => setTab("map")}>
          Блюда ↔ ТТК
        </Tab>
      </div>

      {tab === "map" && <DishTtkMapping />}

      {tab === "ttk" && (
        <div style={card}>
          <table style={tbl}>
            <thead>
              <tr style={th}>
                <td style={td}>Название</td>
                <td style={td}>Категория</td>
                <td style={td}>Тип</td>
                <td style={{ ...td, textAlign: "right" }}>Выход</td>
                <td style={{ ...td, textAlign: "right" }}>Себестоимость, ₽</td>
              </tr>
            </thead>
            <tbody>
              {ttkQ.data?.map((t) => (
                <tr key={t.id} style={{ borderTop: "1px solid var(--grid)" }}>
                  <td style={td}>
                    <Link to={`/ttk/${t.id}`} style={{ color: "var(--text)", textDecoration: "none" }}>
                      {t.name}
                    </Link>
                  </td>
                  <td style={{ ...td, color: "var(--muted)" }}>{t.category || "—"}</td>
                  <td style={td}>
                    {t.is_semi ? (
                      <span style={{ color: COLORS.warn, fontSize: 12 }}>п/ф</span>
                    ) : (
                      <span style={{ color: COLORS.good, fontSize: 12 }}>блюдо</span>
                    )}
                  </td>
                  <td style={{ ...td, textAlign: "right", color: "var(--muted)" }}>
                    {t.yield_qty ? `${fmtNum(t.yield_qty)} ${t.yield_unit}` : "—"}
                  </td>
                  <td style={{ ...td, textAlign: "right", color: COLORS.indigoText, fontWeight: 600 }}>{fmtNum(t.cost_total)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {tab === "ing" && (
        <div style={card}>
          <table style={tbl}>
            <thead>
              <tr style={th}>
                <td style={td}>Ингредиент</td>
                <td style={td}>Ед.</td>
                <td style={{ ...td, textAlign: "right" }}>Цен поставщиков</td>
                <td style={td}>iiko</td>
              </tr>
            </thead>
            <tbody>
              {ingQ.data?.map((i) => (
                <tr key={i.id} style={{ borderTop: "1px solid var(--grid)" }}>
                  <td style={td}>{i.name}</td>
                  <td style={{ ...td, color: "var(--muted)" }}>{i.unit}</td>
                  <td style={{ ...td, textAlign: "right" }}>{i.prices}</td>
                  <td style={{ ...td, color: i.iiko_product_id ? COLORS.good : "var(--muted)" }}>
                    {i.iiko_product_id ? "привязан" : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function Tab({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      style={{
        padding: "6px 16px", borderRadius: 6, border: "none", cursor: "pointer",
        fontSize: 13, fontWeight: 600,
        background: active ? COLORS.primary : "transparent", color: active ? "var(--text)" : "var(--muted)",
      }}
    >
      {children}
    </button>
  );
}

const card: React.CSSProperties = { background: "var(--card)", borderRadius: 12, padding: "16px 20px" };
const tbl: React.CSSProperties = { width: "100%", borderCollapse: "collapse", fontSize: 13 };
const th: React.CSSProperties = { color: "var(--muted)", textAlign: "left" };
const td: React.CSSProperties = { padding: "7px 10px" };
