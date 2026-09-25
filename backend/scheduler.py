"""Планировщик синхронизации продаж с кассы в SQLite (APScheduler).

Дашборд читает ВСЁ из БД; живые запросы к кассе делает только этот планировщик.
- Выручка по дням (`revenue_daily`) — `sync_revenue`.
- Заказы (`order_items`/`orders`/`order_payments`/`dish_detail`) — `sync_orders_recent`
  (свежие дни) и `backfill` (вся история; закрытые дни касса не меняет → тянем однократно).

Какая касса за этим стоит, планировщик не знает: он работает с портом `pos.PosClient`
(адаптеры iiko/Saby в `backend/pos/`). Раньше здесь же разбирались OLAP-строки iiko —
теперь этот разбор живёт в адаптере, а сюда приходят готовые заказы.
"""

import logging
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import func, select

import weather
from config import settings
from constants import DAY_NAMES_EN
from models import (
    DishDetail,
    Order,
    OrderItem,
    OrderPayment,
    RevenueDaily,
    SessionLocal,
    SyncLog,
)
from pos import get_pos, to_item_rows, to_order_rows, to_payment_rows
from utils import today

logger = logging.getLogger(__name__)

# Тот же пояс, что у границ «сегодня» (settings.timezone) — синки и определение
# текущего дня живут в одном времени, иначе ночной full_sync ловил бы не тот день.
scheduler = AsyncIOScheduler(timezone=settings.timezone)


