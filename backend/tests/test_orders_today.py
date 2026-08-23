"""Контракт внутренней ручки `/api/orders/today` — единственной связи с табло.

Табло `iskendy_site` поллит эту ручку и заводит по ней заказы. Формат ответа —
внешний контракт: переименовали поле — табло молча перестало получать заказы, и
узнали об этом от кассира. Тест фиксирует ровно то, на что табло рассчитывает.

Живой iiko не дёргаем: `olap_sales` подменяется заглушкой с сырыми OLAP-строками.
"""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main  # noqa: E402
from config import settings  # noqa: E402

TOKEN = "test-internal-token"

# Как OLAP отдаёт строки на самом деле: group-поля склеены в field0 через ", ".
OLAP_ROWS = [
    {"field0": {"value": "42, 2026-08-24T12:30:15"}, "field1": {"value": 1200}},
    {"field0": {"value": "7, 2026-08-24T11:05:00"}, "field1": {"value": 800}},
    {"field0": {"value": "мусор без разделителя"}, "field1": {"value": 0}},
    {"field0": {"value": "не-число, 2026-08-24T13:00:00"}, "field1": {"value": 0}},
]


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "internal_token", TOKEN)

    async def fake_olap(*args, **kwargs):
        return OLAP_ROWS

    monkeypatch.setattr(main.iiko_web, "olap_sales", fake_olap)
    # без `with` lifespan не запускается: ни планировщика, ни синка из iiko
    return TestClient(main.app)


def test_без_токена_401(client):
    assert client.get("/api/orders/today").status_code == 401


def test_чужой_токен_401(client):
    r = client.get("/api/orders/today", headers={"X-Internal-Token": "wrong"})
    assert r.status_code == 401


def test_пустой_internal_token_выключает_ручку(client, monkeypatch):
    """Не задан токен в .env — ручка закрыта, а не открыта всем."""
    monkeypatch.setattr(settings, "internal_token", "")
    r = client.get("/api/orders/today", headers={"X-Internal-Token": ""})
    assert r.status_code == 401


def test_поля_ответа(client):
    r = client.get("/api/orders/today", headers={"X-Internal-Token": TOKEN})
    assert r.status_code == 200
    body = r.json()

    assert set(body) == {"date", "orders", "now"}
    assert body["date"].count("-") == 2 and len(body["date"]) == 10  # YYYY-MM-DD
    assert len(body["now"].split(":")) == 3  # HH:MM:SS

    orders = body["orders"]
    # мусорные строки OLAP отбрасываются, а не ломают ответ
    assert len(orders) == 2
    for o in orders:
        assert set(o) == {"number", "openTime"}
        assert isinstance(o["number"], int)
        assert isinstance(o["openTime"], str)


def test_заказы_отсортированы_по_номеру(client):
    r = client.get("/api/orders/today", headers={"X-Internal-Token": TOKEN})
    numbers = [o["number"] for o in r.json()["orders"]]
    assert numbers == sorted(numbers) == [7, 42]


def test_openTime_как_пришло_из_olap(client):
    r = client.get("/api/orders/today", headers={"X-Internal-Token": TOKEN})
    by_num = {o["number"]: o["openTime"] for o in r.json()["orders"]}
    assert by_num[42] == "2026-08-24T12:30:15"
    assert by_num[7] == "2026-08-24T11:05:00"
