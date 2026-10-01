"""Сбой кассы не роняет дашборд и не сыплет в лог чужими трейсами.

Оба случая найдены локальным прогоном 26.09.2026 с отключённой кассой: вкладка
«Сегодня» (открывается по умолчанию) отдавала 500, а на каждый сбой asyncio писал ERROR
«Future exception was never retrieved» с полным трейсом.
"""

import asyncio
import gc
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cache  # noqa: E402
from services import revenue_source  # noqa: E402

TODAY = date(2026, 9, 26)


def test_сбой_single_flight_без_шума_в_лог(caplog):
    async def boom():
        raise RuntimeError("касса легла")

    async def scenario():
        with pytest.raises(RuntimeError):
            await cache.cached_or_call("test:boom", boom)

    with caplog.at_level("ERROR", logger="asyncio"):
        asyncio.run(scenario())
        gc.collect()
    assert not [r for r in caplog.records if "never retrieved" in r.getMessage()]


def test_ждущие_получают_ту_же_ошибку():
    """Пометка «прочитано» не глотает ошибку у параллельных вызовов."""

    async def slow_boom():
        await asyncio.sleep(0.01)
        raise RuntimeError("касса легла")

    async def scenario():
        return await asyncio.gather(
            cache.cached_or_call("test:slow", slow_boom),
            cache.cached_or_call("test:slow", slow_boom),
            return_exceptions=True,
        )

    results = asyncio.run(scenario())
    assert [type(r) for r in results] == [RuntimeError, RuntimeError]


def test_отмена_по_таймауту_не_залипает_в_single_flight():
    """`wait_for` отменяет живой запрос ручки табло — ключ не должен остаться «в полёте».

    Найдено аудитом 01.10.2026: CancelledError не ловился как Exception, ключ навсегда
    оставался в `_inflight`, и каждый следующий вызов ждал мёртвый future весь потолок.
    """

    async def hang():
        await asyncio.sleep(10)

    async def fast():
        return ["заказ"]

    async def scenario():
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(cache.cached_or_call("test:hang", hang), timeout=0.01)
        assert "test:hang" not in cache._inflight
        return await asyncio.wait_for(cache.cached_or_call("test:hang", fast), timeout=1)

    assert asyncio.run(scenario()) == ["заказ"]


def test_ждущий_при_отмене_владельца_получает_обычную_ошибку():
    """Отмена запроса-владельца не пробрасывает CancelledError в чужие запросы."""

    async def hang():
        await asyncio.sleep(10)

    async def scenario():
        owner = asyncio.ensure_future(cache.cached_or_call("test:owner", hang))
        await asyncio.sleep(0)
        waiter = asyncio.ensure_future(cache.cached_or_call("test:owner", hang))
        await asyncio.sleep(0)
        owner.cancel()
        # Потолок, чтобы регрессия валила тест, а не вешала прогон.
        results = await asyncio.wait_for(
            asyncio.gather(owner, waiter, return_exceptions=True), timeout=2
        )
        return [type(r) for r in results]

    assert asyncio.run(scenario()) == [asyncio.CancelledError, RuntimeError]


def test_сегодня_без_кассы_отдаёт_дни_из_бд(monkeypatch, caplog):
    stored = [{"date": "2026-09-25", "total_sum": 100.0}]

    async def from_db(df, dt):
        return list(stored)

    async def live(df, dt):
        raise RuntimeError("касса легла")

    monkeypatch.setattr(revenue_source, "days_stored_or_live", from_db)
    monkeypatch.setattr(revenue_source, "days_live", live)
    monkeypatch.setattr(revenue_source, "today", lambda: TODAY)
    with caplog.at_level("WARNING"):
        days = asyncio.run(revenue_source.load_days(date(2026, 9, 25), TODAY, False))
    assert days == stored
    assert any("касса не ответила" in m for m in caplog.messages)
