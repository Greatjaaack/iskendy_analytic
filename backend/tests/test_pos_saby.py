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

from config import settings  # noqa: E402
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
from pos.saby import SabyPos, build_menu  # noqa: E402

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

    async def fake_sales(date_from, date_to, cache_ttl=None):
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

    async def sales(date_from, date_to, cache_ttl=None):
        return [s_собой]

    monkeypatch.setattr(saby, "_fetch_sales", sales)
    (o,) = run(saby.orders(date(2026, 9, 24), date(2026, 9, 24)))
    assert o.channel == "с собой"
    # служебная строка не попадает в суммы заказа
    rows = to_order_rows([o])
    assert rows[0]["total_sum"] == 700.0
    assert rows[0]["channel"] == "с собой"


def test_неизвестная_точка_это_ошибка_а_не_пустые_продажи(monkeypatch):
    """Опечатка в SABY_POINT_ID не должна выглядеть как «продаж нет».

    Saby на неизвестный pointId отвечает HTTP 200 и пустым списком (проверено живьём
    25.09.2026), поэтому идентификатор сверяется отдельным запросом.
    """
    pos = SabyPos()

    async def fake_get(path, params, _retry=True):
        assert path == "/retail/point/list"
        return {"salesPoints": [{"id": 283}], "outcome": {"hasMore": False}}

    monkeypatch.setattr(pos, "_get", fake_get)
    monkeypatch.setattr(settings, "saby_point_id", 999999)
    with pytest.raises(RuntimeError, match="не найдена"):
        run(pos._ensure_point())

    monkeypatch.setattr(settings, "saby_point_id", 283)
    run(pos._ensure_point())  # верная точка — проходит молча
    assert pos._point_ok is True


# ─── Белые пятна документации: адаптер обязан пережить любой из вариантов ────────


def test_время_с_поясом_переводится_в_пояс_точки(saby, monkeypatch):
    """`*WTZ` — «with time zone». Пришло в UTC — час продажи всё равно московский."""
    monkeypatch.setattr(settings, "timezone", "Europe/Moscow")
    utc = {
        **SALE,
        "OpenedWTZ": "2026-09-24T10:42:10.500+00:00",
        "ClosedWTZ": "2026-09-24 10:47:40+00",
    }

    async def sales(date_from, date_to, cache_ttl=None):
        return [utc]

    monkeypatch.setattr(saby, "_fetch_sales", sales)
    (o,) = run(saby.orders(date(2026, 9, 24), date(2026, 9, 24)))
    assert o.hour == 13
    assert (o.open_time, o.close_time) == ("2026-09-24T13:42:10", "2026-09-24T13:47:40")
    assert o.date == date(2026, 9, 24)


def test_пагинация_не_удваивает_чеки_при_нумерации_с_единицы(monkeypatch):
    """Если страницы Saby считаются с 1, `page=0` и `page=1` вернут одно и то же.

    Без дедупа первая сотня чеков удвоилась бы в выручке.
    """
    pos = SabyPos()
    first = [{"Sale": i, "Number": str(i)} for i in range(1, 4)]
    second = [{"Sale": i, "Number": str(i)} for i in range(4, 6)]
    pages = {0: first, 1: first, 2: second}
    calls = []

    async def fake_get(path, params, _retry=True):
        calls.append(params["page"])
        return {"orders": pages[params["page"]], "outcome": {"hasMore": params["page"] < 2}}

    monkeypatch.setattr(pos, "_get", fake_get)
    got = run(pos._paged("/retail/order/list", {}, "orders", 10))
    assert [s["Sale"] for s in got] == [1, 2, 3, 4, 5]


def test_пагинация_останавливается_на_повторе_последней_страницы(monkeypatch):
    """API, который за краем снова отдаёт последнюю страницу с hasMore, не зацикливает."""
    pos = SabyPos()
    calls = []

    async def fake_get(path, params, _retry=True):
        calls.append(params["page"])
        return {"orders": [{"Sale": 1}], "outcome": {"hasMore": True}}

    monkeypatch.setattr(pos, "_get", fake_get)
    got = run(pos._paged("/retail/order/list", {}, "orders", 500))
    assert len(got) == 1 and calls == [0, 1, 2]


