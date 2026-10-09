// Общие инлайн-стили: кнопки-переключатели и раскраска food cost (раньше копировались
// в каждый компонент — четыре одинаковых `mini`, два `tabBtn`, два `costColor`).
import type { CSSProperties } from "react";

import { COLORS } from "./constants";
import { foodCostLevel, type Level } from "./quality";

/** Вкладка страницы (Пульс / Операции / Меню…). */
export const tabBtn = (active: boolean): CSSProperties => ({
  padding: "6px 16px", borderRadius: 6, border: "none", cursor: "pointer",
  fontSize: 13, fontWeight: 600,
  background: active ? COLORS.primary : "transparent",
  color: active ? "var(--text)" : COLORS.muted,
});

/** Маленький тумблер внутри виджета (Выручка / Кол-во, Объём / Доли…). */
export const miniBtn = (active: boolean): CSSProperties => ({
  padding: "5px 12px", borderRadius: 6, border: "none", cursor: "pointer",
  fontSize: 12, fontWeight: 600,
  background: active ? COLORS.primary : "transparent",
  color: active ? "var(--text)" : "var(--muted)",
});

/** Цвет food cost %: зелёный / жёлтый / красный по `FOOD_COST_THRESHOLDS`. Серый — нет
 *  данных, с/с ненадёжна (`ok=false`: бэкенд счёл покрытие недостаточным) или процент
 *  неправдоподобно мал: 5 % — это незаведённая с/с, а не отличный результат. */
export const foodCostColor = (v: number | null, ok = true): string =>
  levelColor(foodCostLevel(v, ok)) ?? "var(--muted)";

/** Цвет уровня оценки (`quality.ts`); `null` — не оцениваем. */
export const levelColor = (l: Level): string | null =>
  l === "good" ? COLORS.good : l === "warn" ? COLORS.warn : l === "bad" ? COLORS.bad : null;
