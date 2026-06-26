import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams, Link } from "react-router-dom";
import {
  addSupplierContact,
  deleteSupplierContact,
  fetchSupplier,
  supplierFileUrl,
  updateProductBrand,
  updateSupplier,
  uploadSupplierFile,
} from "../api";
import type {
  SupplierCard as SupplierCardT,
  SupplierContact,
  SupplierInput,
  SupplierProduct,
} from "../api";
import { COLORS } from "../constants";
import { fmtNum } from "../format";
import { isValidEmail, normalizePhone } from "../validation";

/** Карточка поставщика: редактируемые реквизиты, контакты с каналами, товары, файлы. */
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
    <div className="page" style={{ color: "var(--text)" }}>
      <Link to="/suppliers" style={{ color: "var(--muted)", fontSize: 13, textDecoration: "none" }}>
        ← Поставщики
      </Link>

      <DetailsSection sid={sid} s={s} />
      <ContactsSection sid={sid} contacts={s.contacts} />

      <Section title={`Товары (${s.products_list.length})`}>
        <table style={tbl}>
          <thead>
            <tr style={th}>
              <td style={td}>Товар</td>
              <td style={td}>Торговая марка</td>
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
                <td style={td}><BrandCell sid={sid} p={p} /></td>
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
            <a key={f.id} href={supplierFileUrl(sid, f.id)} target="_blank" rel="noreferrer"
              style={{ color: COLORS.indigoText, fontSize: 13, textDecoration: "none" }}>
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

/** Редактируемые реквизиты поставщика (название, адрес, мин. поставка, комментарий). */
function DetailsSection({ sid, s }: { sid: number; s: SupplierCardT }) {
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState<SupplierInput>({
    name: s.name, address: s.address, min_delivery: s.min_delivery, comment: s.comment,
  });
  const [err, setErr] = useState("");

  const mut = useMutation({
    mutationFn: () => updateSupplier(sid, form),
    onSuccess: async () => {
      setEditing(false); setErr("");
      await qc.invalidateQueries({ queryKey: ["supplier", sid] });
      await qc.invalidateQueries({ queryKey: ["suppliers"] });
    },
    onError: () => setErr("Не удалось сохранить (возможно, имя занято)"),
  });

  if (!editing) {
    return (
      <div style={{ ...card, marginBottom: 16 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
          <div style={{ fontSize: 22, fontWeight: 700 }}>{s.name}</div>
          <button onClick={() => { setForm({ name: s.name, address: s.address, min_delivery: s.min_delivery, comment: s.comment }); setEditing(true); }} style={btnGhost}>
            ✎ Редактировать
          </button>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <Field label="Адрес" value={s.address} />
          <Field label="Мин. поставка" value={s.min_delivery} />
          <Field label="Комментарий" value={s.comment} />
        </div>
      </div>
    );
  }

  const upd = (k: keyof SupplierInput, v: string) => setForm((f) => ({ ...f, [k]: v }));
  return (
    <div style={{ ...card, marginBottom: 16 }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <Labeled label="Название *"><input value={form.name} onChange={(e) => upd("name", e.target.value)} style={input} /></Labeled>
        <Labeled label="Адрес"><input value={form.address ?? ""} onChange={(e) => upd("address", e.target.value)} style={input} /></Labeled>
        <Labeled label="Мин. поставка"><input value={form.min_delivery ?? ""} onChange={(e) => upd("min_delivery", e.target.value)} style={input} /></Labeled>
        <Labeled label="Комментарий"><input value={form.comment ?? ""} onChange={(e) => upd("comment", e.target.value)} style={input} /></Labeled>
        {err && <div style={{ color: COLORS.bad, fontSize: 13 }}>{err}</div>}
        <div style={{ display: "flex", gap: 8 }}>
          <button onClick={() => form.name.trim() && mut.mutate()} disabled={mut.isPending} style={btnPrimary}>
            {mut.isPending ? "Сохранение..." : "Сохранить"}
          </button>
          <button onClick={() => { setEditing(false); setErr(""); }} style={btnGhost}>Отмена</button>
        </div>
      </div>
    </div>
  );
}

/** Контакты поставщика: список с каналами + добавление/удаление с валидацией. */
function ContactsSection({ sid, contacts }: { sid: number; contacts: SupplierContact[] }) {
  const qc = useQueryClient();
  const empty = { contact_person: "", phone: "", whatsapp: "", telegram: "", email: "", comment: "" };
  const [draft, setDraft] = useState({ ...empty });
  const [err, setErr] = useState("");
  const set = (k: keyof typeof empty, v: string) => setDraft((d) => ({ ...d, [k]: v }));

  const invalidate = () => qc.invalidateQueries({ queryKey: ["supplier", sid] });
  const addMut = useMutation({
    mutationFn: () => addSupplierContact(sid, draft),
    onSuccess: () => { setDraft({ ...empty }); setErr(""); invalidate(); },
    onError: () => setErr("Не удалось сохранить контакт"),
  });
  const delMut = useMutation({ mutationFn: (cid: number) => deleteSupplierContact(sid, cid), onSuccess: invalidate });

  const add = () => {
    if (!draft.contact_person && !draft.phone && !draft.whatsapp && !draft.telegram && !draft.email)
      return setErr("Заполните хотя бы одно поле");
    if (draft.phone && !normalizePhone(draft.phone)) return setErr("Некорректный телефон");
    if (draft.whatsapp && !normalizePhone(draft.whatsapp)) return setErr("Некорректный WhatsApp");
    if (draft.email && !isValidEmail(draft.email)) return setErr("Некорректный email");
    addMut.mutate();
  };

  return (
    <Section title={`Контакты (${contacts.length})`}>
      <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 12 }}>
        {contacts.map((c) => (
          <div key={c.id} style={{ display: "flex", gap: 10, alignItems: "center", fontSize: 14, flexWrap: "wrap" }}>
            <span style={{ fontWeight: 600, minWidth: 130 }}>{c.contact_person || "—"}</span>
            {c.phone && <Chan label="☎" value={c.phone} />}
            {c.whatsapp && <Chan label="WA" value={c.whatsapp} />}
            {c.telegram && <Chan label="TG" value={c.telegram} />}
            {c.email && <Chan label="✉" value={c.email} />}
            {c.comment && <span style={{ color: "var(--muted)", fontSize: 13 }}>· {c.comment}</span>}
            <button onClick={() => delMut.mutate(c.id)} style={{ ...iconBtn, marginLeft: "auto" }} title="Удалить">✕</button>
          </div>
        ))}
        {contacts.length === 0 && <Empty />}
      </div>

      <div style={contactBox}>
        <div style={{ display: "flex", gap: 8 }}>
          <input placeholder="Контактное лицо" value={draft.contact_person} onChange={(e) => set("contact_person", e.target.value)} style={{ ...inputSm, flex: 1 }} />
          <input placeholder="Заметка" value={draft.comment} onChange={(e) => set("comment", e.target.value)} style={{ ...inputSm, flex: 1 }} />
        </div>
        <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
          <input placeholder="☎ Телефон" value={draft.phone} onChange={(e) => set("phone", e.target.value)} style={{ ...inputSm, flex: 1 }} />
          <input placeholder="WhatsApp" value={draft.whatsapp} onChange={(e) => set("whatsapp", e.target.value)} style={{ ...inputSm, flex: 1 }} />
          <input placeholder="Telegram" value={draft.telegram} onChange={(e) => set("telegram", e.target.value)} style={{ ...inputSm, flex: 1 }} />
          <input placeholder="Email" value={draft.email} onChange={(e) => set("email", e.target.value)} style={{ ...inputSm, flex: 1 }} />
          <button onClick={add} disabled={addMut.isPending} style={btnGhost}>+ Добавить</button>
        </div>
      </div>
      {err && <div style={{ color: COLORS.bad, fontSize: 13, marginTop: 8 }}>{err}</div>}
    </Section>
  );
}

const Chan = ({ label, value }: { label: string; value: string }) => (
  <span style={{ fontSize: 13 }}>
    <span style={{ color: "var(--muted)" }}>{label} </span>{value}
  </span>
);

/** Инлайн-редактирование торговой марки позиции прайса (сохранение по потере фокуса). */
function BrandCell({ sid, p }: { sid: number; p: SupplierProduct }) {
  const qc = useQueryClient();
  const [val, setVal] = useState(p.brand);
  const mut = useMutation({
    mutationFn: (brand: string) => updateProductBrand(sid, p.price_id, brand),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["supplier", sid] }),
  });
  return (
    <input
      value={val}
      placeholder="—"
      onChange={(e) => setVal(e.target.value)}
      onBlur={() => val.trim() !== p.brand && mut.mutate(val.trim())}
      style={{
        width: "100%", minWidth: 90, padding: "4px 8px", borderRadius: 6,
        border: "1px solid var(--grid)", background: "var(--bg)", color: "var(--text)",
        fontSize: 13, boxSizing: "border-box",
      }}
    />
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div style={{ color: "var(--muted)", fontSize: 12 }}>{label}</div>
      <div style={{ fontSize: 14, marginTop: 2 }}>{value || "—"}</div>
    </div>
  );
}

