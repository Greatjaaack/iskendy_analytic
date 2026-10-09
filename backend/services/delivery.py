"""Логика галки «без доставки»: выручка/чеки доставки и их вычитание из дней.

Доставка — свойство ЗАКАЗА (`services.channels`, правило `utils.order_channel`), и при
выключенной галке заказ доставки отсекается целиком: вместе с напитками комбо и прочими
позициями без пометки доставки. Вынесено из routers/revenue.py.
"""

from datetime import date

from constants import OLAP_FIELD_QTY, OLAP_FIELD_SUM, ORDER_STATUS_CATEGORY
from services.channels import delivery_orders, row_value
from services.olap_parse import ORDER_KEY_SEP, order_group_fields, split_order_row
from services.order_store import order_rows


def delivery_per_bucket(rows: list[dict], bucket_field: str) -> dict[str, dict[str, float]]:
    """{корзина → {"revenue": выручка доставки, "checks": число заказов доставки}}.

    Выручка — ВСЕ товарные позиции заказов доставки, чек — сам заказ. Корзина — дата
    или час (`bucket_field`); заказ опознаётся парой (дата, номер).
    """
    delivery = delivery_orders(rows, bucket_field)
    out: dict[str, dict[str, float]] = {}
    seen: dict[str, set[str]] = {}
    for r in rows:
        key, bucket, category, name = split_order_row(row_value(r), bucket_field)
        if key not in delivery or not name or category == ORDER_STATUS_CATEGORY:
            continue
        rev = float(r.get("field1", {}).get("value", 0) or 0)
        e = out.setdefault(bucket, {"revenue": 0.0, "checks": 0})
        e["revenue"] += rev
        s = seen.setdefault(bucket, set())
        if key not in s:
            s.add(key)
            e["checks"] += 1
    return out


async def delivery_buckets(date_from: date, date_to: date, bucket_field: str) -> dict[str, dict]:
    """Выручка и чеки доставки по корзинам (дата/час) за период."""
    rows = await order_rows(
        group_fields=order_group_fields(bucket_field),
        data_fields=[OLAP_FIELD_SUM],
        date_from=date_from.isoformat(),
        date_to=date_to.isoformat(),
    )
    return delivery_per_bucket(rows, bucket_field)


async def delivery_order_keys(date_from: date, date_to: date) -> set[tuple[date, str]]:
    """Заказы доставки за период как пары `(дата, номер)` — для таблиц с ключом заказа."""
    rows = await order_rows(
        group_fields=order_group_fields(),
        data_fields=[OLAP_FIELD_SUM],
        date_from=date_from.isoformat(),
        date_to=date_to.isoformat(),
    )
    out = set()
    for key in delivery_orders(rows):
        day, num = key.split(ORDER_KEY_SEP, 1)
        out.add((date.fromisoformat(day), num))
    return out


async def delivery_sales_by_dish(date_from: date, date_to: date) -> dict[tuple[str, str], list]:
    """Продажи внутри заказов доставки: `{(категория, имя): [кол-во, выручка]}`.

    Нужны таблице блюд: её источник (`dish_detail`) не знает заказов, поэтому без
    доставки из неё вычитаются именно эти количества и суммы.
    """
    rows = await order_rows(
        group_fields=order_group_fields(),
        data_fields=[OLAP_FIELD_SUM, OLAP_FIELD_QTY],
        date_from=date_from.isoformat(),
        date_to=date_to.isoformat(),
    )
    delivery = delivery_orders(rows)
    out: dict[tuple[str, str], list] = {}
    for r in rows:
        key, _b, category, name = split_order_row(row_value(r))
        if key not in delivery or not name or category == ORDER_STATUS_CATEGORY:
            continue
        a = out.setdefault((category, name), [0.0, 0.0])
        a[0] += float(r.get("field2", {}).get("value", 0) or 0)
        a[1] += float(r.get("field1", {}).get("value", 0) or 0)
    return out


def exclude_delivery(days: list[dict], del_buckets: dict[str, dict]) -> None:
    """Вычитает выручку и чеки доставки из дней (in-place). Корзина дня — `date`.

    `food_cost_pct` и `cost_sum` не трогаем: с/с по каналам не разбивается, так что
    это остаётся food cost всей точки (вычесть «с/с доставки» нечем).
    """
    for d in days:
        dd = del_buckets.get(d["date"])
        if not dd:
            continue
        d["total_sum"] = round(max(0.0, d["total_sum"] - dd["revenue"]), 2)
        d["check_count"] = max(0, d["check_count"] - dd["checks"])
        d["avg_check"] = round(d["total_sum"] / d["check_count"], 2) if d["check_count"] else 0
