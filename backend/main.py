"""Точка входа FastAPI: инициализация БД/хранилища, планировщик, подключение роутеров.

При старте (`lifespan`) создаём схему БД, готовим каталог файлов, запускаем планировщик
синков и делаем первый полный синк продаж из iiko.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

import storage
from auth import require_auth
from cache import cache_clear
from config import settings
from constants import OLAP_FIELD_OPEN_TIME, OLAP_FIELD_ORDER_NUM, OLAP_FIELD_SUM
from iiko_web_client import iiko_web
from models import SessionLocal, SyncLog, init_db
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

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


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

    Живой OLAP SALES по кассе (кэш 60с, см. cache_ttl_seconds) — при оплате-вперёд
    заказ закрывается сразу, поэтому попадает сюда за секунды. Read-only.
    """
    tz = ZoneInfo(settings.timezone)
    today = datetime.now(tz).date().isoformat()
    rows = await iiko_web.olap_sales(
        group_fields=[OLAP_FIELD_ORDER_NUM, OLAP_FIELD_OPEN_TIME],
        data_fields=[OLAP_FIELD_SUM],
        date_from=today,
        date_to=today,
    )
    orders = []
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
        "date": today,
        "orders": orders,
        "now": datetime.now(tz).strftime("%H:%M:%S"),
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
