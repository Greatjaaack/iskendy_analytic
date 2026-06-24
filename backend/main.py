"""Точка входа FastAPI: инициализация БД/хранилища, планировщик, подключение роутеров.

При старте (`lifespan`) создаём схему БД, готовим каталог файлов, запускаем планировщик
синков и делаем первый полный синк продаж из iiko.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

import storage
from cache import cache_clear
from models import SessionLocal, SyncLog, init_db
from routers import dishes, imports, nomenclature, plan, revenue, suppliers
from scheduler import full_sync, setup_scheduler, sync_dishes, sync_revenue

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    storage.ensure_dir()
    setup_scheduler()
    await full_sync()
    yield


app = FastAPI(title="Iskendy Analytics API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(revenue.router)
app.include_router(dishes.router)
app.include_router(suppliers.router)
app.include_router(nomenclature.router)
app.include_router(imports.router)
app.include_router(plan.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/sync/last")
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


@app.post("/api/sync")
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
        await sync_dishes(days)
    else:
        await full_sync()
    return {"status": "sync triggered"}
