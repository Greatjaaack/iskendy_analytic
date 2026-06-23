import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchRevenue, triggerSync, fetchLastSync, rangeKey } from "../api";
import type { Period, RangeSel, RevenueDay } from "../api";
import { KpiCards } from "../components/KpiCards";
import { RevenueChart } from "../components/RevenueChart";
import { WeekdaySummary } from "../components/WeekdaySummary";
import { HourlyChart } from "../components/HourlyChart";
import { DaypartBreakdown } from "../components/DaypartBreakdown";
import { HourlyBreakdown } from "../components/HourlyBreakdown";
import { CheckComposition } from "../components/CheckComposition";
import { CheckFullness } from "../components/CheckFullness";
import { MenuEngineering } from "../components/MenuEngineering";
import { MenuBasket } from "../components/MenuBasket";
import { DishTable } from "../components/DishTable";
import { ChecksDistribution } from "../components/ChecksDistribution";
import {
  REFETCH_INTERVAL_MS, COLORS, PERIODS, weatherInfo,
  AUTOSYNC_OPTIONS, AUTOSYNC_DAYS,
} from "../constants";

const todayISO = () => new Date().toISOString().slice(0, 10);
const daysAgoISO = (n: number) => new Date(Date.now() - n * 86_400_000).toISOString().slice(0, 10);

/** ISO-метка синка (UTC) → «14:05 · 23.06» во времени ресторана (Москва): сперва время, затем дата. */
const fmtSync = (iso: string): string => {
  const d = new Date(iso);
  const opts = { timeZone: "Europe/Moscow" } as const;
  const time = d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit", ...opts });
  const date = d.toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit", ...opts });
  return `${time} · ${date}`;
};

/** Главная: KPI, выручка по дням, чеки по типу, почасовые продажи, продажи блюд.
 *  Период — пресет (день/неделя/месяц) или произвольный диапазон; всё реагирует на него. */
