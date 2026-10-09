"""Канал заказа (в зале / с собой / доставка) и выручка по каналам.

Канал — свойство ЗАКАЗА, а не позиции. Правило одно на все разрезы (`utils.order_channel`):
доставка — заказ с позицией доставки (`utils.is_delivery`) или с единственным «Статусом»
«Доставка»; иначе — сильнейший из «Статусов», без них — зал.

Почему не по позициям (так было до 09.10.2026): 418 из 551 заказа доставки смешанные —
«Большое комбо обед доставка» без маркера `_д`, напитки комбо без категории. Галка «без
доставки» вычитала только помеченные позиции, а чек убирала целиком: май 2026 показывал
446 111 ₽ и средний чек 918 ₽ вместо 341 921 ₽ и ~684 ₽.

Заказ опознаётся парой (дата, номер): номер уникален только внутри дня.
"""

from collections import defaultdict
from collections.abc import Iterable

from constants import (
    CHANNEL_DELIVERY,
    CHANNEL_DINEIN,
    CHANNEL_TAKEAWAY,
    ORDER_STATUS_CATEGORY,
    ORDER_STATUS_CHANNELS,
)
from services.olap_parse import split_order_row
from utils import is_delivery, order_channel

CHANNELS = (CHANNEL_DINEIN, CHANNEL_TAKEAWAY, CHANNEL_DELIVERY)


def order_channels(parsed: Iterable[tuple[str, str, str]]) -> dict[str, str]:
    """`(ключ заказа, категория, имя)` → `{ключ: канал}` для заказов с товарными строками.

    Заказ из одних служебных строк («Статус») чеком не считается и в ответ не попадает.
    """
    statuses: dict[str, set] = defaultdict(set)
    goods: set[str] = set()
    delivery: set[str] = set()
    for key, category, name in parsed:
        if not key:
            continue
        if category == ORDER_STATUS_CATEGORY:
            statuses[key].add(ORDER_STATUS_CHANNELS.get(name.strip().lower()))
            continue
        if not name:
            continue
        goods.add(key)
        if is_delivery(category, name):
            delivery.add(key)
    return {
        key: order_channel(statuses.get(key, ()), key in delivery) or CHANNEL_DINEIN
        for key in goods
    }


def row_value(row: dict) -> str:
    """Склейка group-полей строки разреза (`field0`)."""
    return row.get("field0", {}).get("value", "")


def rows_channels(rows: list[dict], bucket_field: str | None = None) -> dict[str, str]:
    """Каналы заказов для строк разреза `order_group_fields(bucket_field)`."""
    parsed = (split_order_row(row_value(r), bucket_field) for r in rows)
    return order_channels((key, category, name) for key, _b, category, name in parsed)


def delivery_orders(rows: list[dict], bucket_field: str | None = None) -> set[str]:
    """Ключи заказов доставки (для галки «без доставки»: такой заказ отсекается целиком)."""
    return {k for k, ch in rows_channels(rows, bucket_field).items() if ch == CHANNEL_DELIVERY}


def channel_revenue(rows: list[dict], bucket_field: str) -> dict[str, dict[str, float]]:
    """{корзина → {канал: выручка}}. Корзина — дата или час (`bucket_field`).

    Все позиции заказа идут в канал заказа: напиток из заказа доставки — это доставка.
    """
    channels = rows_channels(rows, bucket_field)
    out: dict[str, dict[str, float]] = {}
    for r in rows:
        key, bucket, category, name = split_order_row(row_value(r), bucket_field)
        if not name or category == ORDER_STATUS_CATEGORY or key not in channels:
            continue
        rev = float(r.get("field1", {}).get("value", 0) or 0)
        out.setdefault(bucket, {c: 0.0 for c in CHANNELS})[channels[key]] += rev
    return out
