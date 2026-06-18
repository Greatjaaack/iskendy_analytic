import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { addSupplierContact, createSupplier, uploadSupplierFile, type SupplierInput } from "../api";
import { COLORS } from "../constants";
import { normalizePhone } from "../validation";

const fields: { key: keyof SupplierInput; label: string }[] = [
  { key: "name", label: "Название *" },
  { key: "address", label: "Адрес" },
  { key: "min_delivery", label: "Мин. поставка" },
  { key: "comment", label: "Комментарий" },
];

interface ContactDraft {
  phone: string;
  contact_person: string;
  comment: string;
}

const emptyContact = (): ContactDraft => ({ phone: "", contact_person: "", comment: "" });

/** Форма заведения поставщика: реквизиты + телефоны/контактные лица + опц. файл. */
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
    // заполненные контакты (по телефону) должны пройти валидацию
    const filled = contacts.filter((c) => c.phone.trim() || c.contact_person.trim());
    for (const c of filled) {
      if (!normalizePhone(c.phone)) {
        setErr(`Некорректный телефон: «${c.phone}». Ожидается российский номер.`);
        return;
      }
    }
    setSaving(true);
    setErr("");
    try {
      const s = await createSupplier(form);
      for (const c of filled) {
        await addSupplierContact(s.id, {
          phone: c.phone,
          contact_person: c.contact_person,
          comment: c.comment,
        });
      }
      if (file) await uploadSupplierFile(s.id, file, "price");
      await qc.invalidateQueries({ queryKey: ["suppliers"] });
      nav(`/suppliers/${s.id}`);
    } catch {
      setErr("Не удалось сохранить (возможно, имя занято)");
      setSaving(false);
    }
  };

  return (
    <div style={{ padding: 24, color: "var(--text)", maxWidth: 640 }}>
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
            Телефоны и контактные лица
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {contacts.map((c, i) => (
              <div key={i} style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <input
                  placeholder="+7 ..."
                  value={c.phone}
                  onChange={(e) => setContact(i, { phone: e.target.value })}
                  style={{ ...input, flex: "0 0 170px" }}
                />
                <input
                  placeholder="Контактное лицо"
                  value={c.contact_person}
                  onChange={(e) => setContact(i, { contact_person: e.target.value })}
                  style={{ ...input, flex: 1 }}
                />
                <input
                  placeholder="Заметка"
                  value={c.comment}
                  onChange={(e) => setContact(i, { comment: e.target.value })}
                  style={{ ...input, flex: "0 0 130px" }}
                />
                <button
                  onClick={() => removeRow(i)}
                  disabled={contacts.length === 1}
                  style={iconBtn}
                  title="Удалить"
                >
                  ✕
                </button>
              </div>
            ))}
          </div>
          <button onClick={addRow} style={{ ...btnGhost, marginTop: 8, padding: "6px 12px" }}>
            + Ещё телефон
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
