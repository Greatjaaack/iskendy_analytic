import { useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams, Link } from "react-router-dom";
import { fetchSupplier, uploadSupplierFile, supplierFileUrl } from "../api";
import { COLORS } from "../constants";
import { fmtNum } from "../format";

/** Карточка поставщика: реквизиты, товары с ценами, прикреплённые файлы (загрузка/скачивание). */
export function SupplierCard() {
  const { id } = useParams();
  const sid = Number(id);
  const qc = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);

  const q = useQuery({ queryKey: ["supplier", sid], queryFn: () => fetchSupplier(sid) });

  const onFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (!f) return;
    setUploading(true);
    await uploadSupplierFile(sid, f, "invoice");
    await qc.invalidateQueries({ queryKey: ["supplier", sid] });
    setUploading(false);
    if (fileRef.current) fileRef.current.value = "";
  };

  if (q.isLoading) return <div style={{ padding: 24, color: "var(--muted)" }}>Загрузка...</div>;
  if (!q.data) return <div style={{ padding: 24, color: COLORS.bad }}>Не найдено</div>;
  const s = q.data;

  return (
    <div style={{ padding: 24, color: "var(--text)" }}>
      <Link to="/suppliers" style={{ color: "var(--muted)", fontSize: 13, textDecoration: "none" }}>
        ← Поставщики
      </Link>
      <div style={{ fontSize: 22, fontWeight: 700, margin: "8px 0 20px" }}>{s.name}</div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 16 }}>
        <Info label="Контактное лицо" value={s.contact_person} />
        <Info label="Телефон" value={s.phone} />
        <Info label="Адрес" value={s.address} />
        <Info label="Мин. поставка" value={s.min_delivery} />
        <Info label="Комментарий" value={s.comment} />
      </div>

      <Section title={`Товары (${s.products_list.length})`}>
        <table style={tbl}>
          <thead>
            <tr style={th}>
              <td style={td}>Товар</td>
              <td style={td}>Ед.</td>
              <td style={{ ...td, textAlign: "right" }}>Фасовка</td>
              <td style={{ ...td, textAlign: "right" }}>Цена упак.</td>
              <td style={{ ...td, textAlign: "right" }}>Цена/ед.</td>
              <td style={{ ...td, textAlign: "right" }}>Дата</td>
            </tr>
          </thead>
          <tbody>
            {s.products_list.map((p) => (
              <tr key={p.ingredient_id} style={{ borderTop: "1px solid var(--grid)" }}>
                <td style={td}>{p.name}</td>
                <td style={{ ...td, color: "var(--muted)" }}>{p.unit}</td>
                <td style={{ ...td, textAlign: "right" }}>{fmtNum(p.pack_size)}</td>
                <td style={{ ...td, textAlign: "right" }}>{fmtNum(p.pack_price)}</td>
                <td style={{ ...td, textAlign: "right", color: COLORS.indigoText }}>{fmtNum(p.unit_price)}</td>
                <td style={{ ...td, textAlign: "right", color: "var(--muted)" }}>{p.price_date || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {s.products_list.length === 0 && <Empty />}
      </Section>

      <Section title={`Файлы (${s.files.length})`}>
        <input ref={fileRef} type="file" onChange={onFile} style={{ display: "none" }} />
        <button onClick={() => fileRef.current?.click()} disabled={uploading} style={btnGhost}>
          {uploading ? "Загрузка..." : "↥ Загрузить файл"}
        </button>
        <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 6 }}>
          {s.files.map((f) => (
            <a
              key={f.id}
              href={supplierFileUrl(sid, f.id)}
              target="_blank"
              rel="noreferrer"
              style={{ color: COLORS.indigoText, fontSize: 13, textDecoration: "none" }}
            >
              📄 {f.filename}{" "}
              <span style={{ color: "var(--muted)" }}>· {new Date(f.uploaded_at).toLocaleDateString("ru-RU")}</span>
            </a>
          ))}
          {s.files.length === 0 && <span style={{ color: "var(--muted)", fontSize: 13 }}>Файлов нет</span>}
        </div>
      </Section>
    </div>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ background: "var(--card)", borderRadius: 10, padding: "10px 14px" }}>
      <div style={{ color: "var(--muted)", fontSize: 12 }}>{label}</div>
      <div style={{ fontSize: 14, marginTop: 2 }}>{value || "—"}</div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ background: "var(--card)", borderRadius: 12, padding: "16px 20px", marginBottom: 16 }}>
      <div style={{ fontWeight: 600, marginBottom: 12 }}>{title}</div>
      {children}
    </div>
  );
}

const Empty = () => <div style={{ color: "var(--muted)", padding: 16, fontSize: 13 }}>Нет данных</div>;
const tbl: React.CSSProperties = { width: "100%", borderCollapse: "collapse", fontSize: 13 };
const th: React.CSSProperties = { color: "var(--muted)", textAlign: "left" };
const td: React.CSSProperties = { padding: "7px 10px" };
const btnGhost: React.CSSProperties = {
  padding: "8px 16px", borderRadius: 8, border: "1px solid var(--grid)",
  background: "transparent", color: "var(--text)", fontSize: 13, cursor: "pointer",
};
