"""Контракт внутренней ручки `/api/orders/today` — единственной связи с табло.

Табло `iskendy_site` поллит эту ручку и заводит по ней заказы. Формат ответа —
внешний контракт: переименовали поле — табло молча перестало получать заказы, и
узнали об этом от кассира. Тест фиксирует ровно то, на что табло рассчитывает.

Живая касса не дёргается: подменяется `olap_sales` внутри адаптера iiko
(`pos/iiko.py`), поэтому тест проверяет и разбор ответа кассы, и саму ручку.
"""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main  # noqa: E402
from config import settings  # noqa: E402
from pos import iiko as pos_iiko  # noqa: E402

TOKEN = "test-internal-token"

# Как OLAP отдаёт строки на самом деле: group-поля склеены в field0 через ", ".
OLAP_ROWS = [
    {"field0": {"value": "42, 2026-08-24T12:30:15"}, "field1": {"value": 1200}},
    {"field0": {"value": "7, 2026-08-24T11:05:00"}, "field1": {"value": 800}},
    {"field0": {"value": "мусор без разделителя"}, "field1": {"value": 0}},
    # нечисловой номер: в iiko таких нет, а в Saby номер продажи — строка. Заказ
    # должен доехать до табло, а не потеряться по дороге.
    {"field0": {"value": "A-7, 2026-08-24T13:00:00"}, "field1": {"value": 0}},
]


def _fake_session(order_rows=(), day_started=False):
    """Подменяет БД: `day_started` — есть ли сегодня хоть один заказ."""

    class FakeResult:
        def scalar_one_or_none(self):
            return 1 if day_started else None

        def all(self):
            return list(order_rows)

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, *a, **kw):
            return FakeResult()

    return FakeSession


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "internal_token", TOKEN)
    monkeypatch.setattr(main, "SessionLocal", _fake_session())

    async def fake_olap(*args, **kwargs):
        return OLAP_ROWS

    monkeypatch.setattr(pos_iiko.iiko_web, "olap_sales", fake_olap)
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
    # строка без разделителя отбрасывается, а не ломает ответ; нечисловой номер — нет
    assert len(orders) == 3
    for o in orders:
        assert set(o) == {"number", "openTime"}
        assert isinstance(o["number"], (int, str))
        assert isinstance(o["openTime"], str)


def test_заказы_отсортированы_по_номеру(client):
    """Числовые номера по возрастанию, нечисловые — после них (а не падение ручки)."""
    r = client.get("/api/orders/today", headers={"X-Internal-Token": TOKEN})
    numbers = [o["number"] for o in r.json()["orders"]]
    assert numbers == [7, 42, "A-7"]


def test_нечисловой_номер_доезжает_строкой(client):
    """В Saby номер продажи — строка; терять такой заказ нельзя (см. SABY_API.md)."""
    r = client.get("/api/orders/today", headers={"X-Internal-Token": TOKEN})
    by_num = {o["number"]: o["openTime"] for o in r.json()["orders"]}
    assert by_num["A-7"] == "2026-08-24T13:00:00"


def test_openTime_как_пришло_из_olap(client):
    r = client.get("/api/orders/today", headers={"X-Internal-Token": TOKEN})
    by_num = {o["number"]: o["openTime"] for o in r.json()["orders"]}
    assert by_num[42] == "2026-08-24T12:30:15"
    assert by_num[7] == "2026-08-24T11:05:00"


# --- устойчивость к сбоям iikoweb -------------------------------------------
# OLAP периодически отвечает статусом ERROR, причём по истории 93% таких сбоев
# приходятся на рабочие часы точки — когда заказы идут и табло без них слепнет.


