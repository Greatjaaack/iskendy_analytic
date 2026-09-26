"""Источник дней и часов для выручки: своя БД, затем касса.

Порядок источников (и причина каждого шага):

1. **`revenue_daily`** — сводка по дням, её синкает планировщик за последний месяц.
2. **`order_items`** — позиции заказов, они есть за всю историю (бэкафилл). Дни, которых
   нет в сводке, считаются отсюда: числа те же (выручка без служебных строк, чек = заказ).
3. **Живая касса** — только за днями раньше начала сохранённой истории и за «сегодня», если
   частый синк его ещё не положил. До 25.09.2026 признаком был `is_custom`, и любой выбор
   дат календарём уходил в кассу: `/api/pnl` за месяц стоил 8 403 мс против 373 мс из БД.

Пробелы ВНУТРИ истории живым запросом не добираются: день без заказов — это закрытый день
(у точки таких семь за год), и касса вернёт по нему те же нули.

Почасовой разрез берётся из `orders` по **часу закрытия** заказа: именно так считает iiko —
проверено на боевых данных, все 12 часов сошлись до рубля и до чека, тогда как по часу
открытия расходилось на 1–2 % в каждом часе.

Вынесено из `routers/revenue.py` (этап 7а аудита): роутер остаётся тонким, а расчёты
становятся обычными функциями — их можно тестировать без HTTP и уносить в поток.
"""

import asyncio
import logging
from datetime import date, datetime

from sqlalchemy import func, select

from constants import DAY_NAMES_RU, ORDER_STATUS_CATEGORY
from models import Order, OrderItem, RevenueDaily, SessionLocal
from pos import get_pos
from services.order_store import stored_covers
from utils import daterange, today

logger = logging.getLogger(__name__)


def ru_dow(d: date) -> str:
    """Русское сокращение дня недели для даты."""
    return DAY_NAMES_RU[d.weekday()]


def day_dict(d: date, total, checks, avg, disc, refunds, cost) -> dict:
    total = float(total or 0)
    cost = float(cost or 0)
    return {
        "date": d.isoformat(),
        "day_of_week": ru_dow(d),
        "total_sum": total,
        "discount_sum": float(disc or 0),
        "refund_count": int(refunds or 0),
        "cost_sum": round(cost, 2),
        "check_count": int(checks or 0),
        "avg_check": round(float(avg or 0), 2),
        "food_cost_pct": round(cost / total * 100, 1) if total else 0,
    }


def days_from_db(date_from: date, date_to: date) -> list[dict]:
    with SessionLocal() as db:
        rows = (
            db.execute(
                select(RevenueDaily)
                .where(RevenueDaily.date >= date_from, RevenueDaily.date <= date_to)
                .order_by(RevenueDaily.date)
            )
            .scalars()
            .all()
        )
        # food cost — единый iiko-кост позиций (order_items.cost = ProductCostBase),
        # суммарно по дню. Fallback на revenue_daily.cost_sum (теоретич. расход iiko),
        # если позиционный кост за день пуст (день вне окна бэкафилла) — чтобы P&L и
        # food cost не обнулялись на неполных данных.
        item_cost = dict(
            db.execute(
                select(OrderItem.date, func.sum(OrderItem.cost))
                .where(OrderItem.date >= date_from, OrderItem.date <= date_to)
                .group_by(OrderItem.date)
            ).all()
        )
    return [
        day_dict(
            r.date,
            r.total_sum,
            r.check_count,
            r.avg_check,
            r.discount_sum,
            r.refund_count,
            item_cost.get(r.date) or r.cost_sum,
        )
        for r in rows
    ]


def days_from_items(date_from: date, date_to: date) -> list[dict]:
    """Дни периода, собранные из позиций заказов (`order_items`).

    Нужны там, где `revenue_daily` пуст, а заказы есть: сводка по дням синкается только
    за последний месяц, а позиции — за всю историю (бэкафилл). Раньше такие периоды
    уходили живым запросом в кассу — 8,4 секунды на месяц и полная зависимость от её
    доступности, хотя данные лежали в двух таблицах рядом.

    Числа те же, что в сводке: выручка — сумма позиций без служебных строк («Статус»),
    чек — заказ с хотя бы одной товарной позицией (номер уникален внутри дня), скидка —
    разница брутто и нетто. Возвратов в позициях нет, поэтому 0.
    """
    товарные = OrderItem.category != ORDER_STATUS_CATEGORY
    window = (OrderItem.date >= date_from, OrderItem.date <= date_to)
    with SessionLocal() as db:
        sums = db.execute(
            select(
                OrderItem.date,
                func.sum(OrderItem.sum),
                func.sum(OrderItem.net),
                func.sum(OrderItem.cost),
            )
            .where(*window, товарные)
            .group_by(OrderItem.date)
        ).all()
        checks = dict(
            db.execute(
                select(OrderItem.date, func.count(func.distinct(OrderItem.order_num)))
                .where(*window, товарные)
                .group_by(OrderItem.date)
            ).all()
        )
    days = []
    for day, gross, net, cost in sums:
        gross = float(gross or 0)
        count = int(checks.get(day, 0))
        days.append(
            day_dict(
                day,
                gross,
                count,
                gross / count if count else 0,
                max(0.0, gross - float(net or 0)),
                0,
                cost,
            )
        )
    return days


