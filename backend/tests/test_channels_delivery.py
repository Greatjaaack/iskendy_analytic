"""Доставка — свойство ЗАКАЗА, а не позиции: одно правило для KPI, каналов и разрезов.

Найдено аудитом 09.10.2026: 418 из 551 заказа доставки смешанные — «Большое комбо обед
доставка» без маркера `_д`, напитки комбо без пометки. Галка «без доставки» вычитала только
помеченные позиции, а чек убирала целиком: май 2026 показывал 446 111 ₽ и средний чек
918 ₽ вместо 341 921 ₽ и ~684 ₽.

Правило (`utils.order_channel`): доставка — заказ с позицией доставки или с единственным
«Статусом» «Доставка». «Доставка» вместе с другим «Статусом» — ошибка кассира (заказ 151
от 20.09.2026 «Балык + Кола», оплачен терминалом): берём другой статус.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from constants import OLAP_FIELD_OPEN_DATE  # noqa: E402
from services.channels import channel_revenue, delivery_orders  # noqa: E402
from services.delivery import delivery_per_bucket, exclude_delivery  # noqa: E402
from services.dish_cuts import (  # noqa: E402
    build_basket,
    build_check_distribution,
    build_check_fullness,
)
from utils import order_channel  # noqa: E402

DAY = "2026-09-20"

# (номер, категория, имя, сумма) — строки разреза по заказам за один день
ROWS = [
    # кассир отметил и «Доставку», и «С собой», товаров доставки нет — это «с собой»
    ("151", "Дюрюмы", "Балык", 1180),
    ("151", "Напитки", "Кола", 380),
    ("151", "Статус", "Доставка", 0),
    ("151", "Статус", "С собой", 0),
    # обычный заказ в зале
    ("152", "Дюрюмы", "Балык", 1180),
    ("152", "Статус", "В зале", 0),
    # смешанный заказ доставки: дюрюм помечен `_д`, напиток — нет; статус ошибочный
    ("153", "Доставка", "Дюрюм_д", 900),
    ("153", "Напитки", "Кола б/с", 270),
    ("153", "Статус", "С собой", 0),
    # комбо доставки без маркера `_д` — доставка только по единственному «Статусу»
    ("154", "Комбо", "Большое комбо обед доставка", 1360),
    ("154", "Напитки", "Айран", 0),
    ("154", "Статус", "Доставка", 0),
]
ВЫРУЧКА_ДОСТАВКИ = 900 + 270 + 1360


def rows() -> list[dict]:
    return [
        {"field0": {"value": f"{DAY}, {n}, {cat}, {name}"}, "field1": {"value": s}}
        for n, cat, name, s in ROWS
    ]


def counts(include_delivery: bool) -> dict[str, int]:
    res = build_check_distribution(rows(), include_delivery)
    return {r["type"]: r["count"] for r in res["data"]} | {"total": res["total"]}


def test_правило_канала_заказа():
    assert order_channel({"доставка"}) == "доставка"
    assert order_channel({"доставка", "с собой"}) == "с собой"  # ошибка кассира
    assert order_channel({"доставка", "в зале"}) == "в зале"
    assert order_channel({"с собой"}, has_delivery_item=True) == "доставка"
    assert order_channel({"в зале", "с собой"}) == "с собой"  # сильнейший
    assert order_channel(set()) is None
    assert order_channel({None}) is None  # неизвестный статус не считается


def test_заказы_доставки_целиком():
    assert delivery_orders(rows()) == {f"{DAY}|153", f"{DAY}|154"}


def test_без_доставки_вычитается_весь_заказ():
    """Вычитается и напиток из заказа доставки, и комбо без маркера `_д`."""
    day = delivery_per_bucket(rows(), OLAP_FIELD_OPEN_DATE)[DAY]
    assert day == {"revenue": ВЫРУЧКА_ДОСТАВКИ, "checks": 2}

    days = [{"date": DAY, "total_sum": 5270.0, "check_count": 4, "avg_check": 1317.5}]
    exclude_delivery(days, {DAY: day})
    assert days[0]["total_sum"] == 1180 + 380 + 1180  # остались 151 и 152
    assert days[0]["check_count"] == 2
    assert days[0]["avg_check"] == 1370


def test_чеки_по_каналам():
    assert counts(include_delivery=True) == {
        "Доставка": 2,
        "С собой": 1,
        "В зале": 1,
        "total": 4,
    }
    # без доставки — ровно те чеки, что остаются в KPI
    assert counts(include_delivery=False) == {
        "Доставка": 0,
        "С собой": 1,
        "В зале": 1,
        "total": 2,
    }


def test_выручка_по_каналам_идёт_в_канал_заказа():
    day = channel_revenue(rows(), OLAP_FIELD_OPEN_DATE)[DAY]
    assert day == {"в зале": 1180, "с собой": 1560, "доставка": ВЫРУЧКА_ДОСТАВКИ}
    # зал + с собой = выручка без доставки в KPI
    assert day["в зале"] + day["с собой"] == 1180 + 380 + 1180


def test_разрезы_по_чекам_без_доставки_отсекают_заказ_целиком():
    qty_rows = [
        {"field0": {"value": f"{DAY}, 13, {n}, {cat}, {name}"}, "field1": {"value": 1}}
        for n, cat, name, _s in ROWS
    ]
    full = build_check_fullness(qty_rows, set(), include_delivery=False)["total"]
    assert sum(full.values()) == 2  # 151 и 152; напиток из 153 «чеком» не остаётся

    basket = build_basket(rows(), "dish", 12, set(), include_delivery=False)
    assert basket["orders"] == 2
    assert "Кола б/с" not in basket["labels"]
