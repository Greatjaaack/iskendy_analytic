"""Простой in-memory TTL-кэш для дорогих живых чтений из iikoweb.

Дашборд за один период часто запрашивает один и тот же разрез несколькими виджетами,
а каждый живой вызов `get-data`/OLAP идёт во внешний API (медленно). Кэш с коротким
TTL (`settings.cache_ttl_seconds`) схлопывает повторы внутри окна свежести, не задерживая
обновление дольше TTL. Ключ строится из имени метода и его аргументов вызывающим кодом.

Кэш сбрасывается `cache_clear()` после ручной синхронизации — кнопка «Синхронизировать»
всегда отдаёт свежие данные, минуя кэш.
"""

import time
from typing import Any

from config import settings

# key -> (срок годности по monotonic-часам, значение)
_store: dict[str, tuple[float, Any]] = {}


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