async def days_live(date_from: date, date_to: date) -> list[dict]:
    """Живой запрос сводки по дням у кассы (для произвольного диапазона вне БД)."""
    days = await get_pos().revenue_days(date_from, date_to)
    return [
        day_dict(
            d.date,
            d.revenue,
            d.checks,
            d.avg_check,
            d.discount_sum,
            d.refund_count,
            d.cost_sum,
        )
        for d in days
    ]


def history_start() -> date | None:
    """Первый день, о котором в БД вообще что-то есть (сводка или позиции)."""
    with SessionLocal() as db:
        starts = [
            db.execute(select(func.min(RevenueDaily.date))).scalar(),
            db.execute(select(func.min(OrderItem.date))).scalar(),
        ]
    known = [d for d in starts if d]
    return min(known) if known else None


async def days_stored_or_live(df: date, dt: date) -> list[dict]:
    """Дни периода: из БД, насколько она их покрывает; живой запрос — только за пределами.

    Источники по порядку: `revenue_daily` (сводка, синкается за месяц) → `order_items`
    (позиции, есть за всю историю) → живая касса. Раньше признаком был `is_custom`:
    любой выбор дат календарём уходил в кассу, даже когда все дни лежали в БД. Это
    стоило 8,4 секунды на `/api/pnl` за месяц (против 0,36 с из БД) и делало календарь
    заложником доступности кассы. Тот же путь нужен и для ПРОШЛОГО периода в KPI-дельтах:
    прошлый месяц почти всегда за окном сводки, но внутри истории позиций.

    Пробелы ВНУТРИ истории живым запросом не добираем: день без заказов — это закрытый
    день (у точки таких семь за год), и касса вернёт по нему те же нули.
    """
    days = days_from_db(df, dt)
    have = {d["date"] for d in days}

    gaps = [d for d in daterange(df, dt) if d.isoformat() not in have]
    if gaps:
        from_items = await asyncio.to_thread(days_from_items, min(gaps), max(gaps))
        days += [d for d in from_items if d["date"] not in have]
        have = {d["date"] for d in days}
        gaps = [d for d in daterange(df, dt) if d.isoformat() not in have]

    start = history_start()
    # дни старше сохранённой истории — их в БД нет и не будет, только касса их помнит
    before_history = [d for d in gaps if start is None or d < start]
    if before_history:
        live = await days_live(min(before_history), max(before_history))
        days += [d for d in live if d["date"] not in have]

    return sorted(days, key=lambda d: d["date"])


async def load_days(df: date, dt: date, is_custom: bool) -> list[dict]:
    """Дни периода для дашборда: `days_stored_or_live` + страховка на «сегодня».

    Сегодня держит в БД частый синк (`sync_today`), но в первые минуты после полуночи
    его там ещё нет — тогда добираем день живым запросом.

    Добор — страховка, а не источник: если касса не ответила, отдаём то, что есть в БД.
    Раньше сбой кассы здесь ронял всю ручку (500), и вкладка «Сегодня» — та, что
    открывается по умолчанию, — не показывала даже прошлые дни периода. Сегодняшний
    день появится со следующим удачным синком.
    """
    days = await days_stored_or_live(df, dt)
    have = {d["date"] for d in days}
    if dt >= today() and today().isoformat() not in have:
        try:
            live_today = await days_live(today(), today())
        except Exception as error:
            logger.warning("Сегодня нет в БД, а касса не ответила (%s) — отдаю из БД", error)
            return days
        days = sorted(days + live_today, key=lambda d: d["date"])
    return days


def hours_from_db(df: date, dt: date) -> tuple[dict[int, float], dict[int, int]]:
    """Выручка и чеки по часам суток из таблицы `orders`.

    Час берём по **закрытию** заказа, а не по открытию: именно так считает iiko, и это
    проверено на боевых данных за 01–20.09.2026 — все 12 часов сошлись с ответом кассы
    до рубля и до чека, тогда как по часу открытия расхождение было 1–2 % в каждом часе
    (чек, открытый в 10:59 и закрытый в 11:01, у кассы попадает в 11). У этой точки заказы
    короткие (в среднем 0,6 минуты), поэтому расхождение и было небольшим — но оно было.

    Если время закрытия не записано, используем час открытия (`orders.hour`).
    """
    rev: dict[int, float] = {}
    trn: dict[int, int] = {}
    with SessionLocal() as db:
        rows = db.execute(
            select(Order.hour, Order.close_time, Order.total_sum).where(
                Order.date >= df, Order.date <= dt
            )
        ).all()
    for open_hour, close_time, total in rows:
        hour = open_hour
        if close_time:
            try:
                hour = datetime.fromisoformat(str(close_time)).hour
            except ValueError:
                pass
        if hour is None:
            continue
        rev[hour] = round(rev.get(hour, 0.0) + float(total or 0), 2)
        trn[hour] = trn.get(hour, 0) + 1
    return rev, trn


async def hours_for_period(df: date, dt: date) -> tuple[dict[int, float], dict[int, int]]:
    """Выручка и чеки по часам суток за период: {час: выручка}, {час: чеки}.

    Из БД, если период покрыт сохранёнными заказами; иначе — живой почасовой разрез
    кассы. Раньше ходили в кассу всегда, хотя те же заказы лежат в БД.
    """
    if stored_covers(Order, df.isoformat(), dt.isoformat()):
        return await asyncio.to_thread(hours_from_db, df, dt)
    hours = await get_pos().hourly(df, dt)
    rev = {h: v.revenue for h, v in hours.items()}
    trn = {h: v.checks for h, v in hours.items()}
    return rev, trn
