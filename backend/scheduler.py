"""Планировщик синхронизации продаж из iiko в SQLite (APScheduler).

Дашборд читает ВСЁ из БД; живые запросы к iiko делает только этот планировщик.
- Выручка по дням (`revenue_daily`) — `sync_revenue`.
- Заказы (`order_items`/`orders`/`dish_detail`) — `sync_orders_recent` (свежие дни)
  и `backfill` (вся история; закрытые дни в iiko неизменны → тянем один раз).
`order_items` за весь диапазон тянется ОДНИМ OLAP-запросом (группировка включает
дату); `dish_detail` (нужен `product_type`) — по дню через get-data.
"""

import logging
from collections import defaultdict
from datetime import date, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import func, select

from config import settings
from constants import (
    CHANNEL_DINEIN,
    DAY_NAMES_EN,
    OLAP_FIELD_DISH_CATEGORY,
    OLAP_FIELD_DISH_NAME,
    OLAP_FIELD_GUESTS,
    OLAP_FIELD_HOUR,
    OLAP_FIELD_OPEN_DATE,
    OLAP_FIELD_ORDER_NUM,
    OLAP_FIELD_QTY,
    OLAP_FIELD_SUM,
    ORDER_STATUS_CATEGORY,
    ORDER_STATUS_CHANNELS,
)
from iiko_web_client import iiko_web
from models import (
    DishDetail,
    Order,
    OrderItem,
    RevenueDaily,
    SessionLocal,
    SyncLog,
)
from services.daypart import hour_to_daypart
from services.olap_parse import split_field_5
from utils import is_delivery, today

logger = logging.getLogger(__name__)

# Тот же пояс, что у границ «сегодня» (settings.timezone) — синки и определение
# текущего дня живут в одном времени, иначе ночной full_sync ловил бы не тот день.
scheduler = AsyncIOScheduler(timezone=settings.timezone)


def _g(metric: dict, code: str, key: str, default=0):
    """Достать значение метрики по коду и ключу (дата/uuid)."""
    return metric.get(code, {}).get(key, default)


