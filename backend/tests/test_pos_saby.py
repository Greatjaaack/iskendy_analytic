"""Разбор ответа Saby Presto: продажа → заказ, позиции, оплаты, агрегаты.

Фикстура собрана ПО ДОКУМЕНТАЦИИ (`SABY_API.md`), а не с живой кассы: на 25.09.2026
в Saby нет ни одной продажи — касса ещё на iiko. Поэтому тест фиксирует наше
понимание контракта; когда пробьётся первый живой чек, фикстуру нужно сверить с ним
(список белых пятен — в `SABY_API.md`, раздел «Что проверить на первом чеке»).

Сеть не дёргается: подменяются только `_fetch_sales` и `_ensure_menu`. Корутины
гоняем через `asyncio.run` — отдельный плагин для async-тестов проекту не нужен.
"""

import asyncio
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from constants import (  # noqa: E402
    PRODUCT_TYPE_DISH,
    PRODUCT_TYPE_GOODS,
    PRODUCT_TYPE_MODIFIER,
)
from pos.base import (  # noqa: E402
    aggregate_days,
    aggregate_hours,
    aggregate_products,
    to_order_rows,
)
from pos.saby import SabyPos  # noqa: E402

# id номенклатуры → (категория, тип позиции): так его отдаёт каталог Presto
MENU = {
    101: ("Дюрюмы", PRODUCT_TYPE_DISH),
    102: ("Напитки", PRODUCT_TYPE_GOODS),
    103: ("Допы и соусы", PRODUCT_TYPE_DISH),
    104: ("Статус", PRODUCT_TYPE_DISH),  # служебная папка-маркер канала (как в iiko)
}

SALE = {
    "Sale": 5001,
    "Number": "17",
    "DateWTZ": "2026-09-24 13:42:10",
    "OpenedWTZ": "2026-09-24 13:42:10",
    "ClosedWTZ": "2026-09-24 13:47:40",
    "Deleted": False,
    "Return": False,
    "ShiftNumber": "3",
    "Teller": 77,
    "TotalPrice": 690.0,
    "TotalDiscount": 10.0,
    "Payments": [
        {
            "CheckNumber": "120",
            "CashSum": 200.0,
            "BankSum": 490.0,
            "BankType": "Сбербанк",
            "CertificateSum": 0,
        }
    ],
    "SaleNomenclatures": [
        {
            "Nomenclature": 101,
            "Name": "Дюрюм Балык",
            "Quantity": 1,
            "TotalPrice": 480.0,
            "TotalDiscount": 10.0,
            "PlannedCost": 150.0,
            "TotalCost": 0,
            "IsModifier": False,
            # дочерняя позиция: платный модификатор внутри блюда
            "Positions": [
                {
                    "Nomenclature": 103,
                    "Name": "Дип соус",
                    "Quantity": 1,
                    "TotalPrice": 60.0,
                    "TotalDiscount": 0,
                    "PlannedCost": 12.0,
                    "IsModifier": True,
                }
            ],
        },
        {
            "Nomenclature": 102,
            "Name": "Айран",
            "Quantity": 2,
            "TotalPrice": 150.0,
            "TotalDiscount": 0,
            "PlannedCost": 40.0,
            "IsModifier": False,
        },
    ],
}

RETURN_SALE = {
    "Sale": 5002,
    "Number": "18",
    "OpenedWTZ": "2026-09-24 14:10:00",
    "Return": True,
    "Deleted": False,
    "SaleNomenclatures": [],
    "Payments": [],
}

DELETED_SALE = {"Sale": 5003, "Number": "19", "OpenedWTZ": "2026-09-24 14:20:00", "Deleted": True}


def run(coro):
    """Выполнить корутину в тесте (вместо плагина pytest-asyncio)."""
    return asyncio.run(coro)


@pytest.fixture
def saby(monkeypatch):
    pos = SabyPos()

    async def fake_menu():
        return MENU

    async def fake_sales(date_from, date_to):
        # Удалённые продажи отбрасывает сам `_fetch_sales`, здесь их уже нет.
        return [SALE, RETURN_SALE]

    monkeypatch.setattr(pos, "_ensure_menu", fake_menu)
    monkeypatch.setattr(pos, "_fetch_sales", fake_sales)
    return pos


