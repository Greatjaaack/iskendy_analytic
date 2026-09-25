"""Откуда берутся дни периода: БД, позиции заказов или живая касса.

Раньше признаком был `is_custom`: любой выбор дат календарём уходил живым запросом в
кассу, даже когда все дни лежали в БД. Это стоило 8,4 секунды на `/api/pnl` за месяц
(против 0,36 с из БД) и делало календарь заложником доступности кассы.

Правило теперь такое: сводка `revenue_daily` → позиции `order_items` → и только за
днями, которых в БД нет вовсе (раньше начала истории) или за сегодня, ещё не попавшим в
синк, идём в кассу. Пробел внутри истории — это закрытый день, касса вернёт те же нули.
"""

import sys
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import models  # noqa: E402
from constants import ORDER_STATUS_CATEGORY  # noqa: E402
from routers import revenue as rev  # noqa: E402


def _asyncio_run(coro):
    import asyncio

    return asyncio.run(coro)


# --- выбор источника: кто вызван, а кто нет ---------------------------------


@pytest.fixture
def spy(monkeypatch):
    """Подменяет три источника и запоминает, к какому обращались и за какими днями."""
    calls: dict[str, list] = {"db": [], "items": [], "live": []}
    data: dict[str, list[dict]] = {"db": [], "items": [], "live": []}

    def from_db(df, dt):
        calls["db"].append((df, dt))
        return [d for d in data["db"] if df.isoformat() <= d["date"] <= dt.isoformat()]

    def from_items(df, dt):
        calls["items"].append((df, dt))
        return [d for d in data["items"] if df.isoformat() <= d["date"] <= dt.isoformat()]

    async def live(df, dt):
        calls["live"].append((df, dt))
        return [d for d in data["live"] if df.isoformat() <= d["date"] <= dt.isoformat()]

    monkeypatch.setattr(rev, "_days_from_db", from_db)
    monkeypatch.setattr(rev, "_days_from_items", from_items)
    monkeypatch.setattr(rev, "_days_live", live)
    monkeypatch.setattr(rev, "today", lambda: date(2026, 9, 20))
    monkeypatch.setattr(rev, "_history_start", lambda: date(2026, 9, 1))
    return calls, data


def _day(iso: str, total: float = 100.0) -> dict:
    return rev._day_dict(date.fromisoformat(iso), total, 1, total, 0, 0, 30.0)


def test_период_целиком_в_сводке_кассу_не_дёргает(spy):
    calls, data = spy
    data["db"] = [_day("2026-09-10"), _day("2026-09-11")]
    days = _asyncio_run(rev._load_days(date(2026, 9, 10), date(2026, 9, 11), is_custom=True))
    assert [d["date"] for d in days] == ["2026-09-10", "2026-09-11"]
    assert calls["live"] == []  # главное: календарный диапазон больше не идёт в кассу
    assert calls["items"] == []  # и позиции не нужны, сводка всё покрыла


def test_пробел_в_сводке_закрывается_позициями(spy):
    """Сводка синкается за месяц, позиции есть за всю историю."""
    calls, data = spy
    data["db"] = [_day("2026-09-11")]
    data["items"] = [_day("2026-09-10", 500.0)]
    days = _asyncio_run(rev._load_days(date(2026, 9, 10), date(2026, 9, 11), is_custom=True))
    assert [d["date"] for d in days] == ["2026-09-10", "2026-09-11"]
    assert [d["total_sum"] for d in days] == [500.0, 100.0]
    assert calls["items"] == [(date(2026, 9, 10), date(2026, 9, 10))]
    assert calls["live"] == []


def test_дни_раньше_истории_берём_у_кассы(spy):
    """До начала сохранённой истории данных нет ни в одной таблице — только касса."""
    calls, data = spy
    data["db"] = [_day("2026-09-01")]
    data["live"] = [_day("2026-08-30", 700.0), _day("2026-08-31", 800.0)]
    days = _asyncio_run(rev._load_days(date(2026, 8, 30), date(2026, 9, 1), is_custom=True))
    assert [d["date"] for d in days] == ["2026-08-30", "2026-08-31", "2026-09-01"]
    assert calls["live"] == [(date(2026, 8, 30), date(2026, 8, 31))]  # только пробел


def test_закрытый_день_внутри_истории_кассу_не_дёргает(spy):
    """День без заказов — это выходной. Касса вернёт по нему те же нули, незачем спрашивать."""
    calls, data = spy
    data["db"] = [_day("2026-09-10"), _day("2026-09-12")]
    days = _asyncio_run(rev._load_days(date(2026, 9, 10), date(2026, 9, 12), is_custom=True))
    assert [d["date"] for d in days] == ["2026-09-10", "2026-09-12"]
    assert calls["live"] == []


def test_сегодня_доберём_живым_если_синк_не_успел(spy):
    """Первые минуты после полуночи: синк нового дня ещё не прошёл."""
    calls, data = spy
    data["db"] = [_day("2026-09-19")]
    data["live"] = [_day("2026-09-20", 1234.0)]
    days = _asyncio_run(rev._load_days(date(2026, 9, 19), date(2026, 9, 20), is_custom=False))
    assert [d["date"] for d in days] == ["2026-09-19", "2026-09-20"]
    assert (date(2026, 9, 20), date(2026, 9, 20)) in calls["live"]


