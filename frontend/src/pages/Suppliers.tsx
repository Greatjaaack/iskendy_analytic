import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { fetchSuppliers, runImport, suppliersExportUrl } from "../api";
import { COLORS } from "../constants";

/** Список поставщиков (таблица) + кнопки импорта из файла и создания нового. */
export function Suppliers() {
  const qc = useQueryClient();
  const [importing, setImporting] = useState(false);
  const [msg, setMsg] = useState("");
  const q = useQuery({ queryKey: ["suppliers"], queryFn: fetchSuppliers });

  const handleImport = async () => {
    setImporting(true);
    setMsg("");
    try {
      const r = await runImport();
      setMsg(`Импорт: поставщиков ${r.imported.suppliers}, ингредиентов ${r.imported.ingredients}, цен ${r.imported.prices}, ТТК ${r.imported.ttk}`);
      qc.invalidateQueries();
    } catch {
      setMsg("Ошибка импорта");
    }
    setImporting(false);
  };

  return (
    <div style={{ padding: 24, color: "var(--text)" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
        <div style={{ fontSize: 22, fontWeight: 700 }}>Поставщики</div>
        <div style={{ display: "flex", gap: 8 }}>
          <button onClick={handleImport} disabled={importing} style={btnGhost}>
            {importing ? "Импорт..." : "↧ Импорт из файла"}
          </button>
          <a href={suppliersExportUrl()} style={{ ...btnGhost, textDecoration: "none" }}>
            ⭳ Выгрузить в Excel
          </a>
          <Link to="/suppliers/new" style={{ ...btnPrimary, textDecoration: "none" }}>
            + Новый поставщик
          </Link>
        </div>
      </div>

      {msg && <div style={{ color: COLORS.indigoText, fontSize: 13, marginBottom: 16 }}>{msg}</div>}
      {q.isLoading && <div style={{ color: "var(--muted)" }}>Загрузка...</div>}

      {q.data && q.data.length > 0 && (
        <div style={{ background: "var(--card)", borderRadius: 12, padding: "8px 12px" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ color: "var(--muted)", textAlign: "left" }}>
                <th style={th}>Поставщик</th>
                <th style={th}>Контактное лицо</th>
                <th style={th}>Телефон</th>
                <th style={th}>Мин. поставка</th>
                <th style={{ ...th, textAlign: "right" }}>Товаров</th>
              </tr>
            </thead>
            <tbody>
              {q.data.map((s) => (
                <tr key={s.id} style={{ borderTop: "1px solid var(--grid)" }}>
                  <td style={td}>
                    <Link to={`/suppliers/${s.id}`} style={{ color: "var(--text)", textDecoration: "none", fontWeight: 600 }}>
                      {s.name}
                    </Link>
                  </td>
                  <td style={{ ...td, color: "var(--text)" }}>{s.contacts[0]?.contact_person || "—"}</td>
                  <td style={{ ...td, color: "var(--text)" }}>
                    {s.contacts[0]?.phone || "—"}
                    {s.contacts.length > 1 && (
                      <span style={{ color: "var(--muted)" }}> +{s.contacts.length - 1}</span>
                    )}
                  </td>
                  <td style={{ ...td, color: "var(--text)" }}>{s.min_delivery || "—"}</td>
                  <td style={{ ...td, textAlign: "right", color: COLORS.indigoText }}>{s.products}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {q.data?.length === 0 && (
        <div style={{ color: "var(--muted)", padding: 32 }}>
          Поставщиков нет. Нажмите «Импорт из файла», чтобы загрузить из таблицы ТТК/прайса.
        </div>
      )}
    </div>
  );
}

const th: React.CSSProperties = { padding: "8px 12px" };
const td: React.CSSProperties = { padding: "8px 12px" };
const btnPrimary: React.CSSProperties = {
  padding: "8px 16px", borderRadius: 8, border: "none", background: COLORS.primary,
  color: "var(--text)", fontSize: 13, fontWeight: 600, cursor: "pointer",
};
const btnGhost: React.CSSProperties = {
  padding: "8px 16px", borderRadius: 8, border: "1px solid var(--grid)",
  background: "transparent", color: "var(--text)", fontSize: 13, cursor: "pointer",
};
