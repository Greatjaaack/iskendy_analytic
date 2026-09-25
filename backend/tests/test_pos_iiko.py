"""Разбор OLAP-ответа iiko в доменные заказы (`pos/iiko.py`).

Этот разбор раньше жил в планировщике и был покрыт только «глазами»: сломайся он —
в БД молча легли бы неверные заказы, а дашборд показал бы правдоподобную чушь.
Тест фиксирует поведение на строках того вида, который отдаёт живой OLAP: group-поля
склеены в `field0` через «, », имя блюда может само содержать запятую.

Сеть не дёргается: разбор вызывается напрямую, без запроса к кассе.
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from constants import (  # noqa: E402
    CHANNEL_DELIVERY,
    CHANNEL_DINEIN,
    ORDER_STATUS_CATEGORY,
    PRODUCT_TYPE_DISH,
)
from pos.base import to_item_rows, to_order_rows, to_payment_rows  # noqa: E402
from pos.iiko import IikoPos  # noqa: E402

# [дата, час, заказ, категория, тип, имя] + [sum, qty, guests, cost, net]
ITEM_ROWS = [
    {
        "field0": {"value": "2026-09-24, 13, 17, Дюрюмы, DISH, Дюрюм Балык"},
        "field1": {"value": 490},
        "field2": {"value": 1},
        "field3": {"value": 2},
        "field4": {"value": 150},
        "field5": {"value": 480},
    },
    {
        # имя с запятой — хвост склеивается обратно, иначе позиция «теряется»
        "field0": {"value": "2026-09-24, 13, 17, Напитки, GOODS, Айран, 0.5 л"},
        "field1": {"value": 150},
        "field2": {"value": 2},
        "field3": {"value": 2},
        "field4": {"value": 40},
        "field5": {"value": 150},
    },
    {
        # модификатор категории «Статус» — так эта точка помечает тип обслуживания
        "field0": {"value": "2026-09-24, 13, 17, Статус, MODIFIER, Доставка"},
        "field1": {"value": 0},
        "field2": {"value": 1},
        "field3": {"value": 2},
        "field4": {"value": 0},
        "field5": {"value": 0},
    },
    {
        "field0": {"value": "2026-09-24, 19, 18, Дюрюмы, DISH, Дюрюм Классик"},
        "field1": {"value": 400},
        "field2": {"value": 1},
        "field3": {"value": 1},
        "field4": {"value": 120},
        "field5": {"value": 400},
    },
]

# [дата, заказ, открыт, закрыт, смена, стол, оплата, зал, кассир] + [sum]
ATTR_ROWS = [
    {
        "field0": {
            "value": (
                "2026-09-24, 17, 2026-09-24T13:42:10, 2026-09-24T13:47:40, 3, 5, "
                "Наличные, Основной зал, Иванов"
            )
        },
        "field1": {"value": 200},
    },
    {
        # сплит-оплата: тот же заказ второй строкой с другим способом
        "field0": {
            "value": (
                "2026-09-24, 17, 2026-09-24T13:42:10, 2026-09-24T13:47:40, 3, 5, "
                "Терминал, Основной зал, Иванов"
            )
        },
        "field1": {"value": 440},
    },
    {
        "field0": {
            "value": (
                "2026-09-24, 18, 2026-09-24T19:01:00, 2026-09-24T19:04:00, 3, , "
                "Терминал, , Иванов"
            )
        },
        "field1": {"value": 400},
    },
]


def _orders():
    return sorted(IikoPos()._build(ITEM_ROWS, ATTR_ROWS), key=lambda o: o.number)


def test_заказ_собран_из_двух_запросов():
    first, second = _orders()
    assert (first.number, first.date) == ("17", date(2026, 9, 24))
    assert first.hour == 13
    assert first.open_time == "2026-09-24T13:42:10"
    assert first.close_time == "2026-09-24T13:47:40"
    assert first.session_num == "3"
    assert first.table_num == "5"
    assert first.section == "Основной зал"
    assert first.cashier == "Иванов"
    assert first.guests == 2  # гости — атрибут заказа, повторяется в строках позиций
    assert second.number == "18" and second.hour == 19


def test_имя_с_запятой_не_рассыпается():
    first, _ = _orders()
    names = {i.name for i in first.items}
    assert "Айран, 0.5 л" in names


def test_канал_из_модификатора_статус():
    first, second = _orders()
    assert first.channel == CHANNEL_DELIVERY  # «Статус: Доставка» на уровне заказа
    assert second.channel == CHANNEL_DINEIN  # нет «Статуса» — считаем зал


def test_сплит_оплата_не_дублирует_позиции():
    first, _ = _orders()
    assert len(first.items) == 3  # две товарные + строка «Статус»
    pays = {p.pay_type: p.amount for p in first.payments}
    assert pays == {"Наличные": 200.0, "Терминал": 440.0}


def test_строки_бд_считают_суммы_без_служебных_позиций():
    orders = _orders()
    items = to_item_rows(orders)
    # «Статус» остаётся строкой в order_items (по нему считается разрез по каналам)
    assert sum(1 for i in items if i.category == ORDER_STATUS_CATEGORY) == 1
    assert any(i.dish_type == PRODUCT_TYPE_DISH for i in items)

    rows = {r["order_num"]: r for r in to_order_rows(orders)}
    assert rows["17"]["total_sum"] == 640  # 490 + 150, строка «Статус» не считается
    assert rows["17"]["cost_sum"] == 190
    assert rows["17"]["item_count"] == 3  # 1 дюрюм + 2 айрана
    assert rows["17"]["dish_count"] == 2
    assert rows["17"]["is_delivery"] is False  # позиции обычные, доставка — из «Статуса»
    assert rows["17"]["pay_type"] == "Наличные, Терминал"
    assert rows["17"]["duration_min"] == 5.5

    pays = {(p["order_num"], p["pay_type"]): p["amount"] for p in to_payment_rows(orders)}
    assert pays[("17", "Наличные")] == 200.0
    assert pays[("18", "Терминал")] == 400.0
