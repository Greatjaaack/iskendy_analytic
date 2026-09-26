"""Заказ — это (дата, номер), а не номер: иначе разрезы по чекам врут.

Номер заказа у кассы уникален только внутри дня. Пока разрезы группировали по одному
`OrderNum`, заказы с одинаковым номером из разных дней склеивались в один: на реальных
данных за 01–20.09.2026 из 3 310 чеков получалось 237 «чеков» по 39,7 позиции вместо 2,5,
и от этого врали состав чека, наполненность, сочетаемость и разрез по каналам.

Фикстура: **два дня и повторяющиеся номера заказов** (7 и 8), причём заказ 8 оба дня
открыт в один и тот же час — так проверяются и разрезы, где ключом была пара (час,
номер). Если дата снова исчезнет из группировки, покраснеет каждый тест ниже (проверено:
со сломанным хелпером падают все 8).

Касса не дёргается: `order_rows` подменяется генератором строк, который отдаёт ровно те
group-поля, которые запросил роутер.
"""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main  # noqa: E402
from config import settings  # noqa: E402
from constants import (  # noqa: E402
    OLAP_FIELD_DISH_CATEGORY,
    OLAP_FIELD_DISH_NAME,
    OLAP_FIELD_HOUR,
    OLAP_FIELD_OPEN_DATE,
    OLAP_FIELD_ORDER_NUM,
    OLAP_FIELD_QTY,
    OLAP_FIELD_SUM,
)
from routers import dishes as dishes_router  # noqa: E402
from routers import revenue as revenue_router  # noqa: E402
from services import delivery as delivery_service  # noqa: E402

# Четыре РАЗНЫХ заказа: номера 7 и 8 повторяются в оба дня — так и бывает каждый день.
# Заказ 8 оба дня открыт в ОДИН час (13): без даты в группировке он склеивается даже
# там, где ключом служит пара (час, номер) — наполненность чеков и состав чека.
# (дата, час, номер, категория, имя, кол-во, сумма)
ITEMS = [
    ("2026-09-01", "13", "7", "Дюрюмы", "Балык", 1, 500),
    ("2026-09-01", "13", "7", "Статус", "В зале", 1, 0),
    ("2026-09-02", "19", "7", "Напитки", "Айран", 1, 100),
    ("2026-09-02", "19", "7", "Статус", "С собой", 1, 0),
    ("2026-09-01", "13", "8", "Дюрюмы", "Балык", 1, 500),
    ("2026-09-01", "13", "8", "Статус", "В зале", 1, 0),
    ("2026-09-02", "13", "8", "Напитки", "Айран", 1, 100),
    ("2026-09-02", "13", "8", "Статус", "С собой", 1, 0),
]

_FIELD_INDEX = {
    OLAP_FIELD_OPEN_DATE: 0,
    OLAP_FIELD_HOUR: 1,
    OLAP_FIELD_ORDER_NUM: 2,
    OLAP_FIELD_DISH_CATEGORY: 3,
    OLAP_FIELD_DISH_NAME: 4,
}
_DATA_INDEX = {OLAP_FIELD_QTY: 5, OLAP_FIELD_SUM: 6}


async def fake_order_rows(group_fields, data_fields, date_from, date_to):
    """Строки «как из кассы»: только запрошенные группы, с агрегацией по ним.

    Именно так ведёт себя и живой OLAP, и `services.order_store`: не попросил дату —
    не получил, и строки разных дней слились. Поэтому подмена честно воспроизводит
    исходную ошибку, а не прячет её.
    """
    agg: dict[tuple, list[float]] = {}
    for item in ITEMS:
        if not (date_from <= item[0] <= date_to):
            continue
        key = tuple(item[_FIELD_INDEX[f]] for f in group_fields)
        bucket = agg.setdefault(key, [0.0] * len(data_fields))
        for i, f in enumerate(data_fields):
            bucket[i] += item[_DATA_INDEX[f]]
    rows = []
    for key, values in agg.items():
        row = {"field0": {"value": ", ".join(key)}}
        for i, v in enumerate(values, start=1):
            row[f"field{i}"] = {"value": v}
        rows.append(row)
    return rows


