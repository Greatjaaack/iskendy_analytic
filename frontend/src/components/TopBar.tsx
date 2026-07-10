import { logout } from "../auth-api";
import { useTheme } from "../theme";

/** Иконки темы/выхода в правом верхнем углу — общие для всех страниц (см. Layout в App.tsx). */
export function TopBar() {
  const { mode, toggle } = useTheme();
  return (
    <div className="top-actions">
      <span
        onClick={toggle}
        role="button"
        title={mode === "dark" ? "Светлая тема" : "Тёмная тема"}
        aria-label={mode === "dark" ? "Светлая тема" : "Тёмная тема"}
      >
        {mode === "dark" ? "☀️" : "🌙"}
      </span>
      <span onClick={logout} role="button" title="Выйти" aria-label="Выйти">
        🚪
      </span>
    </div>
  );
}
