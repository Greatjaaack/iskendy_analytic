import { useState } from "react";
import { NavLink } from "react-router-dom";
import { COLORS } from "../constants";

// «Доставка» пока не вынесена в отдельный пункт навигации — на дашборде есть
// галка «С доставкой», её достаточно (решение пользователя).
const items: { to: string; label: string; disabled?: boolean }[] = [
  { to: "/", label: "Дашборд" },
  { to: "/pnl", label: "P&L дня" },
  { to: "/schedule", label: "График и ФОТ" },
  { to: "/invoices", label: "Накладные", disabled: true },
  { to: "/orders", label: "Автозаказ", disabled: true },
];

const linkStyle = (isActive: boolean): React.CSSProperties => ({
  padding: "9px 12px",
  borderRadius: 8,
  fontSize: 14,
  textDecoration: "none",
  color: isActive ? "var(--text)" : "var(--muted)",
  background: isActive ? COLORS.primary : "transparent",
  fontWeight: isActive ? 600 : 400,
});

export function Sidebar() {
  // На телефоне сайдбар — выезжающий drawer; open управляет его видимостью.
  // На десктопе класс .sidebar-open игнорируется (drawer-стили в media-query ≤768px).
  const [open, setOpen] = useState(false);
  const close = () => setOpen(false);

  return (
    <>
      {/* Гамбургер — виден только на телефоне (CSS .menu-btn) */}
      <button
        className="menu-btn"
        onClick={() => setOpen(true)}
        aria-label="Меню"
      >
        ☰
      </button>

      {/* Подложка под drawer — виден только при open на телефоне */}
      <div
        className={`sidebar-backdrop${open ? " sidebar-open" : ""}`}
        onClick={close}
      />

      <div
        className={`sidebar${open ? " sidebar-open" : ""}`}
        style={{
          width: 220,
          flexShrink: 0,
          background: "var(--card)",
          borderRight: "1px solid var(--grid)",
          padding: "20px 12px",
          minHeight: "100vh",
          position: "sticky",
          top: 0,
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 10,
            padding: "0 12px 20px",
          }}
        >
          <img
            src="/favicon.png"
            alt="Искенди"
            width={36}
            height={36}
            style={{ borderRadius: 8, flexShrink: 0 }}
          />
          <div style={{ fontSize: 18, fontWeight: 700, color: "var(--text)", lineHeight: 1.1 }}>
            Искенди
            <div style={{ fontSize: 11, fontWeight: 400, color: "var(--muted)", marginTop: 2 }}>
              Analytics
            </div>
          </div>
        </div>
        <nav style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          {items.map((it) =>
            it.disabled ? (
              <div
                key={it.to}
                style={{
                  padding: "9px 12px",
                  borderRadius: 8,
                  fontSize: 14,
                  color: "var(--muted)",
                  cursor: "not-allowed",
                }}
                title="Скоро"
              >
                {it.label}
              </div>
            ) : (
              <NavLink
                key={it.to}
                to={it.to}
                end={it.to === "/"}
                onClick={close}
                style={({ isActive }) => linkStyle(isActive)}
              >
                {it.label}
              </NavLink>
            )
          )}
        </nav>
      </div>
    </>
  );
}
