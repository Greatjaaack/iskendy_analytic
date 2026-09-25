"""Точка входа FastAPI: инициализация БД/хранилища, планировщик, подключение роутеров.

При старте (`lifespan`) создаём схему БД, готовим каталог файлов, запускаем планировщик
синков и делаем первый полный синк продаж с кассы.
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
from models import Order, RevenueDaily, SessionLocal, SyncLog, init_db
from pos import get_pos
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

    Живое чтение с кассы через порт `pos` — при оплате-вперёд заказ закрывается
    сразу, поэтому попадает сюда за секунды. Read-only.

    Три вещи, ради которых тут не просто один запрос:

    1. Пока за сегодня НЕТ ни одного заказа (ночь, точка закрыта), ходим в кассу раз
       в `idle_poll_seconds` вместо 6 раз в минуту: за ночь это экономит ~4 тысячи
       запросов ради пустого ответа. Признак — наличие заказов в БД, а НЕ время
       суток: точка открывалась и в 12:05, и в 13:01, и жёсткий час однажды съел бы
       первые заказы смены. Цена — первый заказ дня доедет с задержкой до минуты.
    2. Касса периодически отвечает ошибкой (у iiko это статус OLAP ERROR) — по `sync_log`
       93% таких сбоев приходятся на РАБОЧИЕ часы точки, то есть ровно тогда, когда
       заказы идут. Поэтому при ошибке переспрашиваем ещё раз.
    3. Если и повтор не удался — отдаём заказы из БД (их кладёт `sync_today` каждые
       3 минуты) вместо 500: табло продолжит работать на данных, отстающих на пару
       минут, вместо того чтобы ослепнуть. Это спасает от коротких морганий; при
       долгом обрыве кассы синк тоже ничего не заберёт, и БД устареет — поэтому
       каждый такой ответ пишется в лог WARNING, иначе лежачая касса пряталась бы
       за исправным на вид табло.
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

    pos = get_pos()
    # Пока за сегодня нет ни одного заказа, живые чтения кэшируются дольше (см. ниже).
    if ttl is not None and hasattr(pos, "with_open_orders_ttl"):
        pos = pos.with_open_orders_ttl(ttl)

    async def fetch_live() -> list[dict]:
        found = await pos.open_orders(today)
        return [{"number": o.number, "openTime": o.open_time} for o in found]

    async def fetch_live_s_povtorom() -> list[dict]:
        try:
            return await fetch_live()
        except Exception as first_error:
            logger.warning("orders/today: касса не ответила (%s), повторяю", first_error)
            await asyncio.sleep(1)
            return await fetch_live()

    orders: list[dict] = []
    try:
        # Жёсткий потолок на весь живой путь, включая повтор. Без него попытка,
        # пауза и повтор складывались в 121 секунду — вчетверо дольше, чем табло
        # готово ждать, так что даже удачный ответ до него не доезжал.
        rows = await asyncio.wait_for(
            fetch_live_s_povtorom(), timeout=settings.orders_live_budget_sec
        )
    except Exception as error:
        orders = _orders_from_db(today)
        logger.warning(
            "orders/today: касса недоступна (%s), отдаю из БД: %d заказов "
            "(данные могут отставать на время синка)",
            type(error).__name__ if isinstance(error, asyncio.TimeoutError) else error,
            len(orders),
        )
        rows = []

    for r in rows:
        # Номер приводим к int, пока табло держит его числом (его схема:
        # `orders.number INTEGER`). В Saby номер продажи — СТРОКА, и нечисловой
        # номер табло молча отбросит, поэтому такой случай виден в логе: это
        # сигнал, что схему табло пора переводить на строковый номер.
        number = str(r.get("number", "")).strip()
        open_time = str(r.get("openTime", "")).strip()
        if not number or not open_time:
            continue
        try:
            orders.append({"number": int(number), "openTime": open_time})
        except ValueError:
            logger.warning(
                "orders/today: нечисловой номер заказа %r — табло его не примет "
                "(нужна миграция схемы табло на строковый номер)",
                number,
            )
    orders.sort(key=lambda o: o["number"])
    return {
        "date": today_iso,
        "orders": orders,
        "now": datetime.now(tz).strftime("%H:%M:%S"),
    }


def _orders_from_db(day: date) -> list[dict]:
    """Заказы дня из БД — запасной ответ табло, когда живая касса недоступна.

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

    Только из БД (`revenue_daily`), живую кассу не дёргаем: ручка вызывается по
    расписанию, а не человеком, и не должна зависеть от доступности кассы.
    Выручка — ЧИСТАЯ, после комиссии агрегатора: та же цифра, что в KPI дашборда
    (`net_revenue`), иначе сводка и дашборд разошлись бы. Средний чек считается
    от неё же, а не берётся из `revenue_daily.avg_check` (там брутто с кассы).

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
    """Ручная/авто-синхронизация продаж с кассы в SQLite.

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
