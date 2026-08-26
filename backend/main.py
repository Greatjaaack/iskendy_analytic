"""Точка входа FastAPI: инициализация БД/хранилища, планировщик, подключение роутеров.

При старте (`lifespan`) создаём схему БД, готовим каталог файлов, запускаем планировщик
синков и делаем первый полный синк продаж из iiko.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

import storage
from auth import require_auth
from cache import cache_clear
from config import settings
from constants import OLAP_FIELD_OPEN_TIME, OLAP_FIELD_ORDER_NUM, OLAP_FIELD_SUM
from iiko_web_client import iiko_web
from models import Order, RevenueDaily, SessionLocal, SyncLog, init_db
from routers import (
    auth,
    dishes,
    imports,
    nomenclature,
    plan,
    pnl,
    revenue,
    schedule,
    suppliers,
)
from scheduler import (
    full_sync,
    run_startup_sync,
    setup_scheduler,
    sync_orders_recent,
    sync_revenue,
)
from services.aggregator import net_revenue

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    storage.ensure_dir()
    setup_scheduler()
    # выручка готовится сразу (быстро), а заказы + бэкафилл всей истории — в фоне,
    # чтобы старт не блокировался выкачкой истории (приложение отвечает мгновенно).
    await sync_revenue(days_back=31)
    asyncio.create_task(run_startup_sync())
    yield


app = FastAPI(title="Iskendy Analytics API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Авторизация: роутер логина — публичный; все остальные закрыты зависимостью require_auth.
app.include_router(auth.router)

protected = [Depends(require_auth)]
app.include_router(revenue.router, dependencies=protected)
app.include_router(dishes.router, dependencies=protected)
app.include_router(suppliers.router, dependencies=protected)
app.include_router(nomenclature.router, dependencies=protected)
app.include_router(imports.router, dependencies=protected)
app.include_router(plan.router, dependencies=protected)
app.include_router(pnl.router, dependencies=protected)
app.include_router(schedule.router, dependencies=protected)


@app.get("/api/health")
def health():
    return {"status": "ok"}


def _require_internal(x_internal_token: str = Header(default="")) -> None:
    """Сервис-сервисная авторизация внутренних ручек по общему токену из .env."""
    if not settings.internal_token or x_internal_token != settings.internal_token:
        raise HTTPException(status_code=401, detail="internal token required")


@app.get("/api/orders/today", dependencies=[Depends(_require_internal)])
async def orders_today():
    """Заказы за сегодня (номер + время открытия) для внешнего табло iskendy_site.

    Живой OLAP SALES по кассе — при оплате-вперёд заказ закрывается сразу, поэтому
    попадает сюда за секунды. Read-only.

    Три вещи, ради которых тут не просто один запрос:

    1. Пока за сегодня НЕТ ни одного заказа (ночь, точка закрыта), ходим в iiko раз
       в `idle_poll_seconds` вместо 6 раз в минуту: за ночь это экономит ~4 тысячи
       запросов ради пустого ответа. Признак — наличие заказов в БД, а НЕ время
       суток: точка открывалась и в 12:05, и в 13:01, и жёсткий час однажды съел бы
       первые заказы смены. Цена — первый заказ дня доедет с задержкой до минуты.
    2. OLAP в iikoweb периодически отвечает статусом ERROR — по истории `sync_log`
       93% таких сбоев приходятся на РАБОЧИЕ часы точки, то есть ровно тогда, когда
       заказы идут. Поэтому при ошибке переспрашиваем ещё раз.
    3. Если и повтор не удался — отдаём заказы из БД (их кладёт `sync_today` каждые
       3 минуты) вместо 500: табло продолжит работать на данных, отстающих на пару
       минут, вместо того чтобы ослепнуть. Это спасает от коротких морганий; при
       долгом обрыве iiko синк тоже ничего не заберёт, и БД устареет — поэтому
       каждый такой ответ пишется в лог WARNING, иначе лежачий iiko прятался бы за
       исправным на вид табло.
    """
    tz = ZoneInfo(settings.timezone)
    today = datetime.now(tz).date()
    today_iso = today.isoformat()

    with SessionLocal() as db:
        day_started = (
            db.execute(select(Order.id).where(Order.date == today).limit(1)).scalar_one_or_none()
            is not None
        )

    ttl = None if day_started else (settings.idle_poll_seconds or None)

    async def fetch_live() -> list[dict]:
        return await iiko_web.olap_sales(
            group_fields=[OLAP_FIELD_ORDER_NUM, OLAP_FIELD_OPEN_TIME],
            data_fields=[OLAP_FIELD_SUM],
            date_from=today_iso,
            date_to=today_iso,
            cache_ttl=ttl,
        )

    orders: list[dict] = []
    try:
        rows = await fetch_live()
    except Exception as first_error:
        logger.warning("orders/today: живой OLAP не ответил (%s), повторяю", first_error)
        await asyncio.sleep(1)
        try:
            rows = await fetch_live()
        except Exception as error:
            orders = _orders_from_db(today)
            logger.warning(
                "orders/today: iiko недоступен (%s), отдаю из БД: %d заказов "
                "(данные могут отставать на время синка)",
                error,
                len(orders),
            )
            rows = []

    for r in rows:
        # field0 = "<OrderNum>, <OpenTime ISO>" (склейка групп через ", ")
        value = r.get("field0", {}).get("value", "")
        parts = value.split(", ", 1)
        if len(parts) != 2:
            continue
        try:
            number = int(parts[0].strip())
        except ValueError:
            continue
        orders.append({"number": number, "openTime": parts[1].strip()})
    orders.sort(key=lambda o: o["number"])
    return {
        "date": today_iso,
        "orders": orders,
        "now": datetime.now(tz).strftime("%H:%M:%S"),
    }


def _orders_from_db(day: date) -> list[dict]:
    """Заказы дня из БД — запасной ответ табло, когда живой iiko недоступен.

    Те же поля, что у живого ответа: контракт от источника данных не зависит.
    Строки с нечисловым номером или без времени открытия пропускаем — на табло
    они всё равно бесполезны.
    """
    with SessionLocal() as db:
        rows = db.execute(select(Order.order_num, Order.open_time).where(Order.date == day)).all()
    out = []
    for num, open_time in rows:
        if not open_time:
            continue
        try:
            out.append({"number": int(str(num).strip()), "openTime": str(open_time)})
        except (TypeError, ValueError):
            continue
    return sorted(out, key=lambda o: o["number"])


@app.get("/api/summary", dependencies=[Depends(_require_internal)])
def summary(date_: str | None = Query(default=None, alias="date")):
    """Итоги дня для вечерней сводки iskendy_site: выручка, чеки, средний чек.

    Дата параметром (`?date=YYYY-MM-DD`), по умолчанию сегодня в поясе ресторана.
    Сводка уходит в полночь за ПРОШЕДШИЙ день, поэтому «сегодня» ей не годится.

    Только из БД (`revenue_daily`), живой iiko не дёргаем: ручка вызывается по
    расписанию, а не человеком, и не должна зависеть от доступности iikoweb.
    Выручка — ЧИСТАЯ, после комиссии агрегатора: та же цифра, что в KPI дашборда
    (`net_revenue`), иначе сводка и дашборд разошлись бы. Средний чек считается
    от неё же, а не берётся из `revenue_daily.avg_check` (там брутто из iiko).

    `has_data=false` — за этот день в БД нет строки (синк отстал или день ещё не
    наступил). Тогда все три числа нули, и печатать их в сводке как факт нельзя.
    """
    tz = ZoneInfo(settings.timezone)
    if date_:
        try:
            day = date.fromisoformat(date_)
        except ValueError:
            raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")
    else:
        day = datetime.now(tz).date()

    with SessionLocal() as db:
        row = db.execute(select(RevenueDaily).where(RevenueDaily.date == day)).scalar_one_or_none()

    if row is None:
        return {
            "date": day.isoformat(),
            "revenue": 0.0,
            "checks": 0,
            "avg_check": 0.0,
            "has_data": False,
        }

    gross = float(row.total_sum or 0)
    checks = int(row.check_count or 0)
    net, _, _ = net_revenue(gross, day, day)
    return {
        "date": day.isoformat(),
        "revenue": round(net, 2),
        "checks": checks,
        "avg_check": round(net / checks, 2) if checks else 0.0,
        "has_data": True,
    }


@app.get("/api/sync/last", dependencies=protected)
def last_sync():
    """Время последней успешной синхронизации (created_at в БД — naive UTC)."""
    with SessionLocal() as db:
        row = db.execute(
            select(SyncLog)
            .where(SyncLog.status == "ok")
            .order_by(SyncLog.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        if not row:
            return {"last_sync": None}
        return {
            "last_sync": row.created_at.isoformat() + "Z",
            "sync_type": row.sync_type,
        }


@app.post("/api/sync", dependencies=protected)
async def trigger_sync(days: int = 0):
    """Ручная/авто-синхронизация продаж из iiko в SQLite.

    `days` — окно синка: 0 (по умолчанию) — полный синк (31 день, кнопка «Синхронизировать»);
    >0 — лёгкий синк за последние `days` дней (автосинхронизация по таймеру на дашборде —
    прошлые дни уже в БД, обновлять нужно лишь свежие). Кэш живых чтений сбрасывается,
    чтобы дашборд получил актуальные данные сразу.
    """
    cache_clear()
    if days > 0:
        await sync_revenue(days)
        await sync_orders_recent(days)
    else:
        await full_sync()
    return {"status": "sync triggered"}