const Labeled = ({ label, children }: { label: string; children: React.ReactNode }) => (
  <label style={{ fontSize: 13 }}>
    <div style={{ color: "var(--muted)", marginBottom: 4 }}>{label}</div>
    {children}
  </label>
);

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ ...card, marginBottom: 16 }}>
      <div style={{ fontWeight: 600, marginBottom: 12 }}>{title}</div>
      {children}
    </div>
  );
}

const Empty = () => <div style={{ color: "var(--muted)", padding: 16, fontSize: 13 }}>Нет данных</div>;
const card: React.CSSProperties = { background: "var(--card)", borderRadius: 12, padding: "16px 20px" };
const tbl: React.CSSProperties = { width: "100%", borderCollapse: "collapse", fontSize: 13 };
const th: React.CSSProperties = { color: "var(--muted)", textAlign: "left" };
const td: React.CSSProperties = { padding: "7px 10px" };
const input: React.CSSProperties = {
  width: "100%", padding: "9px 12px", borderRadius: 8, border: "1px solid var(--grid)",
  background: "var(--bg)", color: "var(--text)", fontSize: 14, boxSizing: "border-box",
};
const inputSm: React.CSSProperties = {
  padding: "8px 10px", borderRadius: 8, border: "1px solid var(--grid)",
  background: "var(--bg)", color: "var(--text)", fontSize: 13, boxSizing: "border-box", minWidth: 0,
};
const contactBox: React.CSSProperties = {
  border: "1px solid var(--grid)", borderRadius: 10, padding: 12,
};
const btnPrimary: React.CSSProperties = {
  padding: "8px 16px", borderRadius: 8, border: "none", background: COLORS.primary,
  color: "var(--text)", fontSize: 13, fontWeight: 600, cursor: "pointer",
};
const btnGhost: React.CSSProperties = {
  padding: "8px 16px", borderRadius: 8, border: "1px solid var(--grid)",
  background: "transparent", color: "var(--text)", fontSize: 13, cursor: "pointer",
};
const iconBtn: React.CSSProperties = {
  padding: "6px 9px", borderRadius: 8, border: "1px solid var(--grid)",
  background: "transparent", color: "var(--muted)", fontSize: 13, cursor: "pointer",
};
