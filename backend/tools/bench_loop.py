"""Инструмент: держит ли тяжёлая ручка event loop.

Запуск (из `backend/`):

    PARITY_DB=/путь/к/копии.db python3 tools/bench_loop.py

Пока дашборд считает разрез, в том же процессе живёт ручка табло `/api/orders/today`.
Если loop занят подсчётом, заказы к гостю не едут — поэтому смысл замера не в скорости
ручки, а в **максимальном разрыве между ответами** `/api/health` под нагрузкой.

Замеры на копии боевой базы (месяц данных, 4 тяжёлые ручки параллельно):
- до выноса чтения и агрегации в поток: разрыв **716 мс**, 9 пингов;
- после (`services/order_store.py` через `asyncio.to_thread`): **120–175 мс** (разброс
  между прогонами), около 100 пингов.

Остаток — агрегация внутри самих роутеров; он уйдёт, когда расчёты переедут из роутеров
в `services/`. Цена выноса: сами ручки стали медленнее на 5–50 мс (переключение потоков),
и это сознательный обмен — заказы на табло важнее скорости виджета.
"""

import asyncio
import logging
import os
import statistics
import sys
import time

import httpx

os.environ.update(
    DATABASE_URL="sqlite:///" + os.environ["PARITY_DB"],
    AUTH_PASSWORD="b",
    POS_PROVIDER="iiko",
    CACHE_TTL_SECONDS="0",
)
sys.path.insert(0, ".")

logging.getLogger("httpx").setLevel(logging.WARNING)

import main  # noqa: E402

Q = "date_from=2026-09-01&date_to=2026-09-25"
HEAVY = [
    f"dishes/basket?{Q}&group=dish",
    f"dishes/check-fullness?{Q}",
    f"dishes/check-composition?{Q}",
    f"revenue/ops-report?{Q}",
]


async def measure() -> None:
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        login = await client.post("/api/auth/login", json={"username": "admin", "password": "b"})
        headers = {"Authorization": f"Bearer {login.json()['token']}"}

        idle = []
        for _ in range(10):
            started = time.perf_counter()
            await client.get("/api/health")
            idle.append((time.perf_counter() - started) * 1000)
        print(f"   health без нагрузки : медиана {statistics.median(idle):6.1f} мс")

        # Важен не сам ответ health, а РАЗРЫВ между ответами: он и равен времени,
        # которое event loop был занят и никого не обслуживал.
        stamps: list[float] = []
        stop = False

        async def pinger() -> None:
            while not stop:
                await client.get("/api/health")
                stamps.append(time.perf_counter())
                await asyncio.sleep(0.005)

        ping = asyncio.create_task(pinger())
        await asyncio.sleep(0.05)
        started = time.perf_counter()
        await asyncio.gather(*(client.get(f"/api/{u}", headers=headers) for u in HEAVY))
        heavy_ms = (time.perf_counter() - started) * 1000
        stop = True
        await ping

        gaps = [(b - a) * 1000 for a, b in zip(stamps, stamps[1:])]
        print(f"   4 тяжёлых ручки заняли {heavy_ms:.0f} мс")
        print(f"   пингов health за это время: {len(gaps) + 1}")
        print(f"   МАКС разрыв между пингами: {max(gaps):6.1f} мс (столько loop был занят)")
        print(f"   медианный разрыв: {statistics.median(gaps):6.1f} мс")


if __name__ == "__main__":
    asyncio.run(measure())
