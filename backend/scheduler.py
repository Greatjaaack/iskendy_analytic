"""Планировщик синхронизации продаж из iiko в SQLite (APScheduler).

Выручка по дням и расход блюд синкаются раз в час (за 7 дней) и полностью ночью
(за 30 дней). Дашборд читает выручку из БД, а блюда/почасовые — живым запросом.
"""

import logging
from datetime import date, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import settings
from constants import DAY_NAMES_EN
from iiko_web_client import iiko_web
from models import DishSale, RevenueDaily, SessionLocal, SyncLog
from utils import today

logger = logging.getLogger(__name__)

# Тот же пояс, что у границ «сегодня» (settings.timezone) — синки и определение
# текущего дня живут в одном времени, иначе ночной full_sync ловил бы не тот день.
scheduler = AsyncIOScheduler(timezone=settings.timezone)


def _g(metric: dict, code: str, key: str, default=0):
    """Достать значение метрики по коду и ключу (дата/uuid)."""
    return metric.get(code, {}).get(key, default)


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


async def sync_dishes(days_back: int = 7):
    """Расход блюд (по UUID; названия резолвятся отдельно — TODO словарь блюд)."""
    logger.info(f"Синк блюд за {days_back} дн...")
    date_to = today()
    date_from = date_to - timedelta(days=days_back - 1)

    try:
        rows = await iiko_web.dishes_detail(date_from.isoformat(), date_to.isoformat())

        with SessionLocal() as db:
            db.query(DishSale).filter(
                DishSale.date_from == date_from,
                DishSale.date_to == date_to,
            ).delete()
            for d in rows:
                db.add(
                    DishSale(
                        date_from=date_from,
                        date_to=date_to,
                        dish_id=d["dish_id"],
                        dish_name=d["dish_name"],
                        group_name=d["category"],
                        quantity=d["quantity"],
                        revenue=d["revenue"],
                        cost_sum=d["cost_sum"],
                    )
                )
            db.add(SyncLog(sync_type="dishes", status="ok"))
            db.commit()
        logger.info("Синк блюд завершён")
    except Exception as error:
        logger.exception("Синк блюд упал")  # traceback прикрепится сам
        with SessionLocal() as db:
            db.add(SyncLog(sync_type="dishes", status="error", message=str(error)))
            db.commit()


async def full_sync():
    # 31 день, чтобы покрыть «месяц» = с 1-го числа по сегодня даже в 31-дневном месяце
    await sync_revenue(days_back=31)
    await sync_dishes(days_back=31)


def setup_scheduler():
    scheduler.add_job(sync_revenue, "interval", hours=1, args=[7], id="revenue_hourly")
    scheduler.add_job(sync_dishes, "interval", hours=1, args=[7], id="dishes_hourly")
    scheduler.add_job(full_sync, "cron", hour=0, minute=5, id="full_midnight")
    scheduler.start()
    logger.info("Планировщик запущен")
