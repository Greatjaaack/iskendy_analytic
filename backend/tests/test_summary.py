"""Контракт внутренней ручки `/api/summary` — деньги для вечерней сводки табло.

Вторая связь с `iskendy_site`: его сводка в полночь читает отсюда выручку, чеки и
средний чек за прошедший день. Как и с `/api/orders/today`, имена полей — внешний
контракт: переименовали — в сводке молча пропали деньги.

БД подменяется временной SQLite: живой прод не трогаем, iiko не дёргаем.
"""

import sys
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main  # noqa: E402
from config import settings  # noqa: E402

TOKEN = "test-internal-token"
DAY = date(2026, 8, 24)


class FakeRow:
    """Строка `revenue_daily` за день: 100 000 ₽ выручки при 200 чеках."""

    total_sum = 100000.0
    check_count = 200


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "internal_token", TOKEN)
    # комиссии агрегатора у точки нет (доставка не через агрегатора) — net = gross
    monkeypatch.setattr(main, "net_revenue", lambda gross, df, dt: (gross, 0.0, 0.0))
    return TestClient(main.app)


def _with_row(monkeypatch, row):
    """Подменяет чтение из БД: ручка получает `row` вместо похода в SQLite."""

    class FakeResult:
        def scalar_one_or_none(self):
            return row

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, *a, **kw):
            return FakeResult()

    monkeypatch.setattr(main, "SessionLocal", FakeSession)


def test_без_токена_401(client):
    assert client.get("/api/summary").status_code == 401


def test_чужой_токен_401(client):
    r = client.get("/api/summary", headers={"X-Internal-Token": "wrong"})
    assert r.status_code == 401


def test_поля_и_расчёт(client, monkeypatch):
    _with_row(monkeypatch, FakeRow())
    r = client.get(f"/api/summary?date={DAY.isoformat()}", headers={"X-Internal-Token": TOKEN})
    assert r.status_code == 200
    body = r.json()

    assert set(body) == {"date", "revenue", "checks", "avg_check", "has_data"}
    assert body["date"] == "2026-08-24"
    assert body["revenue"] == 100000.0
    assert body["checks"] == 200
    assert body["avg_check"] == 500.0  # выручка ÷ чеки, а не avg_check из iiko
    assert body["has_data"] is True


def test_день_без_данных_отдаёт_нули_и_has_data_false(client, monkeypatch):
    """Синк отстал — сводка должна увидеть это, а не напечатать 0 ₽ как факт."""
    _with_row(monkeypatch, None)
    r = client.get("/api/summary?date=2020-01-01", headers={"X-Internal-Token": TOKEN})
    assert r.status_code == 200
    body = r.json()
    assert body["has_data"] is False
    assert (body["revenue"], body["checks"], body["avg_check"]) == (0.0, 0, 0.0)


def test_ноль_чеков_не_делит_на_ноль(client, monkeypatch):
    class Empty:
        total_sum = 0.0
        check_count = 0

    _with_row(monkeypatch, Empty())
    r = client.get("/api/summary?date=2026-08-24", headers={"X-Internal-Token": TOKEN})
    assert r.status_code == 200
    assert r.json()["avg_check"] == 0.0


def test_кривая_дата_400(client):
    r = client.get("/api/summary?date=24.08.2026", headers={"X-Internal-Token": TOKEN})
    assert r.status_code == 400


def test_без_даты_берётся_сегодня_в_поясе_ресторана(client, monkeypatch):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    _with_row(monkeypatch, FakeRow())
    r = client.get("/api/summary", headers={"X-Internal-Token": TOKEN})
    today = datetime.now(ZoneInfo(settings.timezone)).date().isoformat()
    assert r.json()["date"] == today