async def fake_modifier_filters(date_from, date_to):
    """Ни одного модификатора: фикстура их не содержит."""
    return set(), set()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "auth_password", "t")
    monkeypatch.setattr(dishes_router, "order_rows", fake_order_rows)
    monkeypatch.setattr(dishes_router, "modifier_filters", fake_modifier_filters)
    monkeypatch.setattr(revenue_router, "order_rows", fake_order_rows)
    monkeypatch.setattr(delivery_service, "order_rows", fake_order_rows)
    c = TestClient(main.app)
    token = c.post("/api/auth/login", json={"username": "admin", "password": "t"}).json()["token"]
    c.headers.update({"Authorization": f"Bearer {token}"})
    return c


PERIOD = "date_from=2026-09-01&date_to=2026-09-02"


def test_чеки_по_типу_обслуживания_считают_все_заказы(client):
    """Четыре заказа (номера 7 и 8 в двух днях) — четыре чека, а не два."""
    body = client.get(f"/api/dishes/check-distribution?{PERIOD}").json()
    assert body["total"] == 4
    counts = {d["type"]: d["count"] for d in body["data"]}
    assert counts["В зале"] == 2  # «Статус» первого дня не красит заказы второго
    assert counts["С собой"] == 2


def test_наполненность_не_сливает_позиции_разных_дней(client):
    """Четыре чека по одной позиции, а не два чека, один из которых на две."""
    total = client.get(f"/api/dishes/check-fullness?{PERIOD}").json()["total"]
    assert total["1"] == 4  # четыре чека по одной позиции
    assert total["2"] == 0  # склейка дала бы чек на две позиции


def test_сочетаемость_не_придумывает_пары(client):
    """Балык (1 сентября) и Айран (2 сентября) вместе в чеке НЕ встречались."""
    body = client.get(f"/api/dishes/basket?{PERIOD}&group=dish").json()
    assert body["orders"] == 4
    i = body["labels"].index("Балык")
    j = body["labels"].index("Айран")
    assert body["matrix"][i][j] == 0
    assert body["matrix"][i][i] == 2  # Балык — в двух чеках первого дня


def test_состав_чека_считает_каждый_чек(client):
    """Чеков 4, в каждом одна категория — доли 50/50 между Дюрюмами и Напитками."""
    total = client.get(f"/api/dishes/check-composition?{PERIOD}").json()["total"]
    assert total["checks"] == 4
    assert total["by"]["Дюрюмы"]["qty"] == 50.0
    assert total["by"]["Напитки"]["qty"] == 50.0


def test_kpi_по_каналам_считает_все_чеки(client):
    body = client.get(f"/api/revenue/kpi-by-channel?{PERIOD}").json()
    assert body["other"]["checks"] == 4
    assert body["other"]["revenue"] == 1200
    assert body["other"]["avg_check"] == 300


def test_блюдо_канал_берёт_статус_своего_заказа(client):
    """Балык продан в зале, Айран — с собой; без даты оба ушли бы в один канал."""
    rows = {
        r["name"]: r for r in client.get(f"/api/dishes/service-breakdown?{PERIOD}").json()["data"]
    }
    assert rows["Балык"]["в зале"] == 2
    assert rows["Балык"]["с собой"] == 0
    assert rows["Айран"]["с собой"] == 2
    assert rows["Айран"]["в зале"] == 0


def test_выручка_по_каналам_по_дням(client):
    """Каждый день — свой канал, суммы не перетекают между днями."""
    data = {r["date"]: r for r in client.get(f"/api/revenue/by-channel?{PERIOD}").json()["data"]}
    assert data["2026-09-01"]["в зале"] == 1000
    assert data["2026-09-01"]["с собой"] == 0
    assert data["2026-09-02"]["с собой"] == 200
    assert data["2026-09-02"]["в зале"] == 0


def test_выручка_по_каналам_по_часам(client):
    """То же по часам: в 13 часов и зал, и «с собой» (разные дни), в 19 — «с собой»."""
    data = {
        r["hour"]: r for r in client.get(f"/api/revenue/hourly-by-channel?{PERIOD}").json()["data"]
    }
    assert data[13]["в зале"] == 1000  # два заказа первого дня
    assert data[13]["с собой"] == 100  # заказ 8 второго дня — тот же час, другой канал
    assert data[19]["с собой"] == 100