def test_оплата_без_разбивки_не_теряется(saby):
    """Платёж только с `Amount` (агрегатор и т. п.) попадает в «Прочее», Σ = выручке."""
    sale = {**SALE, "Payments": [{"Amount": 690.0}]}
    (o,) = [saby._to_order(sale, MENU)]
    assert [(p.pay_type, p.amount) for p in o.payments] == [("Прочее", 690.0)]


def test_статус_модификатором_вне_каталога(saby, monkeypatch):
    """«С собой» модификатором блюда без позиции в каталоге — канал всё равно найден."""
    sale = {
        **SALE,
        "SaleNomenclatures": SALE["SaleNomenclatures"]
        + [{"Nomenclature": 999, "Name": "С собой", "Quantity": 1, "IsModifier": True}],
    }
    o = saby._to_order(sale, MENU)
    assert o.channel == "с собой"
    row = to_order_rows([o])[0]
    assert row["item_count"] == 4  # служебная строка не считается позицией чека
    assert row["total_sum"] == 700.0


def test_платное_блюдо_с_именем_статуса_остаётся_товаром(saby):
    """Отсев по имени — только для строк по 0 ₽: платная «Доставка» — это товар."""
    sale = {
        **SALE,
        "SaleNomenclatures": [
            {"Nomenclature": 999, "Name": "Доставка", "Quantity": 1, "TotalPrice": 150.0}
        ],
    }
    o = saby._to_order(sale, MENU)
    assert o.channel is None
    assert o.items[0].category == ""


def test_каталог_по_uuid_если_id_не_совпал():
    """Категория находится по `NomenclatureUUID`, если числовые id продажи и каталога разные."""
    menu = build_menu(
        [
            {"id": 1, "name": "Блюда", "isParent": True},
            {"id": 2, "name": "Дюрюмы", "isParent": True, "hierarchicalParent": 1},
            {"id": 3, "name": "Дюрюм", "hierarchicalParent": 2, "externalId": "u-3"},
            {"id": 4, "name": "Товары", "isParent": True},
            {"id": 5, "name": "Вода", "hierarchicalParent": 4},
        ]
    )
    assert menu[3] == menu["u-3"] == ("Дюрюмы", PRODUCT_TYPE_DISH)
    assert menu[5] == ("Товары", PRODUCT_TYPE_GOODS)
    pos = SabyPos()
    sale = {
        **SALE,
        "SaleNomenclatures": [
            {"Nomenclature": 777, "NomenclatureUUID": "u-3", "Name": "Дюрюм", "Quantity": 1}
        ],
    }
    assert pos._to_order(sale, menu).items[0].category == "Дюрюмы"


def test_часы_по_закрытию_как_в_бд(saby):
    """Живой почасовой разрез совпадает с `hours_from_db`: час — по закрытию чека."""
    sale = {**SALE, "OpenedWTZ": "2026-09-24 13:59:30", "ClosedWTZ": "2026-09-24 14:00:40"}
    o = saby._to_order(sale, MENU)
    assert o.hour == 13  # в `orders.hour` остаётся час открытия
    assert list(aggregate_hours([o])) == [14]


def test_табло_передаёт_ttl_в_кэш(monkeypatch):
    """Ночная экономия запросов табло работает и на Saby: TTL доходит до кэша."""
    pos = SabyPos()
    seen = {}

    async def fake_cached(key, factory, ttl=None):
        seen["ttl"] = ttl
        return []

    monkeypatch.setattr("pos.saby.cached_or_call", fake_cached)
    run(pos.open_orders(date(2026, 9, 24), cache_ttl=60))
    assert seen["ttl"] == 60
