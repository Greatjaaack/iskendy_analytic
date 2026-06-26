"""Доступ к сохранённой истории заказов из БД — drop-in замена живых запросов iiko.

`order_rows()` повторяет контракт `IikoWebClient.olap_sales` (строки вида
`{"field0": {"value": "<склейка group через ', '>"}, "field1": {"value": n}, ...}`),
а `dish_detail_rows()` — контракт `IikoWebClient.dishes_detail`. Поэтому даунстрим-
разбор в роутерах (`split_field_*`) и вся доменная логика остаются без изменений.

Для периодов внутри сохранённого окна данные берутся из таблиц `order_items` /
`dish_detail`; для диапазонов старше начала истории — живой fallback к iiko.
"""

from datetime import date

from sqlalchemy import func, select

from constants import (
    OLAP_FIELD_DISH_CATEGORY,
    OLAP_FIELD_DISH_NAME,
    OLAP_FIELD_GUESTS,
    OLAP_FIELD_HOUR,
    OLAP_FIELD_OPEN_DATE,
    OLAP_FIELD_ORDER_NUM,
    OLAP_FIELD_QTY,
    OLAP_FIELD_SUM,
)
from iiko_web_client import iiko_web
from models import DishDetail, OrderItem, SessionLocal

# OLAP-поле группировки → как достать его строковое значение из строки order_items
_GROUP_GETTERS = {
    OLAP_FIELD_OPEN_DATE: lambda r: r.date.isoformat(),
    OLAP_FIELD_HOUR: lambda r: str(r.hour if r.hour is not None else ""),
    OLAP_FIELD_ORDER_NUM: lambda r: r.order_num or "",
    OLAP_FIELD_DISH_CATEGORY: lambda r: r.category or "",
    OLAP_FIELD_DISH_NAME: lambda r: r.name or "",
}
# data-поля: SUM/QTY суммируются, GUESTS — атрибут заказа (в группе с OrderNum
# константен), берём максимум
_MAX_FIELDS = {OLAP_FIELD_GUESTS}
_VALUE_GETTERS = {
    OLAP_FIELD_SUM: lambda r: r.sum or 0.0,
    OLAP_FIELD_QTY: lambda r: r.qty or 0.0,
    OLAP_FIELD_GUESTS: lambda r: r.guests or 0.0,
}


def _parse(d: str) -> date:
    return date.fromisoformat(d)


def _min_date(model) -> date | None:
    with SessionLocal() as db:
        return db.execute(select(func.min(model.date))).scalar()


def stored_covers(model, date_from: str, date_to: str) -> bool:
    """Покрывает ли сохранённая история запрошенный период целиком.

    Бэкафилл заполняет дни непрерывно от начала истории до сегодня, недавние дни
    пере-синкаются ежечасно, поэтому достаточно, чтобы начало периода было не
    раньше первой сохранённой даты.
    """
    lo = _min_date(model)
    return lo is not None and _parse(date_from) >= lo


async def order_rows(group_fields, data_fields, date_from, date_to):
    """Аналог `olap_sales`: строки заказа из БД (или живой fallback вне окна)."""
    if not stored_covers(OrderItem, date_from, date_to):
        return await iiko_web.olap_sales(
            group_fields=group_fields,
            data_fields=data_fields,
            date_from=date_from,
            date_to=date_to,
        )

    df, dt = _parse(date_from), _parse(date_to)
    with SessionLocal() as db:
        items = (
            db.execute(select(OrderItem).where(OrderItem.date >= df, OrderItem.date <= dt))
            .scalars()
            .all()
        )

    getters = [_GROUP_GETTERS[f] for f in group_fields]
    # группировка по значениям выбранных group-полей
    agg: dict[tuple, dict] = {}
    for r in items:
        key = tuple(g(r) for g in getters)
        bucket = agg.get(key)
        if bucket is None:
            bucket = agg[key] = {f: 0.0 for f in data_fields}
        for f in data_fields:
            v = _VALUE_GETTERS[f](r)
            if f in _MAX_FIELDS:
                bucket[f] = max(bucket[f], v)
            else:
                bucket[f] += v

    rows = []
    for key, bucket in agg.items():
        row = {"field0": {"value": ", ".join(key)}}
        for i, f in enumerate(data_fields, start=1):
            row[f"field{i}"] = {"value": bucket[f]}
        rows.append(row)
    return rows


async def dish_detail_rows(date_from, date_to):
    """Аналог `dishes_detail`: агрегат блюд из БД (или живой fallback вне окна)."""
    if not stored_covers(DishDetail, date_from, date_to):
        return await iiko_web.dishes_detail(date_from, date_to)

    df, dt = _parse(date_from), _parse(date_to)
    with SessionLocal() as db:
        rows = (
            db.execute(select(DishDetail).where(DishDetail.date >= df, DishDetail.date <= dt))
            .scalars()
            .all()
        )

    # суммируем по позиции номенклатуры за период (как get-data за диапазон)
    agg: dict[str, dict] = {}
    for r in rows:
        a = agg.get(r.dish_id)
        if a is None:
            a = agg[r.dish_id] = {
                "dish_id": r.dish_id,
                "dish_name": r.dish_name,
                "category": r.category or "",
                "product_type": r.product_type or "",
                "quantity": 0.0,
                "revenue": 0.0,
                "cost_sum": 0.0,
            }
        a["quantity"] += r.quantity or 0.0
        a["revenue"] += r.revenue or 0.0
        a["cost_sum"] += r.cost_sum or 0.0

    out = list(agg.values())
    out.sort(key=lambda r: r["revenue"], reverse=True)
    return out
