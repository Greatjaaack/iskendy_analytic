"""Простой in-memory TTL-кэш для дорогих живых чтений из iikoweb.

Дашборд за один период часто запрашивает один и тот же разрез несколькими виджетами,
а каждый живой вызов `get-data`/OLAP идёт во внешний API (медленно). Кэш с коротким
TTL (`settings.cache_ttl_seconds`) схлопывает повторы внутри окна свежести, не задерживая
обновление дольше TTL. Ключ строится из имени метода и его аргументов вызывающим кодом.

Кэш сбрасывается `cache_clear()` после ручной синхронизации — кнопка «Синхронизировать»
всегда отдаёт свежие данные, минуя кэш.
"""

import asyncio
import time
from typing import Any, Awaitable, Callable

from config import settings

# key -> (срок годности по monotonic-часам, значение)
_store: dict[str, tuple[float, Any]] = {}

# key -> future выполняющегося прямо сейчас живого запроса (single-flight): параллельные
# одинаковые вызовы ждут один результат, а не дублируют дорогой запрос к iikoweb.
_inflight: dict[str, "asyncio.Future[Any]"] = {}


def cache_get(key: str) -> Any | None:
    """Вернуть значение по ключу, если оно ещё не протухло, иначе None."""
    item = _store.get(key)
    if item is None:
        return None
    expiry, value = item
    if expiry < time.monotonic():
        _store.pop(key, None)
        return None
    return value


def cache_set(key: str, value: Any) -> None:
    """Положить значение с TTL `settings.cache_ttl_seconds` (при TTL<=0 — no-op)."""
    if settings.cache_ttl_seconds <= 0:
        return
    _store[key] = (time.monotonic() + settings.cache_ttl_seconds, value)


def cache_clear() -> None:
    """Сбросить весь кэш (после ручного синка, чтобы не отдавать устаревшие данные)."""
    _store.clear()


async def cached_or_call(key: str, factory: Callable[[], Awaitable[Any]]) -> Any:
    """Вернуть значение по ключу из кэша, иначе вызвать `factory()` РОВНО один раз.

    Single-flight: пока живой запрос с этим ключом в полёте, параллельные вызовы ждут
    его результат, а не запускают свой (дашборд грузит несколько виджетов за один
    период разом — иначе они дублировали бы один и тот же медленный запрос к iikoweb).
    Успешный результат кладётся в кэш с обычным TTL.
    """
    cached = cache_get(key)
    if cached is not None:
        return cached

    fut = _inflight.get(key)
    if fut is not None:
        return await fut

    fut = asyncio.get_running_loop().create_future()
    _inflight[key] = fut
    try:
        value = await factory()
    except Exception as error:
        _inflight.pop(key, None)
        if not fut.done():
            fut.set_exception(error)
        raise
    cache_set(key, value)
    _inflight.pop(key, None)
    if not fut.done():
        fut.set_result(value)
    return value
