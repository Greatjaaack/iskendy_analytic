import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { createSupplier, uploadSupplierFile, type SupplierInput } from "../api";

const fields: { key: keyof SupplierInput; label: string }[] = [
  { key: "name", label: "Название *" },
  { key: "contact_person", label: "Контактное лицо" },
  { key: "phone", label: "Телефон" },
  { key: "address", label: "Адрес" },
  { key: "min_delivery", label: "Мин. поставка" },
  { key: "comment", label: "Комментарий" },
];

/** Форма заведения поставщика: реквизиты + опциональная загрузка файла (прайс/накладная). */
export function NewSupplier() {
  const nav = useNavigate();
  const qc = useQueryClient();
  const [form, setForm] = useState<SupplierInput>({ name: "" });
  const [file, setFile] = useState<File | null>(null);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");

  const save = async () => {
    if (!form.name.trim()) {
      setErr("Укажите название");
      return;
    }
    setSaving(true);
    setErr("");
    try {
      const s = await createSupplier(form);
      if (file) await uploadSupplierFile(s.id, file, "price");
      await qc.invalidateQueries({ queryKey: ["suppliers"] });
      nav(`/suppliers/${s.id}`);
    } catch {
      setErr("Не удалось сохранить (возможно, имя занято)");
      setSaving(false);
    }
  };

  return (
    <div style={{ padding: 24, color: "var(--text)", maxWidth: 560 }}>
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

        <label style={{ fontSize: 13 }}>
          <div style={{ color: "var(--muted)", marginBottom: 4 }}>Файл (прайс/накладная) — необязательно</div>
          <input type="file" onChange={(e) => setFile(e.target.files?.[0] ?? null)} style={{ color: "var(--muted)" }} />
        </label>

        {err && <div style={{ color: "#fca5a5", fontSize: 13 }}>{err}</div>}

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
  padding: "9px 18px", borderRadius: 8, border: "none", background: "#6366f1",
  color: "var(--text)", fontSize: 13, fontWeight: 600, cursor: "pointer",
};
const btnGhost: React.CSSProperties = {
  padding: "9px 18px", borderRadius: 8, border: "1px solid var(--grid)",
  background: "transparent", color: "var(--text)", fontSize: 13, cursor: "pointer",
};
