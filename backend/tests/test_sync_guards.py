"""Предохранители синка: история кассы, которой уже нет, не должна затираться.

Два сценария, каждый из которых однажды стоил бы всей истории продаж:

1. **Переезд кассы.** Синк заказов заменяет данные по дням (delete + insert). Новая
   касса (Saby) о днях до переезда не знает ничего, поэтому первый же `sync_orders_recent`
   после переключения стёр бы неделю, а `backfill` — все 288 дней истории iiko. Вернуть
   их неоткуда: в iiko мы уже не ходим, и больше они нигде не лежат.
2. **Пустой ответ кассы.** OLAP iiko умеет отвечать пустотой вместо ошибки. Без проверки
   такой ответ обнулял бы день и на дашборде, и в запасном ответе табло.

БД здесь не поднимается: подменяются `SessionLocal` и касса.
"""

import asyncio
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import scheduler  # noqa: E402
from config import settings  # noqa: E402
from pos.base import PosItem, PosOrder  # noqa: E402

DAY = date(2026, 9, 24)


def run(coro):
    return asyncio.run(coro)


class FakeQuery:
    """Мини-заглушка `db.query(...)`: считает строки и помечает факт удаления."""

    def __init__(self, journal: dict, have: int):
        self._journal = journal
        self._have = have

    def filter(self, *a, **kw):
        return self

    def count(self):
        return self._have

    def delete(self):
        self._journal["deleted"] = self._journal.get("deleted", 0) + 1


def fake_session(journal: dict, have: int):
    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def query(self, model):
            return FakeQuery(journal, have)

        def bulk_save_objects(self, objs):
            journal.setdefault("saved", []).extend(objs)

        def add(self, obj):
            journal.setdefault("added", []).append(obj)

        def get(self, model, key):
            journal.setdefault("upserted", []).append(key)
            return None

        def commit(self):
            journal["committed"] = True

    return FakeSession


class FakePos:
    """Касса, отдающая заданные заказы, и запоминающая запрошенное окно."""

    name = "fake"

    def __init__(self, orders_by_call=(), journal=None):
        self._orders = list(orders_by_call)
        self.journal = journal if journal is not None else {}

    async def orders(self, date_from, date_to):
        self.journal["window"] = (date_from, date_to)
        return self._orders

    async def products(self, day):
        self.journal["products_day"] = day
        return []


def _order(day=DAY):
    return PosOrder(
        number="1",
        date=day,
        hour=13,
        items=[PosItem(name="Дюрюм Балык", category="Дюрюмы", qty=1, sum=490, net=490)],
    )


# --- 1. Окно синка обрезается датой переключения кассы ------------------------


def test_окно_обрезается_датой_переключения(monkeypatch):
    monkeypatch.setattr(settings, "pos_switch_date", date(2026, 10, 1))
    assert scheduler.sync_window(date(2026, 9, 20), date(2026, 10, 5)) == (
        date(2026, 10, 1),
        date(2026, 10, 5),
    )


def test_окно_целиком_до_переключения_отменяется(monkeypatch):
    monkeypatch.setattr(settings, "pos_switch_date", date(2026, 10, 1))
    assert scheduler.sync_window(date(2026, 9, 20), date(2026, 9, 30)) is None


def test_без_настройки_окно_не_меняется(monkeypatch):
    monkeypatch.setattr(settings, "pos_switch_date", None)
    window = (date(2025, 12, 5), date(2026, 9, 25))
    assert scheduler.sync_window(*window) == window


def test_синк_заказов_за_старые_дни_не_ходит_в_кассу(monkeypatch):
    """Ни запроса, ни удаления: дни до переезда трогать нечем и незачем."""
    journal: dict = {}
    pos = FakePos(journal=journal)
    monkeypatch.setattr(settings, "pos_switch_date", date(2026, 10, 1))
    monkeypatch.setattr(scheduler, "get_pos", lambda: pos)
    monkeypatch.setattr(scheduler, "SessionLocal", fake_session(journal, have=39045))

    run(scheduler.sync_orders_range(date(2026, 9, 18), date(2026, 9, 24)))
    assert "window" not in journal  # кассу не спрашивали
    assert "deleted" not in journal  # историю не удаляли