def _daterange(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


# ---------- Выручка по дням ----------


async def sync_revenue(days_back: int = 7):
    """Выручка/чеки/средний чек/себестоимость по дням."""
    logger.info(f"Синк выручки за {days_back} дн...")
    date_to = today()
    date_from = date_to - timedelta(days=days_back - 1)

    try:
        data = await iiko_web.revenue_by_day(date_from.isoformat(), date_to.isoformat())

        # data = {"REV_GROSS": {"2026-06-17": 11780, ...}, "TRN_ALL": {...}, ...}
        all_dates = set()
        for code in data.values():
            all_dates.update(code.keys())

        with SessionLocal() as db:
            for d_str in sorted(all_dates):
                d = date.fromisoformat(d_str)
                rev = float(_g(data, "REV_GROSS", d_str) or 0)
                checks = int(_g(data, "TRN_ALL", d_str) or 0)
                avg = float(_g(data, "AVERAGE_SPEND_GROSS", d_str) or 0)
                disc = float(_g(data, "ACC_CAT_DISCOUNT_AMT", d_str) or 0)
                refunds = int(_g(data, "REFUND_TRN", d_str) or 0)
                cost = float(_g(data, "PRODUCTS_USAGE_THEO_AMT", d_str) or 0)

                row = db.get(RevenueDaily, d)
                if not row:
                    row = RevenueDaily(date=d)
                    db.add(row)
                row.day_of_week = DAY_NAMES_EN[d.weekday()]
                row.total_sum = rev
                row.check_count = checks
                row.avg_check = avg
                row.discount_sum = disc
                row.refund_count = refunds
                row.cost_sum = cost

            db.add(SyncLog(sync_type="revenue", status="ok"))
            db.commit()
        logger.info("Синк выручки завершён")
    except Exception as error:
        logger.exception("Синк выручки упал")  # traceback прикрепится сам
        with SessionLocal() as db:
            db.add(SyncLog(sync_type="revenue", status="error", message=str(error)))
            db.commit()


# ---------- Заказы (order_items / orders / dish_detail) ----------


def _parse_order_rows(rows: list[dict]) -> list[dict]:
    """OLAP-строки суперсета [дата, час, заказ, категория, имя]+[sum,qty,guests] → dict-и."""
    out = []
    for r in rows:
        ds, hs, order_num, category, name = split_field_5(r.get("field0", {}).get("value", ""))
        if not ds:
            continue
        try:
            d = date.fromisoformat(ds)
        except ValueError:
            continue
        try:
            hour = int(hs)
        except (ValueError, TypeError):
            hour = None
        out.append(
            {
                "date": d,
                "hour": hour,
                "order_num": order_num,
                "category": category,
                "name": name,
                "sum": float(r.get("field1", {}).get("value", 0) or 0),
                "qty": float(r.get("field2", {}).get("value", 0) or 0),
                "guests": float(r.get("field3", {}).get("value", 0) or 0),
            }
        )
    return out


def _build_orders(items: list[dict]) -> list[dict]:
    """Из позиций заказа собрать обогащённые чек-сущности.

    Канал — из модификатора «Статус»; `is_delivery` — бизнес-правило доставки
    (категория «Доставка» ИЛИ маркер `_д`, как на дашборде); `daypart`/`weekday` —
    из часа/даты; `dish_count` — число разных товарных позиций.
    """
    h2dp = hour_to_daypart()
    by_order: dict[tuple, list[dict]] = defaultdict(list)
    for it in items:
        by_order[(it["date"], it["order_num"])].append(it)

    orders = []
    for (d, onum), its in by_order.items():
        channel = CHANNEL_DINEIN
        guests = 0.0
        total = 0.0
        item_count = 0.0
        hour = None
        delivery = False
        names: set[str] = set()
        for it in its:
            if it["category"] == ORDER_STATUS_CATEGORY:
                ch = ORDER_STATUS_CHANNELS.get((it["name"] or "").strip().lower())
                if ch:
                    channel = ch
                continue  # «Статус» — не товарная позиция
            total += it["sum"]
            item_count += it["qty"]
            guests = max(guests, it["guests"])
            names.add(it["name"])
            if is_delivery(it["category"], it["name"]):
                delivery = True
            if it["hour"] is not None:
                hour = it["hour"] if hour is None else min(hour, it["hour"])
        orders.append(
            {
                "date": d,
                "order_num": onum,
                "hour": hour,
                "weekday": d.weekday(),
                "daypart": h2dp.get(hour) if hour is not None else None,
                "channel": channel,
                "is_delivery": delivery,
                "guests": guests,
                "total_sum": total,
                "item_count": item_count,
                "dish_count": len(names),
            }
        )
    return orders


async def sync_orders_range(date_from: date, date_to: date):
    """Заполнить `order_items`/`orders` за диапазон ОДНИМ OLAP-запросом (replace по дням)."""
    rows = await iiko_web.olap_sales(
        group_fields=[
            OLAP_FIELD_OPEN_DATE,
            OLAP_FIELD_HOUR,
            OLAP_FIELD_ORDER_NUM,
            OLAP_FIELD_DISH_CATEGORY,
            OLAP_FIELD_DISH_NAME,
        ],
        data_fields=[OLAP_FIELD_SUM, OLAP_FIELD_QTY, OLAP_FIELD_GUESTS],
        date_from=date_from.isoformat(),
        date_to=date_to.isoformat(),
    )
    items = _parse_order_rows(rows)
    with SessionLocal() as db:
        db.query(OrderItem).filter(OrderItem.date >= date_from, OrderItem.date <= date_to).delete()
        db.query(Order).filter(Order.date >= date_from, Order.date <= date_to).delete()
        db.bulk_save_objects([OrderItem(**it) for it in items])
        db.bulk_save_objects([Order(**o) for o in _build_orders(items)])
        db.commit()


async def sync_dish_detail_day(day: date):
    """Заполнить `dish_detail` за один день (get-data DATA_DETAILS, нужен `product_type`)."""
    rows = await iiko_web.dishes_detail(day.isoformat(), day.isoformat())
    with SessionLocal() as db:
        db.query(DishDetail).filter(DishDetail.date == day).delete()
        db.bulk_save_objects(
            [
                DishDetail(
                    date=day,
                    dish_id=r["dish_id"],
                    dish_name=r["dish_name"],
                    category=r["category"],
                    product_type=r["product_type"],
                    quantity=r["quantity"],
                    revenue=r["revenue"],
                    cost_sum=r["cost_sum"],
                )
                for r in rows
            ]
        )
        db.commit()


async def sync_orders_recent(days_back: int = 7):
    """Пере-синк свежих дней: order_items одним запросом + dish_detail по дню."""
    logger.info(f"Синк заказов за {days_back} дн...")
    date_to = today()
    date_from = date_to - timedelta(days=days_back - 1)
    try:
        await sync_orders_range(date_from, date_to)
        for d in _daterange(date_from, date_to):
            await sync_dish_detail_day(d)
        with SessionLocal() as db:
            db.add(SyncLog(sync_type="orders", status="ok"))
            db.commit()
        logger.info("Синк заказов завершён")
    except Exception as error:
        logger.exception("Синк заказов упал")
        with SessionLocal() as db:
            db.add(SyncLog(sync_type="orders", status="error", message=str(error)))
            db.commit()


async def _history_start() -> date | None:
    """Начало истории: из настройки либо probe по выручке (первая дата с продажами)."""
    if settings.history_start_date:
        return settings.history_start_date
    date_to = today()
    probe_from = date_to - timedelta(days=3650)  # до ~10 лет назад; ответ разрежён
    data = await iiko_web.revenue_by_day(probe_from.isoformat(), date_to.isoformat())
    dates: set[str] = set()
    for code in data.values():
        dates.update(code.keys())
    if not dates:
        return None
    return min(date.fromisoformat(x) for x in dates)


async def backfill():
    """Один раз выкачать всю историю заказов в БД (идемпотентно, пропускает заполненное).

    `order_items` — одним OLAP-запросом на весь диапазон (быстро, чинит OLAP-разрезы
    сразу). `dish_detail` — по дню (нужен `product_type`), newest→oldest, в фоне.
    """
    try:
        start = await _history_start()
    except Exception:
        logger.exception("backfill: probe начала истории упал")
        return
    if not start:
        logger.warning("backfill: история продаж пуста — нечего заполнять")
        return

    date_to = today()
    try:
        await sync_orders_range(start, date_to)
        logger.info("backfill: order_items заполнены (%s..%s)", start, date_to)
    except Exception:
        logger.exception("backfill: order_items упал")

    # dish_detail заполняем только за дни, где реально есть заказы: начало истории
    # из probe может быть завышено (revenue_by_day отдаёт стартовую дату окна), а
    # фактический минимум — это первая дата в order_items. Иначе гоняли бы тысячи
    # пустых дней get-data впустую.
    with SessionLocal() as db:
        real_start = db.execute(select(func.min(OrderItem.date))).scalar()
        have = {d for (d,) in db.execute(select(DishDetail.date).distinct()).all()}
    if real_start is None:
        logger.info("backfill: заказов нет — dish_detail пропускаем")
        return
    days = sorted((d for d in _daterange(real_start, date_to) if d not in have), reverse=True)
    logger.info("backfill: dish_detail — %d дней (с %s)", len(days), real_start)
    for i, d in enumerate(days, 1):
        try:
            await sync_dish_detail_day(d)
        except Exception:
            logger.exception("backfill: dish_detail %s упал", d)
        if i % 20 == 0:
            logger.info("backfill dish_detail: %d/%d", i, len(days))
    logger.info("backfill завершён")


async def full_sync():
    """Полный синк свежих данных (кнопка «Синхронизировать», ночной job, старт).

    Глубокую историю не трогает (она неизменна) — это делает `backfill`.
    """
    await sync_revenue(days_back=31)
    await sync_orders_recent(days_back=7)


async def run_startup_sync():
    """Фоновый стартовый синк: свежие заказы + бэкафилл всей истории."""
    await sync_orders_recent(days_back=7)
    await backfill()


async def nightly():
    await full_sync()
    await backfill()


def setup_scheduler():
    scheduler.add_job(sync_revenue, "interval", hours=1, args=[7], id="revenue_hourly")
    scheduler.add_job(sync_orders_recent, "interval", hours=1, args=[7], id="orders_hourly")
    scheduler.add_job(nightly, "cron", hour=0, minute=5, id="full_midnight")
    scheduler.start()
    logger.info("Планировщик запущен")
