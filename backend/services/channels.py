"""Разрез выручки по каналам обслуживания: в зале / с собой / доставка.

Канал заказа берётся из служебной позиции категории «Статус» (у этой точки тип
обслуживания не пишется в системное поле кассы), а позиции из меню-категории «Доставка»
или с маркером `_д` в имени форсят доставку независимо от «Статуса».

Два правила, за которые пришлось заплатить ошибками:

- **Заказ опознаётся парой (дата, номер).** Номер уникален только внутри дня: по одному
  номеру «Статус» одного дня красил заказы того же номера из других дней.
- **Если «Статусов» на заказе несколько** (кассир отметил и «Доставка», и «С собой» —
  так было у заказа 151 от 20.09.2026), берётся сильнейший по `CHANNEL_PRIORITY`, а не
  тот, что встретился последним: иначе канал зависел от порядка строк в ответе.

Вынесено из `routers/revenue.py` (этап 7а аудита).
"""

from constants import (
    CHANNEL_DELIVERY,
    CHANNEL_DINEIN,
    CHANNEL_TAKEAWAY,
    ORDER_STATUS_CATEGORY,
    ORDER_STATUS_CHANNELS,
)
from services.olap_parse import split_order_row
from utils import is_delivery, stronger_channel

CHANNELS = (CHANNEL_DINEIN, CHANNEL_TAKEAWAY, CHANNEL_DELIVERY)


def channel_revenue(rows: list[dict], bucket_field: str) -> dict[str, dict[str, float]]:
    """{корзина → {канал: выручка}}. Корзина — дата или час (`bucket_field`).

    Канал: категория «Доставка» → доставка; иначе «Статус» заказа (по умолчанию зал).
    Заказ опознаётся парой (дата, номер) — по одному номеру «Статус» одного дня
    приписывался бы заказам того же номера из других дней.
    """
    order_channel: dict[str, str] = {}
    for r in rows:
        ordernum, _b, category, name = split_order_row(
            r.get("field0", {}).get("value", ""), bucket_field
        )
        if category == ORDER_STATUS_CATEGORY:
            # несколько «Статусов» на заказе → сильнейший (доставка > с собой > зал)
            order_channel[ordernum] = stronger_channel(
                order_channel.get(ordernum), ORDER_STATUS_CHANNELS.get(name.strip().lower())
            )
    out: dict[str, dict[str, float]] = {}
    for r in rows:
        ordernum, bucket, category, name = split_order_row(
            r.get("field0", {}).get("value", ""), bucket_field
        )
        if not name or category == ORDER_STATUS_CATEGORY:
            continue
        rev = float(r.get("field1", {}).get("value", 0) or 0)
        ch = (
            CHANNEL_DELIVERY
            if is_delivery(category, name)
            else (order_channel.get(ordernum) or CHANNEL_DINEIN)
        )
        out.setdefault(bucket, {c: 0.0 for c in CHANNELS})[ch] += rev
    return out