def test_продажа_становится_заказом(saby):
    orders = run(saby.orders(date(2026, 9, 24), date(2026, 9, 24)))
    assert len(orders) == 1  # возврат — не заказ
    o = orders[0]
    assert o.number == "17"
    assert o.date == date(2026, 9, 24)
    assert o.hour == 13
    assert o.open_time == "2026-09-24T13:42:10"
    assert o.close_time == "2026-09-24T13:47:40"
    assert o.session_num == "3"
    assert o.cashier == "#77"  # имя кассира Saby в продаже не отдаёт, только id
    # гостей в API продаж нет: ставим 1 на чек — у точки кассир гостей не вводит и
    # iiko отдаёт ровно 1:1 к чекам, так что цифры «Гостей» не меняются
    assert o.guests == 1
    assert o.channel is None  # служебной позиции «Статус» в этом чеке нет


def test_позиции_с_категорией_и_модификатором(saby):
    (o,) = run(saby.orders(date(2026, 9, 24), date(2026, 9, 24)))
    by_name = {i.name: i for i in o.items}
    assert set(by_name) == {"Дюрюм Балык", "Айран", "Дип соус"}

    dish = by_name["Дюрюм Балык"]
    assert dish.category == "Дюрюмы"  # категория пришла из каталога, не из продажи
    assert dish.dish_type == PRODUCT_TYPE_DISH
    assert dish.net == 480.0
    assert dish.sum == 490.0  # брутто = сумма в чеке + скидка (база разрезов дашборда)
    assert dish.cost == 150.0  # плановая с/с по ТТК кассы

    assert by_name["Дип соус"].dish_type == PRODUCT_TYPE_MODIFIER  # вложенная позиция
    assert by_name["Айран"].dish_type == PRODUCT_TYPE_GOODS
    assert by_name["Айран"].qty == 2


def test_оплаты_разложены_по_способам(saby):
    (o,) = run(saby.orders(date(2026, 9, 24), date(2026, 9, 24)))
    pays = {p.pay_type: p.amount for p in o.payments}
    assert pays == {"Наличные": 200.0, "Карта (Сбербанк)": 490.0}
    assert round(sum(pays.values()), 2) == 690.0  # Σ оплат = сумма продажи


def test_сводка_дня_считается_из_заказов(saby):
    (day,) = run(saby.revenue_days(date(2026, 9, 24), date(2026, 9, 24)))
    assert day.date == date(2026, 9, 24)
    assert day.revenue == 700.0  # 490 + 60 + 150 (брутто)
    assert day.checks == 1
    assert day.avg_check == 700.0
    assert day.discount_sum == 10.0
    assert day.cost_sum == 202.0  # 150 + 12 + 40
    assert day.refund_count == 1  # продажа с Return = true


def test_часы_и_номенклатура(saby):
    hours = run(saby.hourly(date(2026, 9, 24), date(2026, 9, 24)))
    assert set(hours) == {13}
    assert hours[13].revenue == 700.0
    assert hours[13].checks == 1

    products = run(saby.products(date(2026, 9, 24)))
    by_name = {p.name: p for p in products}
    assert by_name["Дюрюм Балык"].revenue == 490.0
    assert by_name["Дип соус"].product_type == PRODUCT_TYPE_MODIFIER
    assert by_name["Айран"].quantity == 2


def test_табло_получает_номер_и_время(saby):
    found = run(saby.open_orders(date(2026, 9, 24)))
    assert [(o.number, o.open_time) for o in found] == [("17", "2026-09-24T13:42:10")]


def test_пустая_выборка_не_ломает_агрегаты():
    """Saby на пустом периоде отдаёт `{}` вместо `[]` — проверено живьём 25.09.2026."""
    assert aggregate_days([]) == []
    assert aggregate_hours([]) == {}
    assert aggregate_products([]) == []


def test_канал_из_служебной_позиции_статус(saby, monkeypatch):
    """Канал переезжает, если в меню Presto завести папку «Статус» с позициями по 0 ₽.

    Системного признака «в зале / с собой» в API продаж нет, но точка и в iiko
    помечает канал служебным модификатором — ту же схему повторяем в Presto.
    """
    s_собой = {
        **SALE,
        "Number": "20",
        "SaleNomenclatures": SALE["SaleNomenclatures"]
        + [
            {
                "Nomenclature": 104,
                "Name": "С собой",
                "Quantity": 1,
                "TotalPrice": 0,
                "IsModifier": True,
            }
        ],
    }

    async def sales(date_from, date_to):
        return [s_собой]

    monkeypatch.setattr(saby, "_fetch_sales", sales)
    (o,) = run(saby.orders(date(2026, 9, 24), date(2026, 9, 24)))
    assert o.channel == "с собой"
    # служебная строка не попадает в суммы заказа
    rows = to_order_rows([o])
    assert rows[0]["total_sum"] == 700.0
    assert rows[0]["channel"] == "с собой"
