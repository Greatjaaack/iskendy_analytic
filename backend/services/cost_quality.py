"""Надёжность себестоимости: какая доля выручки покрыта правдоподобной с/с позиций.

Food cost — сумма с/с позиций от кассы ÷ выручка. Если у главной позиции с/с не заведена
или заведена мусорно (у «Балыка» 3 % цены), сумма получается правдоподобной на вид (5 %),
но она ложная: цифра красится зелёным, а EBITDA выходит 94 %. Покрытие показывает, можно
ли этой цифре верить; правило позиции — `utils.cost_plausible`.
"""

from datetime import date

from sqlalchemy import select

from constants import FOOD_COST_MIN_COVERAGE, ORDER_STATUS_CATEGORY
from models import OrderItem, SessionLocal
from utils import cost_plausible


def cost_coverage(df: date, dt: date) -> float | None:
    """% выручки периода с правдоподобной с/с; `None` — в периоде нет продаж."""
    with SessionLocal() as db:
        rows = db.execute(
            select(OrderItem.sum, OrderItem.cost).where(
                OrderItem.date >= df,
                OrderItem.date <= dt,
                OrderItem.category != ORDER_STATUS_CATEGORY,
                OrderItem.sum > 0,
            )
        ).all()
    total = sum(s for s, _c in rows)
    if not total:
        return None
    covered = sum(s for s, c in rows if cost_plausible(c, s))
    return round(covered / total * 100, 1)


def cost_reliable(coverage: float | None) -> bool:
    """Можно ли оценивать food cost по бенчмарку (красить зелёным/красным)."""
    return coverage is not None and coverage >= FOOD_COST_MIN_COVERAGE