def test_ретрай_после_первой_ошибки(client, monkeypatch):
    """Моргнул OLAP — переспрашиваем, а не отдаём 500."""
    calls = {"n": 0}

    async def flaky(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("iikoweb olap: статус ERROR")
        return OLAP_ROWS

    monkeypatch.setattr(pos_iiko.iiko_web, "olap_sales", flaky)
    r = client.get("/api/orders/today", headers={"X-Internal-Token": TOKEN})
    assert r.status_code == 200
    assert calls["n"] == 2
    assert [o["number"] for o in r.json()["orders"]] == [7, 42, "A-7"]


def test_обе_попытки_упали_отдаём_из_БД(client, monkeypatch):
    """iiko недоступен — табло получает заказы из БД, а не 500."""

    async def always_fails(*a, **kw):
        raise RuntimeError("iikoweb olap: статус ERROR")

    monkeypatch.setattr(pos_iiko.iiko_web, "olap_sales", always_fails)
    monkeypatch.setattr(
        main,
        "SessionLocal",
        _fake_session(order_rows=[("42", "2026-08-26T12:30:15"), ("7", "2026-08-26T11:05:00")]),
    )
    r = client.get("/api/orders/today", headers={"X-Internal-Token": TOKEN})
    assert r.status_code == 200
    body = r.json()
    # контракт тот же, что у живого ответа — источник данных наружу не виден
    assert set(body) == {"date", "orders", "now"}
    assert [o["number"] for o in body["orders"]] == [7, 42]
    assert body["orders"][0]["openTime"] == "2026-08-26T11:05:00"


def test_запасной_ответ_пишется_в_лог(client, monkeypatch, caplog):
    """Иначе лежачий iiko спрячется за исправным на вид табло."""

    async def always_fails(*a, **kw):
        raise RuntimeError("iikoweb olap: статус ERROR")

    monkeypatch.setattr(pos_iiko.iiko_web, "olap_sales", always_fails)
    with caplog.at_level("WARNING"):
        client.get("/api/orders/today", headers={"X-Internal-Token": TOKEN})
    assert any("отдаю из БД" in m for m in caplog.messages)


# --- «тихий» режим, пока заказов за день нет ---------------------------------


def test_пока_заказов_нет_ходим_в_iiko_реже(client, monkeypatch):
    """Ночь, точка закрыта: запрос раз в минуту вместо 6 раз в минуту."""
    seen = {}

    async def spy(*a, **kw):
        seen["ttl"] = kw.get("cache_ttl")
        return []

    monkeypatch.setattr(pos_iiko.iiko_web, "olap_sales", spy)
    monkeypatch.setattr(settings, "idle_poll_seconds", 60)
    client.get("/api/orders/today", headers={"X-Internal-Token": TOKEN})
    assert seen["ttl"] == 60


def test_после_первого_заказа_режим_обычный(client, monkeypatch):
    """Смена открылась — свежесть важнее экономии, TTL общий."""
    seen = {}

    async def spy(*a, **kw):
        seen["ttl"] = kw.get("cache_ttl")
        return OLAP_ROWS

    monkeypatch.setattr(pos_iiko.iiko_web, "olap_sales", spy)
    monkeypatch.setattr(main, "SessionLocal", _fake_session(day_started=True))
    monkeypatch.setattr(settings, "idle_poll_seconds", 60)
    client.get("/api/orders/today", headers={"X-Internal-Token": TOKEN})
    assert seen["ttl"] is None


# --- потолок ожидания живой кассы --------------------------------------------


def test_медленная_kassa_ne_derzhit_tablo(client, monkeypatch):
    """Больная касса не должна утаскивать табло за собой.

    27.08.2026 касса собирала выборку дольше, чем ждал клиент, и ручка тратила
    60 секунд на попытку, секунду на паузу и ещё 60 на повтор. Табло обрывает
    связь на 30-й секунде, поэтому за два часа не получило ни одного ответа —
    включая удачные, приходившие на 77–106-й секунде. Ответ, опоздавший к сроку
    вызывающего, равен отсутствию ответа.
    """
    import asyncio

    async def medlennaya(*a, **kw):
        await asyncio.sleep(30)
        return OLAP_ROWS

    monkeypatch.setattr(settings, "orders_live_budget_sec", 0.05)
    monkeypatch.setattr(pos_iiko.iiko_web, "olap_sales", medlennaya)
    monkeypatch.setattr(
        main,
        "SessionLocal",
        _fake_session(order_rows=[("11", "2026-08-27T12:07:02")]),
    )
    r = client.get("/api/orders/today", headers={"X-Internal-Token": TOKEN})
    assert r.status_code == 200
    # дождались запасного пути, а не живого ответа
    assert [o["number"] for o in r.json()["orders"]] == [11]


def test_potolok_nakryvaet_i_povtor(client, monkeypatch, caplog):
    """Потолок считается на весь живой путь, а не на одну попытку.

    Иначе неудачная попытка, пауза и повтор складывались бы в двойное ожидание —
    ровно та арифметика, что дала 121 секунду при 30-секундном терпении табло.
    """
    import asyncio

    popytok = {"n": 0}

    async def upala_potom_visnet(*a, **kw):
        popytok["n"] += 1
        if popytok["n"] == 1:
            raise RuntimeError("iikoweb olap: статус ERROR")
        await asyncio.sleep(30)
        return OLAP_ROWS

    monkeypatch.setattr(settings, "orders_live_budget_sec", 0.05)
    monkeypatch.setattr(pos_iiko.iiko_web, "olap_sales", upala_potom_visnet)
    with caplog.at_level("WARNING"):
        r = client.get("/api/orders/today", headers={"X-Internal-Token": TOKEN})
    assert r.status_code == 200
    assert any("отдаю из БД" in m for m in caplog.messages)


def test_bystraya_kassa_otvechaet_zhivymi_dannymi(client):
    """Здоровая касса укладывается в потолок — табло получает живые заказы.

    Обратная сторона: потолок не должен превращать рабочую кассу в вечный
    запасной путь.
    """
    r = client.get("/api/orders/today", headers={"X-Internal-Token": TOKEN})
    assert r.status_code == 200
    assert [o["number"] for o in r.json()["orders"]] == [7, 42, "A-7"]
