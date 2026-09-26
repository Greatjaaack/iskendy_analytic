// Общие инлайн-стили: кнопки-переключатели и раскраска food cost (раньше копировались
// в каждый компонент — четыре одинаковых `mini`, два `tabBtn`, два `costColor`).
import type { CSSProperties } from "react";

import { COLORS, FOOD_COST_THRESHOLDS } from "./constants";

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

/** Цвет food cost %: зелёный / жёлтый / красный по `FOOD_COST_THRESHOLDS`, нет данных — серый. */
export const foodCostColor = (v: number | null): string => {
  if (v == null) return "var(--muted)";
  if (v < FOOD_COST_THRESHOLDS.good) return COLORS.good;
  if (v <= FOOD_COST_THRESHOLDS.warn) return COLORS.warn;
  return COLORS.bad;
};