def test_сегодня_из_бд_живым_не_дёргаем(spy):
    calls, data = spy
    data["db"] = [_day("2026-09-19"), _day("2026-09-20")]
    _asyncio_run(rev._load_days(date(2026, 9, 19), date(2026, 9, 20), is_custom=False))
    assert calls["live"] == []


# --- сами числа из позиций ---------------------------------------------------


@pytest.fixture
def db_with_items(tmp_path, monkeypatch):
    """Временная БД с позициями двух заказов одного дня + служебной строкой «Статус»."""
    engine = create_engine(
        f"sqlite:///{tmp_path / 'items.db'}", connect_args={"check_same_thread": False}
    )
    event.listen(engine, "connect", models._sqlite_pragmas)
    models.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        db.add_all(
            [
                models.OrderItem(
                    date=date(2026, 3, 1),
                    hour=13,
                    order_num="1",
                    category="Дюрюмы",
                    name="Балык",
                    qty=1,
                    sum=600,
                    net=550,
                    cost=180,
                ),
                models.OrderItem(
                    date=date(2026, 3, 1),
                    hour=13,
                    order_num="1",
                    category=ORDER_STATUS_CATEGORY,
                    name="С собой",
                    qty=1,
                    sum=0,
                    net=0,
                    cost=0,
                ),
                models.OrderItem(
                    date=date(2026, 3, 1),
                    hour=19,
                    order_num="2",
                    category="Напитки",
                    name="Айран",
                    qty=2,
                    sum=200,
                    net=200,
                    cost=60,
                ),
            ]
        )
        db.commit()
    monkeypatch.setattr(rev, "SessionLocal", Session)
    return Session


def test_день_из_позиций_считает_как_сводка(db_with_items):
    """Выручка без служебных строк, чек = заказ, скидка = брутто − нетто, с/с — по позициям."""
    (day,) = rev._days_from_items(date(2026, 3, 1), date(2026, 3, 1))
    assert day["date"] == "2026-03-01"
    assert day["total_sum"] == 800.0  # 600 + 200, строка «Статус» не считается
    assert day["check_count"] == 2  # два заказа
    assert day["avg_check"] == 400.0
    assert day["discount_sum"] == 50.0  # 600 → 550
    assert day["cost_sum"] == 240.0
    assert day["food_cost_pct"] == 30.0


def test_день_без_позиций_не_появляется(db_with_items):
    assert rev._days_from_items(date(2026, 3, 2), date(2026, 3, 3)) == []


def test_прошлый_период_тоже_из_бд(spy, monkeypatch):
    """KPI-дельты: прошлый месяц за окном сводки, но внутри истории позиций.

    Раньше `_days_from_db` возвращал пусто и дельта тянулась живым запросом в кассу —
    на каждое открытие дашборда.
    """
    calls, data = spy
    data["items"] = [_day("2026-08-01", 300.0), _day("2026-08-02", 400.0)]
    days = _asyncio_run(rev.days_stored_or_live(date(2026, 8, 1), date(2026, 8, 2)))
    assert [d["total_sum"] for d in days] == [300.0, 400.0]
    assert calls["live"] == []


# --- почасовой разрез: час ЗАКРЫТИЯ заказа ----------------------------------


@pytest.fixture
def db_with_orders(tmp_path, monkeypatch):
    """Заказы: один закрыт в другом часе, чем открыт; у второго времени закрытия нет."""
    engine = create_engine(
        f"sqlite:///{tmp_path / 'orders.db'}", connect_args={"check_same_thread": False}
    )
    event.listen(engine, "connect", models._sqlite_pragmas)
    models.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        db.add_all(
            [
                models.Order(
                    date=date(2026, 3, 1),
                    order_num="1",
                    hour=10,
                    total_sum=500,
                    open_time="2026-03-01T10:59:10",
                    close_time="2026-03-01T11:01:40",
                ),
                models.Order(
                    date=date(2026, 3, 1),
                    order_num="2",
                    hour=19,
                    total_sum=300,
                    open_time="2026-03-01T19:05:00",
                    close_time=None,
                ),
            ]
        )
        db.commit()
    monkeypatch.setattr(rev, "SessionLocal", Session)
    return Session


def test_час_берётся_по_закрытию_заказа(db_with_orders):
    """Так считает iiko: на боевых данных все 12 часов сошлись до рубля и до чека.

    Заказ 10:59 → 11:01 у кассы попадает в 11-й час, а не в 10-й.
    """
    rev_by_hour, checks_by_hour = rev._hours_from_db(date(2026, 3, 1), date(2026, 3, 1))
    assert rev_by_hour == {11: 500.0, 19: 300.0}
    assert checks_by_hour == {11: 1, 19: 1}


def test_без_времени_закрытия_берём_час_открытия(db_with_orders):
    """Второй заказ закрытия не имеет — он остаётся в своём 19-м часе."""
    rev_by_hour, _ = rev._hours_from_db(date(2026, 3, 1), date(2026, 3, 1))
    assert rev_by_hour[19] == 300.0
