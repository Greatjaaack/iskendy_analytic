"""Точка входа FastAPI: инициализация БД/хранилища, планировщик, подключение роутеров.

При старте (`lifespan`) создаём схему БД, готовим каталог файлов, запускаем планировщик
синков и делаем первый полный синк продаж из iiko.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import storage
from models import init_db
from routers import dishes, imports, nomenclature, revenue, suppliers
from scheduler import full_sync, setup_scheduler

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


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/sync")
async def trigger_sync():
    await full_sync()
    return {"status": "sync triggered"}
