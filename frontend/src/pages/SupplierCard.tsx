import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams, Link } from "react-router-dom";
import {
  addSupplierContact,
  deleteSupplierContact,
  fetchSupplier,
  supplierFileUrl,
  uploadSupplierFile,
} from "../api";
import type { SupplierContact } from "../api";
import { COLORS } from "../constants";
import { fmtNum } from "../format";
import { normalizePhone } from "../validation";

/** Карточка поставщика: реквизиты, контакты (телефоны/лица), товары, файлы. */
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
        <Info label="Адрес" value={s.address} />
        <Info label="Мин. поставка" value={s.min_delivery} />
        <Info label="Комментарий" value={s.comment} />
      </div>

      <ContactsSection sid={sid} contacts={s.contacts} />

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

/** Секция контактов: список телефонов/лиц + добавление и удаление с валидацией. */
function ContactsSection({ sid, contacts }: { sid: number; contacts: SupplierContact[] }) {
  const qc = useQueryClient();
  const [phone, setPhone] = useState("");
  const [person, setPerson] = useState("");
  const [comment, setComment] = useState("");
  const [err, setErr] = useState("");

  const invalidate = () => qc.invalidateQueries({ queryKey: ["supplier", sid] });
  const addMut = useMutation({
    mutationFn: () => addSupplierContact(sid, { phone, contact_person: person, comment }),
    onSuccess: () => {
      setPhone("");
      setPerson("");
      setComment("");
      setErr("");
      invalidate();
    },
    onError: () => setErr("Не удалось сохранить контакт"),
  });
  const delMut = useMutation({
    mutationFn: (cid: number) => deleteSupplierContact(sid, cid),
    onSuccess: invalidate,
  });

  const add = () => {
    if (!normalizePhone(phone)) {
      setErr("Некорректный телефон. Ожидается российский номер.");
      return;
    }
    addMut.mutate();
  };

  return (
    <Section title={`Контакты (${contacts.length})`}>
      <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 12 }}>
        {contacts.map((c) => (
          <div key={c.id} style={{ display: "flex", gap: 10, alignItems: "center", fontSize: 14 }}>
            <span style={{ fontWeight: 600, minWidth: 150 }}>{c.phone}</span>
            <span style={{ flex: 1 }}>{c.contact_person || "—"}</span>
            {c.comment && <span style={{ color: "var(--muted)", fontSize: 13 }}>{c.comment}</span>}
            <button onClick={() => delMut.mutate(c.id)} style={iconBtn} title="Удалить">
              ✕
            </button>
          </div>
        ))}
        {contacts.length === 0 && <Empty />}
      </div>

      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <input
          placeholder="+7 ..."
          value={phone}
          onChange={(e) => setPhone(e.target.value)}
          style={{ ...inputSm, flex: "0 0 160px" }}
        />
        <input
          placeholder="Контактное лицо"
          value={person}
          onChange={(e) => setPerson(e.target.value)}
          style={{ ...inputSm, flex: 1, minWidth: 140 }}
        />
        <input
          placeholder="Заметка"
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          style={{ ...inputSm, flex: "0 0 130px" }}
        />
        <button onClick={add} disabled={addMut.isPending} style={btnGhost}>
          + Добавить
        </button>
      </div>
      {err && <div style={{ color: COLORS.bad, fontSize: 13, marginTop: 8 }}>{err}</div>}
    </Section>
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
const inputSm: React.CSSProperties = {
  padding: "8px 10px", borderRadius: 8, border: "1px solid var(--grid)",
  background: "var(--bg)", color: "var(--text)", fontSize: 13, boxSizing: "border-box",
};
const iconBtn: React.CSSProperties = {
  padding: "6px 9px", borderRadius: 8, border: "1px solid var(--grid)",
  background: "transparent", color: "var(--muted)", fontSize: 13, cursor: "pointer",
};
