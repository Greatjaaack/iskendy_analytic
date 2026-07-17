"""Комиссия агрегатора и чистая выручка — единый расчёт для дашборда и P&L.

Доставка у точки — только через агрегатора (Яндекс Еда). iiko пишет заказ БРУТТО
(полная сумма заказа), а агрегатор удерживает `aggregator_pct`% при выплате на счёт.
«Чистая выручка» = брутто − эта комиссия; вычет — ТОЛЬКО из агрегаторской части, зал
не трогаем. База комиссии — фактические платежи группы «Агрегатор» из `order_payments`
(а не категория «доставка», которая недосчитывает заказы). Один источник формулы, чтобы
KPI дашборда и P&L считали чистую выручку одинаково и не расходились.
"""

from datetime import date

from sqlalchemy import select

from constants import PAYMENT_AGGREGATOR
from models import OrderPayment, PnlMonth, SessionLocal
from utils import payment_group

# Ставка удержания агрегатора по умолчанию (Яндекс Еда). У точки была всегда 35%.
DEFAULT_AGGREGATOR_PCT = 35.0


def aggregator_revenue_by_day(df: date, dt: date) -> dict[str, float]:
    """Брутто-выручка через агрегатора по дням (платежи группы «Агрегатор»).

    Это полная сумма заказов доставки (как её пишет iiko), до удержания комиссии.
    """
    out: dict[str, float] = {}
    with SessionLocal() as db:
        rows = db.execute(
            select(OrderPayment.date, OrderPayment.pay_type, OrderPayment.amount).where(
                OrderPayment.date >= df, OrderPayment.date <= dt
            )
        ).all()
    for d, pt, amt in rows:
        if payment_group(pt) == PAYMENT_AGGREGATOR:
            key = d.isoformat()
            out[key] = out.get(key, 0.0) + float(amt or 0)
    return out


def _rates_by_month() -> dict[tuple[int, int], float]:
    """Ставка удержания агрегатора по месяцам (`pnl_month.aggregator_pct`)."""
    with SessionLocal() as db:
        rows = db.execute(select(PnlMonth.year, PnlMonth.month, PnlMonth.aggregator_pct)).all()
    return {(y, m): float(p or 0) for y, m, p in rows}


def aggregator_commission(df: date, dt: date) -> float:
    """Суммарная комиссия агрегатора за период = Σ по дням (агрег-выручка × ставку месяца).

    Ставка берётся помесячно из `pnl_month`; для месяцев без строки — дефолт 35%.
    """
    by_day = aggregator_revenue_by_day(df, dt)
    rates = _rates_by_month()
    total = 0.0
    for ds, rev in by_day.items():
        d = date.fromisoformat(ds)
        pct = rates.get((d.year, d.month), DEFAULT_AGGREGATOR_PCT)
        total += rev * pct / 100
    return total


def net_revenue(gross: float, df: date, dt: date) -> tuple[float, float, float]:
    """(чистая выручка, брутто-агрег-выручка, комиссия) для периода.

    Чистая = gross − комиссия. Брутто-агрег-выручка — сколько всего пришло через
    агрегатора (для показа «из них доставка …»). gross — уже посчитанная суммарная
    выручка периода (REV_GROSS), сюда её и передаём, чтобы не считать дважды.
    """
    agg_rev = sum(aggregator_revenue_by_day(df, dt).values())
    commission = aggregator_commission(df, dt)
    return gross - commission, agg_rev, commission