export function Dashboard() {
  const [sel, setSel] = useState<RangeSel>({ period: "week" });
  const [showCustom, setShowCustom] = useState(false);
  const [from, setFrom] = useState(daysAgoISO(6));
  const [to, setTo] = useState(todayISO());
  const [syncing, setSyncing] = useState(false);
  const [tab, setTab] = useState<"pulse" | "ops" | "menu">("pulse");
  // галка «с доставкой»: выкл → бэкенд вычитает выручку/чеки доставки из revenue-виджетов
  const [withDelivery, setWithDelivery] = useState(false);
  // интервал автосинхронизации (мс), выбор пользователя — хранится в localStorage
  const [autoSyncMs, setAutoSyncMs] = useState<number>(
    () => Number(localStorage.getItem("autosync-ms")) || 0,
  );

  const isCustom = "from" in sel;
  // Один день («Сегодня» или диапазон из одной даты): «по дням» вырождается в один
  // столбец, поэтому в «Пульсе» показываем внутридневную динамику — почасовой график.
  const isSingleDay = isCustom ? sel.from === sel.to : sel.period === "day";

  const revenueQ = useQuery({
    queryKey: ["revenue", rangeKey(sel), withDelivery],
    queryFn: () => fetchRevenue(sel, withDelivery),
    refetchInterval: REFETCH_INTERVAL_MS,
  });

  const lastSyncQ = useQuery({
    queryKey: ["last-sync"],
    queryFn: fetchLastSync,
    refetchInterval: REFETCH_INTERVAL_MS,
  });

  // days не задан → полный синк (кнопка); days=AUTOSYNC_DAYS → лёгкий синк (автотаймер)
  const runSync = async (days?: number) => {
    setSyncing(true);
    await triggerSync(days);
    await Promise.all([revenueQ.refetch(), lastSyncQ.refetch()]);
    setSyncing(false);
  };
  const handleSync = () => runSync();

  // автосинхронизация: при выбранном интервале лёгкий синк + рефетч по таймеру
  useEffect(() => {
    localStorage.setItem("autosync-ms", String(autoSyncMs));
    if (!autoSyncMs) return;
    const id = setInterval(() => runSync(AUTOSYNC_DAYS), autoSyncMs);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoSyncMs]);

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
          <label
            title="Учитывать заказы доставки во всех виджетах дашборда (выручка, чеки, блюда, состав чека)"
            style={{
              display: "flex", alignItems: "center", gap: 6, cursor: "pointer",
              padding: "6px 12px", borderRadius: 8, border: `1px solid ${COLORS.grid}`,
              background: COLORS.card, color: "var(--text)", fontSize: 13, userSelect: "none",
            }}
          >
            <input
              type="checkbox"
              checked={withDelivery}
              onChange={(e) => setWithDelivery(e.target.checked)}
              style={{ cursor: "pointer" }}
            />
            С доставкой
          </label>
          <select
            value={autoSyncMs}
            onChange={(e) => setAutoSyncMs(Number(e.target.value))}
            title="Автоматически синхронизировать данные с выбранным интервалом"
            style={{
              padding: "6px 10px", borderRadius: 8, border: `1px solid ${COLORS.grid}`,
              background: COLORS.card, color: "var(--text)", fontSize: 13, cursor: "pointer",
            }}
          >
            {AUTOSYNC_OPTIONS.map((o) => (
              <option key={o.ms} value={o.ms}>
                {o.ms === 0 ? "Автосинк: выкл" : `Автосинк: ${o.label}`}
              </option>
            ))}
          </select>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 2 }}>
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
            <span style={{ color: COLORS.muted, fontSize: 11 }} title="Время последней успешной синхронизации (МСК)">
              {lastSyncQ.data?.last_sync
                ? `Обновлено: ${fmtSync(lastSyncQ.data.last_sync)}`
                : "Ещё не синхронизировано"}
            </span>
          </div>
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
          <KpiCards summary={revenueQ.data.summary} />

          {/* Разделы дашборда: Пульс / Операции / Меню (один экран не перегружен) */}
          <div style={{ display: "flex", gap: 4, background: COLORS.card, borderRadius: 8, padding: 4, width: "fit-content" }}>
            {([["pulse", "Пульс"], ["ops", "Операции"], ["menu", "Меню"]] as const).map(([k, label]) => (
              <button key={k} onClick={() => setTab(k)} style={tabBtn(tab === k)}>{label}</button>
            ))}
          </div>

          {tab === "pulse" && (
            <div className="dash-grid">
              <div className="dash-full">
                {isSingleDay ? (
                  <HourlyChart range={sel} withDelivery={withDelivery} />
                ) : (
                  <RevenueChart data={revenueQ.data.data} prevData={revenueQ.data.prev_data} range={sel} />
                )}
              </div>
              <div className="dash-full">
                <ChecksDistribution range={sel} withDelivery={withDelivery} />
              </div>
            </div>
          )}
          {tab === "ops" && (
            <div className="dash-grid">
              {/* свод по дням недели бессмыслен для одного дня (1 строка, бар на 100%) */}
              {!isSingleDay && <WeekdaySummary range={sel} withDelivery={withDelivery} />}
              <div className="dash-full">
                <DaypartBreakdown range={sel} withDelivery={withDelivery} />
              </div>
              <HourlyChart range={sel} withDelivery={withDelivery} />
              <CheckFullness range={sel} withDelivery={withDelivery} />
              <div className="dash-full">
                <HourlyBreakdown range={sel} withDelivery={withDelivery} />
              </div>
            </div>
          )}
          {tab === "menu" && (
            <div className="dash-grid">
              <CheckComposition range={sel} withDelivery={withDelivery} />
              <MenuBasket range={sel} withDelivery={withDelivery} />
              <div className="dash-full">
                <MenuEngineering range={sel} withDelivery={withDelivery} />
              </div>
              <div className="dash-full">
                <DishTable range={sel} withDelivery={withDelivery} />
              </div>
            </div>
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
