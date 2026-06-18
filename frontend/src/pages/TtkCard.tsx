import { useQuery } from "@tanstack/react-query";
import { useParams, Link } from "react-router-dom";
import { fetchTtk } from "../api";
import { COLORS } from "../constants";
import { fmtNum } from "../format";

/** Карточка ТТК: состав (сырьё/п-ф), нормы, потери и себестоимость; переход в дочерние п/ф. */
export function TtkCard() {
  const { id } = useParams();
  const tid = Number(id);
  const q = useQuery({ queryKey: ["ttk", tid], queryFn: () => fetchTtk(tid) });

  if (q.isLoading) return <div style={{ padding: 24, color: "var(--muted)" }}>Загрузка...</div>;
  if (!q.data) return <div style={{ padding: 24, color: COLORS.bad }}>Не найдено</div>;
  const t = q.data;

  return (
    <div style={{ padding: 24, color: "var(--text)" }}>
      <Link to="/nomenclature" style={{ color: "var(--muted)", fontSize: 13, textDecoration: "none" }}>
        ← Номенклатура ↔ ТТК
      </Link>
      <div style={{ display: "flex", alignItems: "center", gap: 10, margin: "8px 0 4px" }}>
        <div style={{ fontSize: 22, fontWeight: 700 }}>{t.name}</div>
        {t.is_semi && <span style={{ color: COLORS.warn, fontSize: 13 }}>п/ф</span>}
      </div>
      <div style={{ color: "var(--muted)", fontSize: 13, marginBottom: 20 }}>
        {t.category || "без категории"} · выход {t.yield_qty ? `${fmtNum(t.yield_qty)} ${t.yield_unit}` : "—"} ·
        себестоимость <span style={{ color: COLORS.indigoText, fontWeight: 600 }}>{fmtNum(t.cost_total)} ₽</span>
      </div>

      <div style={{ background: "var(--card)", borderRadius: 12, padding: "16px 20px" }}>
        <div style={{ fontWeight: 600, marginBottom: 12 }}>Состав</div>
        <table style={tbl}>
          <thead>
            <tr style={th}>
              <td style={td}>Ингредиент / п/ф</td>
              <td style={{ ...td, textAlign: "right" }}>Брутто</td>
              <td style={{ ...td, textAlign: "right" }}>Нетто</td>
              <td style={td}>Ед.</td>
              <td style={{ ...td, textAlign: "right" }}>% потери</td>
              <td style={{ ...td, textAlign: "right" }}>С/С, ₽</td>
            </tr>
          </thead>
          <tbody>
            {t.lines.map((l) => (
              <tr key={l.id} style={{ borderTop: "1px solid var(--grid)" }}>
                <td style={td}>
                  {l.child_ttk_id ? (
                    <Link to={`/ttk/${l.child_ttk_id}`} style={{ color: COLORS.warn, textDecoration: "none" }}>
                      {l.raw_name} ↗
                    </Link>
                  ) : (
                    l.raw_name
                  )}
                </td>
                <td style={{ ...td, textAlign: "right" }}>{fmtNum(l.gross)}</td>
                <td style={{ ...td, textAlign: "right" }}>{fmtNum(l.net)}</td>
                <td style={{ ...td, color: "var(--muted)" }}>{l.unit}</td>
                <td style={{ ...td, textAlign: "right", color: "var(--muted)" }}>{l.waste_pct ? `${l.waste_pct}%` : "—"}</td>
                <td style={{ ...td, textAlign: "right", color: COLORS.indigoText }}>{fmtNum(l.cost_rub)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

const tbl: React.CSSProperties = { width: "100%", borderCollapse: "collapse", fontSize: 13 };
const th: React.CSSProperties = { color: "var(--muted)", textAlign: "left" };
const td: React.CSSProperties = { padding: "7px 10px" };