def test_бэкафилл_не_опускается_ниже_переключения(monkeypatch):
    """`_history_start` для нового провайдера начинается не раньше дня переезда."""
    monkeypatch.setattr(settings, "history_start_date", date(2025, 12, 5))
    monkeypatch.setattr(settings, "pos_switch_date", date(2026, 10, 1))
    assert run(scheduler._history_start()) == date(2026, 10, 1)


def test_dish_detail_за_старый_день_не_синкается(monkeypatch):
    journal: dict = {}
    pos = FakePos(journal=journal)
    monkeypatch.setattr(settings, "pos_switch_date", date(2026, 10, 1))
    monkeypatch.setattr(scheduler, "get_pos", lambda: pos)
    monkeypatch.setattr(scheduler, "SessionLocal", fake_session(journal, have=10))

    run(scheduler.sync_dish_detail_day(date(2026, 9, 24)))
    assert "products_day" not in journal
    assert "deleted" not in journal


# --- 2. Пустой ответ кассы не затирает непустой день -------------------------


def test_пустой_ответ_поверх_непустого_дня_ничего_не_трогает(monkeypatch, caplog):
    journal: dict = {}
    monkeypatch.setattr(settings, "pos_switch_date", None)
    monkeypatch.setattr(scheduler, "get_pos", lambda: FakePos(journal=journal))
    monkeypatch.setattr(scheduler, "SessionLocal", fake_session(journal, have=120))

    with caplog.at_level("WARNING"):
        run(scheduler.sync_orders_range(DAY, DAY))
    assert "deleted" not in journal
    assert any("НЕ затираю данные" in m for m in caplog.messages)


def test_пустой_ответ_на_пустом_дне_это_норма(monkeypatch):
    """Точка была закрыта — день честно остаётся пустым, без воплей в лог."""
    journal: dict = {}
    monkeypatch.setattr(settings, "pos_switch_date", None)
    monkeypatch.setattr(scheduler, "get_pos", lambda: FakePos(journal=journal))
    monkeypatch.setattr(scheduler, "SessionLocal", fake_session(journal, have=0))

    run(scheduler.sync_orders_range(DAY, DAY))
    assert journal.get("deleted") == 3  # три таблицы очищены (и заполнены пустотой)
    assert journal.get("committed") is True


def test_непустой_ответ_обновляет_день(monkeypatch):
    journal: dict = {}
    monkeypatch.setattr(settings, "pos_switch_date", None)
    monkeypatch.setattr(scheduler, "get_pos", lambda: FakePos([_order()], journal))
    monkeypatch.setattr(scheduler, "SessionLocal", fake_session(journal, have=120))

    run(scheduler.sync_orders_range(DAY, DAY))
    assert journal.get("deleted") == 3
    assert journal.get("committed") is True
    assert len(journal.get("saved", [])) == 2  # одна позиция + один заказ, оплат нет
    assert journal["window"] == (DAY, DAY)


@pytest.mark.parametrize("days_back", [7, 31])
def test_синк_выручки_не_лезет_в_прошлое(monkeypatch, days_back):
    """Дни до переезда не апсёртятся, даже если касса их вернула."""
    seen: dict = {}

    class RevPos:
        name = "fake"

        async def revenue_days(self, date_from, date_to):
            seen["window"] = (date_from, date_to)
            return []

    switch = scheduler.today() - timedelta(days=2)
    monkeypatch.setattr(settings, "pos_switch_date", switch)
    monkeypatch.setattr(scheduler, "get_pos", lambda: RevPos())
    monkeypatch.setattr(scheduler, "SessionLocal", fake_session({}, have=0))

    run(scheduler.sync_revenue(days_back=days_back))
    assert seen["window"][0] == switch
