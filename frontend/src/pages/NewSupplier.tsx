import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { addSupplierContact, createSupplier, uploadSupplierFile, type SupplierInput } from "../api";
import { COLORS } from "../constants";
import { isValidEmail, normalizePhone } from "../validation";

const fields: { key: keyof SupplierInput; label: string }[] = [
  { key: "name", label: "Название *" },
  { key: "address", label: "Адрес" },
  { key: "min_delivery", label: "Мин. поставка" },
  { key: "comment", label: "Комментарий" },
];

interface ContactDraft {
  contact_person: string;
  phone: string;
  whatsapp: string;
  telegram: string;
  email: string;
  comment: string;
}

const emptyContact = (): ContactDraft => ({
  contact_person: "", phone: "", whatsapp: "", telegram: "", email: "", comment: "",
});

const isFilled = (c: ContactDraft) =>
  c.contact_person || c.phone || c.whatsapp || c.telegram || c.email;

/** Форма заведения поставщика: реквизиты + контакты с каналами (тел/WA/TG/email) + файл. */
export function NewSupplier() {
  const nav = useNavigate();
  const qc = useQueryClient();
  const [form, setForm] = useState<SupplierInput>({ name: "" });
  const [contacts, setContacts] = useState<ContactDraft[]>([emptyContact()]);
  const [file, setFile] = useState<File | null>(null);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");

  const setContact = (i: number, patch: Partial<ContactDraft>) =>
    setContacts((cs) => cs.map((c, idx) => (idx === i ? { ...c, ...patch } : c)));
  const addRow = () => setContacts((cs) => [...cs, emptyContact()]);
  const removeRow = (i: number) => setContacts((cs) => cs.filter((_, idx) => idx !== i));

  const save = async () => {
    if (!form.name.trim()) {
      setErr("Укажите название");
      return;
    }
    const filled = contacts.filter(isFilled);
    for (const c of filled) {
      if (c.phone && !normalizePhone(c.phone)) return setErr(`Некорректный телефон: «${c.phone}»`);
      if (c.whatsapp && !normalizePhone(c.whatsapp)) return setErr(`Некорректный WhatsApp: «${c.whatsapp}»`);
      if (c.email && !isValidEmail(c.email)) return setErr(`Некорректный email: «${c.email}»`);
    }
    setSaving(true);
    setErr("");
    try {
      const s = await createSupplier(form);
      for (const c of filled) await addSupplierContact(s.id, c);
      if (file) await uploadSupplierFile(s.id, file, "price");
      await qc.invalidateQueries({ queryKey: ["suppliers"] });
      nav(`/suppliers/${s.id}`);
    } catch {
      setErr("Не удалось сохранить (возможно, имя занято)");
      setSaving(false);
    }
  };

  return (
    <div className="page" style={{ color: "var(--text)", maxWidth: 720 }}>
      <Link to="/suppliers" style={{ color: "var(--muted)", fontSize: 13, textDecoration: "none" }}>
        ← Поставщики
      </Link>
      <div style={{ fontSize: 22, fontWeight: 700, margin: "8px 0 20px" }}>Новый поставщик</div>

      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {fields.map((f) => (
          <label key={f.key} style={{ fontSize: 13 }}>
            <div style={{ color: "var(--muted)", marginBottom: 4 }}>{f.label}</div>
            <input
              value={form[f.key] ?? ""}
              onChange={(e) => setForm({ ...form, [f.key]: e.target.value })}
              style={input}
            />
          </label>
        ))}

        <div>
          <div style={{ color: "var(--muted)", fontSize: 13, marginBottom: 6 }}>
            Контакты и каналы связи
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {contacts.map((c, i) => (
              <div key={i} style={contactBox}>
                <div style={{ display: "flex", gap: 8 }}>
                  <input placeholder="Контактное лицо" value={c.contact_person}
                    onChange={(e) => setContact(i, { contact_person: e.target.value })} style={{ ...input, flex: 1 }} />
                  <input placeholder="Заметка (склад/бухгалтерия…)" value={c.comment}
                    onChange={(e) => setContact(i, { comment: e.target.value })} style={{ ...input, flex: 1 }} />
                  <button onClick={() => removeRow(i)} disabled={contacts.length === 1} style={iconBtn} title="Удалить">✕</button>
                </div>
                <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                  <input placeholder="☎ Телефон" value={c.phone}
                    onChange={(e) => setContact(i, { phone: e.target.value })} style={{ ...input, flex: 1 }} />
                  <input placeholder="WhatsApp" value={c.whatsapp}
                    onChange={(e) => setContact(i, { whatsapp: e.target.value })} style={{ ...input, flex: 1 }} />
                  <input placeholder="Telegram (@…)" value={c.telegram}
                    onChange={(e) => setContact(i, { telegram: e.target.value })} style={{ ...input, flex: 1 }} />
                  <input placeholder="Email" value={c.email}
                    onChange={(e) => setContact(i, { email: e.target.value })} style={{ ...input, flex: 1 }} />
                </div>
              </div>
            ))}
          </div>
          <button onClick={addRow} style={{ ...btnGhost, marginTop: 8, padding: "6px 12px" }}>
            + Ещё контакт
          </button>
        </div>

        <label style={{ fontSize: 13 }}>
          <div style={{ color: "var(--muted)", marginBottom: 4 }}>Файл (прайс/накладная) — необязательно</div>
          <input type="file" onChange={(e) => setFile(e.target.files?.[0] ?? null)} style={{ color: "var(--muted)" }} />
        </label>

        {err && <div style={{ color: COLORS.bad, fontSize: 13 }}>{err}</div>}

        <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
          <button onClick={save} disabled={saving} style={btnPrimary}>
            {saving ? "Сохранение..." : "Сохранить"}
          </button>
          <Link to="/suppliers" style={{ ...btnGhost, textDecoration: "none" }}>
            Отмена
          </Link>
        </div>
      </div>
    </div>
  );
}

const input: React.CSSProperties = {
  width: "100%", padding: "9px 12px", borderRadius: 8, border: "1px solid var(--grid)",
  background: "var(--card)", color: "var(--text)", fontSize: 14, boxSizing: "border-box",
};
const contactBox: React.CSSProperties = {
  border: "1px solid var(--grid)", borderRadius: 10, padding: 12, background: "var(--bg)",
};
const btnPrimary: React.CSSProperties = {
  padding: "9px 18px", borderRadius: 8, border: "none", background: COLORS.primary,
  color: "var(--text)", fontSize: 13, fontWeight: 600, cursor: "pointer",
};
const btnGhost: React.CSSProperties = {
  padding: "9px 18px", borderRadius: 8, border: "1px solid var(--grid)",
  background: "transparent", color: "var(--text)", fontSize: 13, cursor: "pointer",
};
const iconBtn: React.CSSProperties = {
  padding: "8px 10px", borderRadius: 8, border: "1px solid var(--grid)",
  background: "transparent", color: "var(--muted)", fontSize: 13, cursor: "pointer",
};
