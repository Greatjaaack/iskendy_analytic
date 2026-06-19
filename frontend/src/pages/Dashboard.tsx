import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchRevenue, triggerSync, rangeKey } from "../api";
import type { Period, RangeSel, RevenueDay } from "../api";
import { KpiCards } from "../components/KpiCards";
import { RevenueChart } from "../components/RevenueChart";
import { WeekdaySummary } from "../components/WeekdaySummary";
import { HourlyChart } from "../components/HourlyChart";
import { HourlyBreakdown } from "../components/HourlyBreakdown";
import { ServiceBreakdown } from "../components/ServiceBreakdown";
import { CheckComposition } from "../components/CheckComposition";
import { CheckFullness } from "../components/CheckFullness";
import { MenuEngineering } from "../components/MenuEngineering";
import { DishTable } from "../components/DishTable";
import { ChecksDistribution } from "../components/ChecksDistribution";
import { REFETCH_INTERVAL_MS, COLORS, PERIODS, weatherInfo } from "../constants";

const todayISO = () => new Date().toISOString().slice(0, 10);
const daysAgoISO = (n: number) => new Date(Date.now() - n * 86_400_000).toISOString().slice(0, 10);

/** Главная: KPI, выручка по дням, чеки по типу, почасовые продажи, продажи блюд.
 *  Период — пресет (день/неделя/месяц) или произвольный диапазон; всё реагирует на него. */
export function Dashboard() {
  const [sel, setSel] = useState<RangeSel>({ period: "week" });
  const [showCustom, setShowCustom] = useState(false);
  const [from, setFrom] = useState(daysAgoISO(6));
  const [to, setTo] = useState(todayISO());
  const [syncing, setSyncing] = useState(false);
  const [tab, setTab] = useState<"pulse" | "ops" | "menu">("pulse");

  const isCustom = "from" in sel;

  const revenueQ = useQuery({
    queryKey: ["revenue", rangeKey(sel)],
    queryFn: () => fetchRevenue(sel),
    refetchInterval: REFETCH_INTERVAL_MS,
  });

  const handleSync = async () => {
    setSyncing(true);
    await triggerSync();
    await revenueQ.refetch();
    setSyncing(false);
  };

  const pickPreset = (p: Period) => {
    setSel({ period: p });
    setShowCustom(false);
  };

  const applyCustom = () => {
    if (from && to && from <= to) setSel({ from, to });
  };

  return (
    <div style={{ minHeight: "100vh", background: COLORS.bg, color: "var(--text)", padding: 24 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 12, marginBottom: 24 }}>
        <div>
          <div style={{ fontSize: 22, fontWeight: 700 }}>Искенди Analytics</div>
          <div style={{ color: COLORS.muted, fontSize: 13, marginTop: 2 }}>
            Финансовая аналитика ресторана
          </div>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <div style={{ display: "flex", background: COLORS.card, borderRadius: 8, padding: 4, gap: 4 }}>
            {PERIODS.map((p) => {
              const active = !isCustom && sel.period === p.key;
              return (
                <button key={p.key} onClick={() => pickPreset(p.key)} style={tabBtn(active)}>
                  {p.label}
                </button>
              );
            })}
            <button onClick={() => setShowCustom((v) => !v)} style={tabBtn(isCustom)}>
              📅 Период
            </button>
          </div>
          <button
            onClick={handleSync}
            disabled={syncing}
            style={{
              padding: "6px 16px", borderRadius: 8, border: `1px solid ${COLORS.grid}`,
              background: "transparent", color: syncing ? COLORS.muted : "var(--text)",
              fontSize: 13, cursor: syncing ? "not-allowed" : "pointer",
            }}
          >
            {syncing ? "Обновление..." : "↻ Синхронизировать"}
          </button>
        </div>
      </div>

      {showCustom && (
        <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 16, flexWrap: "wrap" }}>
          <span style={{ color: COLORS.muted, fontSize: 13 }}>с</span>
          <input type="date" value={from} max={to} onChange={(e) => setFrom(e.target.value)} style={dateInput} />
          <span style={{ color: COLORS.muted, fontSize: 13 }}>по</span>
          <input type="date" value={to} min={from} max={todayISO()} onChange={(e) => setTo(e.target.value)} style={dateInput} />
          <button onClick={applyCustom} style={{ ...tabBtn(false), background: COLORS.primary, color: "var(--text)" }}>
            Применить
          </button>
          {isCustom && (
            <span style={{ color: COLORS.indigoText, fontSize: 13 }}>
              {sel.from} — {sel.to}
            </span>
          )}
        </div>
      )}

      {revenueQ.error && (
        <div style={{ background: "#2d1e1e", border: `1px solid ${COLORS.bad}`, borderRadius: 8, padding: 12, color: "#fca5a5", marginBottom: 16, fontSize: 13 }}>
          Ошибка загрузки данных. Проверьте что backend запущен и API-логин настроен.
        </div>
      )}

      {revenueQ.isLoading && (
        <div style={{ color: COLORS.muted, textAlign: "center", padding: 48 }}>Загрузка данных...</div>
      )}

      {revenueQ.data && (
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          {/* «Сегодня» (#7): дата, день недели, погода */}
          {!isCustom && sel.period === "day" && revenueQ.data.data[0] && (
            <TodayBanner day={revenueQ.data.data[0]} />
          )}
          <KpiCards summary={revenueQ.data.summary} range={sel} />

          {/* Разделы дашборда: Пульс / Операции / Меню (один экран не перегружен) */}
          <div style={{ display: "flex", gap: 4, background: COLORS.card, borderRadius: 8, padding: 4, width: "fit-content" }}>
            {([["pulse", "Пульс"], ["ops", "Операции"], ["menu", "Меню"]] as const).map(([k, label]) => (
              <button key={k} onClick={() => setTab(k)} style={tabBtn(tab === k)}>{label}</button>
            ))}
          </div>

          {tab === "pulse" && (
            <>
              <RevenueChart data={revenueQ.data.data} prevData={revenueQ.data.prev_data} range={sel} />
              <WeekdaySummary range={sel} />
            </>
          )}
          {tab === "ops" && (
            <>
              <ChecksDistribution range={sel} />
              <HourlyChart range={sel} />
              <CheckFullness range={sel} />
              <CheckComposition range={sel} />
              <HourlyBreakdown range={sel} />
            </>
          )}
          {tab === "menu" && (
            <>
              <ServiceBreakdown range={sel} />
              <MenuEngineering range={sel} />
              <DishTable range={sel} />
            </>
          )}
        </div>
      )}
    </div>
  );
}