def _daterange(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def sync_window(date_from: date, date_to: date) -> tuple[date, date] | None:
    """Обрезать окно синка по дате, с которой работает текущая касса.

    ⚠️ Это предохранитель истории. Синк заказов заменяет данные по дням (delete +
    insert), а новая касса о старых днях не знает НИЧЕГО: Saby отдаёт только свои
    продажи. Без обрезки первый же `sync_orders_recent(7)` после переключения стёр бы
    неделю истории iiko, а `backfill` — всю её целиком, и вернуть было бы нечего:
    в iiko мы уже не ходим, а больше она нигде не лежит.

    `POS_SWITCH_DATE` — день, с которого данные берёт текущий провайдер. Дни раньше
    него синк не трогает вовсе. Не задана — ведём себя как раньше (актуально для iiko,
    у которого история своя).

    Возвращает суженное окно или `None`, если от окна ничего не осталось.
    """
    start = settings.pos_switch_date
    if start and date_from < start:
        date_from = start
    if date_from > date_to:
        return None
    return date_from, date_to


# ---------- Выручка по дням ----------


async def sync_revenue(days_back: int = 7):
    """Выручка/чеки/средний чек/себестоимость по дням (upsert по дате)."""
    logger.info(f"Синк выручки за {days_back} дн...")
    window = sync_window(today() - timedelta(days=days_back - 1), today())
    if window is None:
        logger.info("Синк выручки: окно раньше даты переключения кассы — пропускаю")
        return
    date_from, date_to = window

    try:
        days = await get_pos().revenue_days(date_from, date_to)

        with SessionLocal() as db:
            for day in days:
                if day.date < date_from:  # касса отдала лишний день — не трогаем историю
                    continue
                row = db.get(RevenueDaily, day.date)
                if not row:
                    row = RevenueDaily(date=day.date)
                    db.add(row)
                row.day_of_week = DAY_NAMES_EN[day.date.weekday()]
                row.total_sum = day.revenue
                row.check_count = day.checks
                row.avg_check = day.avg_check
                row.discount_sum = day.discount_sum
                row.refund_count = day.refund_count
                row.cost_sum = day.cost_sum

            db.add(SyncLog(sync_type="revenue", status="ok"))
            db.commit()
        logger.info("Синк выручки завершён")
    except Exception as error:
        logger.exception("Синк выручки упал")  # traceback прикрепится сам
        with SessionLocal() as db:
            db.add(SyncLog(sync_type="revenue", status="error", message=str(error)))
            db.commit()


# ---------- Заказы (order_items / orders / order_payments / dish_detail) ----------


async def sync_orders_range(date_from: date, date_to: date):
    """Заполнить `order_items`/`orders`/`order_payments` за диапазон (replace по дням).

    Заказы приходят от адаптера кассы уже разобранными (`pos.PosOrder`); здесь только
    раскладка их по трём таблицам и замена диапазона одной транзакцией.

    Два предохранителя истории:
    1. Окно обрезается по `POS_SWITCH_DATE` (см. `sync_window`) — новая касса не должна
       переписывать дни, которых она не видела.
    2. Пустой ответ кассы по диапазону, где в БД заказы ЕСТЬ, считается сбоем, а не
       «продаж не было»: данные остаются как есть. Иначе одна кривая выборка (у iiko
       OLAP умеет отвечать пустотой вместо ошибки) обнуляла бы день на дашборде и в
       запасном ответе табло — до следующего удачного синка.
    """
    window = sync_window(date_from, date_to)
    if window is None:
        logger.info("Синк заказов: окно раньше даты переключения кассы — пропускаю")
        return
    date_from, date_to = window

    orders = await get_pos().orders(date_from, date_to)
    items = to_item_rows(orders)
    order_rows = to_order_rows(orders)
    payments = to_payment_rows(orders)

    if not items:
        with SessionLocal() as db:
            have = (
                db.query(OrderItem)
                .filter(OrderItem.date >= date_from, OrderItem.date <= date_to)
                .count()
            )
        if have:
            logger.warning(
                "Синк заказов %s..%s: касса отдала 0 позиций, а в БД их %d — "
                "считаю это сбоем выборки и НЕ затираю данные",
                date_from,
                date_to,
                have,
            )
            return

    with SessionLocal() as db:
        db.query(OrderItem).filter(OrderItem.date >= date_from, OrderItem.date <= date_to).delete()
        db.query(Order).filter(Order.date >= date_from, Order.date <= date_to).delete()
        db.query(OrderPayment).filter(
            OrderPayment.date >= date_from, OrderPayment.date <= date_to
        ).delete()
        db.bulk_save_objects([OrderItem(**asdict(it)) for it in items])
        db.bulk_save_objects([Order(**o) for o in order_rows])
        db.bulk_save_objects([OrderPayment(**p) for p in payments])
        db.commit()


async def sync_dish_detail_day(day: date):
    """Заполнить `dish_detail` за один день (продажи по номенклатуре + тип позиции).

    Те же два предохранителя, что в `sync_orders_range`: день раньше переключения кассы
    не трогаем, пустой ответ поверх непустого дня считаем сбоем выборки.
    """
    if sync_window(day, day) is None:
        return
    rows = await get_pos().products(day)
    with SessionLocal() as db:
        if not rows and db.query(DishDetail).filter(DishDetail.date == day).count():
            logger.warning(
                "dish_detail %s: касса отдала пусто поверх непустого дня — пропускаю", day
            )
            return
        db.query(DishDetail).filter(DishDetail.date == day).delete()
        db.bulk_save_objects(
            [
                DishDetail(
                    date=day,
                    dish_id=r.product_id,
                    dish_name=r.name,
                    category=r.category,
                    product_type=r.product_type,
                    quantity=r.quantity,
                    revenue=r.revenue,
                    cost_sum=r.cost_sum,
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
    """Начало истории: из настройки, иначе спрашиваем кассу (если она умеет probe).

    Ниже даты переключения кассы не опускаемся: старые дни уже лежат в БД, и новая
    касса о них ничего не знает — бэкафиллить их значит затирать историю пустотой.
    """
    start = settings.history_start_date or await get_pos().history_start()
    switch = settings.pos_switch_date
    if start and switch:
        return max(start, switch)
    return start or switch


async def backfill():
    """Один раз выкачать всю историю заказов в БД (идемпотентно, пропускает заполненное).

    `order_items` — одним запросом на весь диапазон (быстро, сразу чинит все разрезы
    дашборда). `dish_detail` — по дню (нужен тип позиции), newest→oldest, в фоне.
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
    # из probe может быть завышено (сводка по дням отдаёт стартовую дату окна), а
    # фактический минимум — это первая дата в order_items. Иначе гоняли бы тысячи
    # пустых дней впустую.
    with SessionLocal() as db:
        real_start = db.execute(select(func.min(OrderItem.date))).scalar()
        have = {d for (d,) in db.execute(select(DishDetail.date).distinct()).all()}
    if real_start is None:
        logger.info("backfill: заказов нет — dish_detail пропускаем")
        return
    switch = settings.pos_switch_date
    days = sorted(
        (
            d
            for d in _daterange(real_start, date_to)
            if d not in have and not (switch and d < switch)
        ),
        reverse=True,
    )
    logger.info("backfill: dish_detail — %d дней (с %s)", len(days), real_start)
    for i, d in enumerate(days, 1):
        try:
            await sync_dish_detail_day(d)
        except Exception:
            logger.exception("backfill: dish_detail %s упал", d)
        if i % 20 == 0:
            logger.info("backfill dish_detail: %d/%d", i, len(days))
    logger.info("backfill завершён")


async def sync_today():
    """Частый лёгкий синк текущего дня в БД — держит «сегодня» свежим для дашборда.

    Дашборд отдаёт «сегодня» из БД (быстро, без живого запроса на пути запроса), а этот
    job «прогревает» БД раз в `settings.today_sync_seconds`. Берём 2 дня, чтобы захватить
    и вчера на стыке полуночи. Ошибки логируются внутри `sync_revenue`/`sync_orders_recent`.
    """
    await sync_revenue(days_back=2)
    await sync_orders_recent(days_back=2)


async def full_sync():
    """Полный синк свежих данных (кнопка «Синхронизировать», ночной job, старт).

    Глубокую историю не трогает (она неизменна) — это делает `backfill`.
    """
    await sync_revenue(days_back=31)
    await sync_orders_recent(days_back=7)


async def run_startup_sync():
    """Фоновый стартовый синк: прогрев погоды + свежие заказы + бэкафилл всей истории."""
    await weather.prewarm()
    await sync_orders_recent(days_back=7)
    await backfill()


def prune_sync_log() -> int:
    """Удалить записи журнала синков старше `settings.sync_log_keep_days`.

    Журнал нужен для разбора («когда синк падал и почему»), но каждый успешный синк
    пишет строку, а `sync_today` идёт раз в три минуты: к 25.09.2026 в таблице было
    86 196 строк — больше, чем самих позиций заказов (39 045). Месяца истории хватает:
    ошибки разбираются по горячим следам, а `/api/sync/last` смотрит только последнюю
    удачную запись. Возвращает число удалённых строк.
    """
    keep = settings.sync_log_keep_days
    if keep <= 0:
        return 0
    edge = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=keep)
    with SessionLocal() as db:
        removed = db.query(SyncLog).filter(SyncLog.created_at < edge).delete()
        db.commit()
    if removed:
        logger.info("журнал синков: удалено %d записей старше %d дней", removed, keep)
    return removed


async def nightly():
    await full_sync()
    await backfill()
    prune_sync_log()


async def keep_session_warm():
    """Прогреть авторизацию кассы, чтобы она не случилась на запросе пользователя.

    У iiko это cookie-сессия с TTL ~20 мин, поднимаемая headless-браузером (секунды);
    у Saby — сервисный токен и каталог номенклатуры. Ручка табло ходит в кассу вживую,
    и логин посреди её запроса стоил бы этих секунд ожидания.
    """
    try:
        await get_pos().warm()
    except Exception:
        logger.exception("keep_session_warm: не удалось прогреть авторизацию кассы")


def setup_scheduler():
    scheduler.add_job(sync_revenue, "interval", hours=1, args=[7], id="revenue_hourly")
    scheduler.add_job(sync_orders_recent, "interval", hours=1, args=[7], id="orders_hourly")
    scheduler.add_job(nightly, "cron", hour=0, minute=5, id="full_midnight")
    scheduler.add_job(keep_session_warm, "interval", minutes=10, id="session_keepalive")
    scheduler.add_job(weather.prewarm, "interval", hours=6, id="weather_prewarm")
    if settings.today_sync_seconds > 0:
        scheduler.add_job(
            sync_today,
            "interval",
            seconds=settings.today_sync_seconds,
            id="today_refresh",
        )
    scheduler.start()
    logger.info("Планировщик запущен")
