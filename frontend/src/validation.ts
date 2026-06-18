// Клиентская валидация телефона (зеркалит backend utils.normalize_phone).

/** Нормализует российский номер в «+7XXXXXXXXXX»; `null` — если номер некорректный. */
export const normalizePhone = (raw: string): string | null => {
  let d = (raw || "").replace(/\D/g, "");
  if (d.length === 11 && (d[0] === "7" || d[0] === "8")) d = d.slice(1);
  if (d.length !== 10) return null;
  return "+7" + d;
};

/** Базовая проверка email. */
export const isValidEmail = (raw: string): boolean => /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(raw.trim());