const tabBtn = (active: boolean): React.CSSProperties => ({
  padding: "6px 16px", borderRadius: 6, border: "none", cursor: "pointer",
  fontSize: 13, fontWeight: 600,
  background: active ? COLORS.primary : "transparent",
  color: active ? "var(--text)" : COLORS.muted,
});

const dateInput: React.CSSProperties = {
  padding: "6px 10px", borderRadius: 8, border: `1px solid ${COLORS.grid}`,
  background: COLORS.card, color: "var(--text)", fontSize: 13,
};

/** Шапка «Сегодня» (#7): дата, день недели и погода в Москве. */
function TodayBanner({ day }: { day: RevenueDay }) {
  const dateStr = new Date(day.date).toLocaleDateString("ru-RU", {
    day: "numeric", month: "long", year: "numeric",
  });
  const w = day.weather;
  const info = weatherInfo(w?.weather_code);
  return (
    <div style={{
      background: COLORS.card, borderRadius: 12, padding: "16px 24px",
      display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8,
    }}>
      <div>
        <div style={{ fontSize: 18, fontWeight: 700, color: "var(--text)" }}>Сегодня, {day.day_of_week}</div>
        <div style={{ color: COLORS.muted, fontSize: 13 }}>{dateStr}</div>
      </div>
      {w && (
        <div style={{ fontSize: 16, color: "var(--text)" }}>
          {info.icon} {info.label}
          {w.temp_max != null ? `, ${Math.round(w.temp_max)}°` : ""}
        </div>
      )}
    </div>
  );
}
