import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { login } from "../auth-api";
import { COLORS } from "../constants";

/** Экран входа: логин/пароль → JWT в localStorage → редирект на исходную страницу. */
export function Login() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as { from?: { pathname: string } } | null)?.from?.pathname ?? "/";

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      await login(username.trim(), password);
      navigate(from, { replace: true });
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status;
      setError(status === 401 ? "Неверный логин или пароль" : "Не удалось войти. Попробуйте ещё раз.");
    } finally {
      setBusy(false);
    }
  };

  const field: React.CSSProperties = {
    width: "100%", padding: "10px 12px", borderRadius: 8, fontSize: 14,
    border: "1px solid var(--grid)", background: "var(--bg)", color: "var(--text)",
    boxSizing: "border-box",
  };

  return (
    <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", background: "var(--bg)" }}>
      <form
        onSubmit={submit}
        style={{
          width: 320, background: "var(--card)", borderRadius: 14, padding: 28,
          border: "1px solid var(--grid)", display: "flex", flexDirection: "column", gap: 14,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <img
            src="/favicon.png"
            alt="Искенди"
            width={44}
            height={44}
            style={{ borderRadius: 10, flexShrink: 0 }}
          />
          <div>
            <div style={{ fontSize: 20, fontWeight: 700, color: "var(--text)" }}>Искенди</div>
            <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 2 }}>Analytics · вход</div>
          </div>
        </div>

        <label style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 12, color: "var(--muted)" }}>
          Логин
          <input
            style={field}
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoFocus
            autoComplete="username"
          />
        </label>

        <label style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 12, color: "var(--muted)" }}>
          Пароль
          <input
            style={field}
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
          />
        </label>

        {error && <div style={{ color: COLORS.bad, fontSize: 13 }}>{error}</div>}

        <button
          type="submit"
          disabled={busy || !username || !password}
          style={{
            marginTop: 4, padding: "10px 12px", borderRadius: 8, border: "none",
            background: busy || !username || !password ? "var(--grid)" : COLORS.primary,
            color: "#fff", fontSize: 14, fontWeight: 600,
            cursor: busy || !username || !password ? "default" : "pointer",
          }}
        >
          {busy ? "Вход…" : "Войти"}
        </button>
      </form>
    </div>
  );
}
