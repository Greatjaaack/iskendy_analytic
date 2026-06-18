// Переключение светлой/тёмной темы.
// Палитра задана CSS-переменными в index.css и выбирается атрибутом data-theme на <html>.
// Компоненты читают цвета через var(--…)/COLORS, поэтому смена темы мгновенная и глобальная.
import { useEffect, useState } from "react";

export type ThemeMode = "dark" | "light";
const STORAGE_KEY = "iskendy-theme";

const apply = (mode: ThemeMode) => {
  document.documentElement.dataset.theme = mode;
};

const stored = (): ThemeMode =>
  (localStorage.getItem(STORAGE_KEY) as ThemeMode) || "dark";

/** Хук темы: текущий режим + переключатель (сохраняется в localStorage). */
export function useTheme() {
  const [mode, setMode] = useState<ThemeMode>(stored);

  useEffect(() => {
    apply(mode);
    localStorage.setItem(STORAGE_KEY, mode);
  }, [mode]);

  const toggle = () => setMode((m) => (m === "dark" ? "light" : "dark"));
  return { mode, toggle };
}
