"""Логика галки «без доставки»: выручка/чеки доставки и их вычитание из дней.

Доставка = меню-категория «Доставка» ИЛИ имя позиции с маркером `_д`
(единое правило — utils.is_delivery). При выключенной галке бэкенд вычитает
эти суммы из REV_GROSS-дней/часов. Вынесено из routers/revenue.py.
"""

from datetime import date

from constants import (
    OLAP_FIELD_DISH_CATEGORY,
    OLAP_FIELD_DISH_NAME,
    OLAP_FIELD_ORDER_NUM,
    OLAP_FIELD_SUM,
)
from iiko_web_client import iiko_web
from services.olap_parse import split_field_4
from utils import is_delivery


def delivery_per_bucket(rows: list[dict]) -> dict[str, dict[str, float]]:
    """{bucket → {"revenue": выручка доставки, "checks": число заказов доставки}}.

    Доставка = меню-категория «Доставка» ИЛИ имя с маркером `_д` (см. utils.is_delivery):
    выручка — сумма по таким позициям, чек — заказ, в котором есть хотя бы одна.
    bucket = 1-е group-поле (дата/час).
    """
    out: dict[str, dict[str, float]] = {}
    seen: dict[str, set[str]] = {}
    for r in rows:
        bucket, ordernum, category, name = split_field_4(r.get("field0", {}).get("value", ""))
        if not name or not is_delivery(category, name):
            continue
        rev = float(r.get("field1", {}).get("value", 0) or 0)
        e = out.setdefault(bucket, {"revenue": 0.0, "checks": 0})
        e["revenue"] += rev
        s = seen.setdefault(bucket, set())
        if ordernum not in s:
            s.add(ordernum)
            e["checks"] += 1
    return out


async def delivery_buckets(date_from: date, date_to: date, bucket_field: str) -> dict[str, dict]:
    """Выручка и чеки доставки по корзинам (дата/час) за период — через OLAP SALES."""
    rows = await iiko_web.olap_sales(
        group_fields=[
            bucket_field,
            OLAP_FIELD_ORDER_NUM,
            OLAP_FIELD_DISH_CATEGORY,
            OLAP_FIELD_DISH_NAME,
        ],
        data_fields=[OLAP_FIELD_SUM],
        date_from=date_from.isoformat(),
        date_to=date_to.isoformat(),
    )
    return delivery_per_bucket(rows)


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
