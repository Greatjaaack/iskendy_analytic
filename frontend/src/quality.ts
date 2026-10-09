/** Оценка цифр, которым можно (или нельзя) верить: food cost и прибыль.
 *
 *  Без этой проверки на проде 09.10.2026 food cost 5 % красился зелёным, а шапка P&L
 *  показывала зелёную EBITDA 94,6 %: с/с «Балыка» в iiko — 3 % цены, затраты не введены.
 *  Оценка — по данным, а не выключателем: когда с/с придёт настоящей (ТТК в Saby),
 *  цвета вернутся сами. */
import { FOOD_COST_MIN_PLAUSIBLE, FOOD_COST_THRESHOLDS } from "./constants.ts";

export type Level = "good" | "warn" | "bad" | null;

/** Уровень food cost %. `null` — не оцениваем: нет данных, бэкенд счёл с/с ненадёжной
 *  (`ok=false`) или процент неправдоподобно мал. */
export function foodCostLevel(v: number | null, ok = true): Level {
  if (v == null || !ok || v < FOOD_COST_MIN_PLAUSIBLE) return null;
  if (v < FOOD_COST_THRESHOLDS.good) return "good";
  if (v <= FOOD_COST_THRESHOLDS.warn) return "warn";
  return "bad";
}

/** Уровень EBITDA/прибыли. Убыток — всегда «bad»: недостающие затраты его только углубят.
 *  Плюс — «good» лишь при полных данных, иначе это оценка сверху (`null`). */
export function profitLevel(v: number, partial: boolean): Level {
  if (v < 0) return "bad";
  return partial ? null : "good";
}
