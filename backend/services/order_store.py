"""Доступ к сохранённой истории заказов из БД — единственный источник разрезов.

`order_rows()` отдаёт строки вида `{"field0": {"value": "<склейка group через ', '>"},
"field1": {"value": n}, ...}` — исторически это формат OLAP-ответа iiko, и роутеры
разбирают его через `split_field_*`. Формат оставлен как внутренний контракт разрезов:
он не зависит от кассы, потому что собирается здесь из таблицы `order_items`.

Для периодов внутри сохранённого окна данные берутся из `order_items` / `dish_detail`;
для диапазонов старше начала истории — живой fallback к кассе через порт `pos`
(касса может истории и не иметь: у Saby выборка ограничена сроком её подключения,
поэтому история iiko живёт у нас в БД и обязана быть выкачана ДО отключения iiko).
"""

import asyncio
from datetime import date, timedelta

from sqlalchemy import func, select

from constants import (
    OLAP_FIELD_COST,
    OLAP_FIELD_DISH_CATEGORY,
    OLAP_FIELD_DISH_NAME,
    OLAP_FIELD_DISH_TYPE,
    OLAP_FIELD_GUESTS,
    OLAP_FIELD_HOUR,
    OLAP_FIELD_NET,
    OLAP_FIELD_OPEN_DATE,
    OLAP_FIELD_ORDER_NUM,
    OLAP_FIELD_QTY,
    OLAP_FIELD_SUM,
)
from models import DishDetail, OrderItem, SessionLocal
from pos import get_pos, to_item_rows

# OLAP-поле группировки → как достать его строковое значение из строки order_items
_GROUP_GETTERS = {
    OLAP_FIELD_OPEN_DATE: lambda r: r.date.isoformat(),
    OLAP_FIELD_HOUR: lambda r: str(r.hour if r.hour is not None else ""),
    OLAP_FIELD_ORDER_NUM: lambda r: r.order_num or "",
    OLAP_FIELD_DISH_CATEGORY: lambda r: r.category or "",
    OLAP_FIELD_DISH_TYPE: lambda r: r.dish_type or "",
    OLAP_FIELD_DISH_NAME: lambda r: r.name or "",
}
# data-поля: SUM/QTY/COST/NET суммируются, GUESTS — атрибут заказа (в группе с
# OrderNum константен), берём максимум
_MAX_FIELDS = {OLAP_FIELD_GUESTS}
_VALUE_GETTERS = {
    OLAP_FIELD_SUM: lambda r: r.sum or 0.0,
    OLAP_FIELD_QTY: lambda r: r.qty or 0.0,
    OLAP_FIELD_GUESTS: lambda r: r.guests or 0.0,
    OLAP_FIELD_COST: lambda r: r.cost or 0.0,
    OLAP_FIELD_NET: lambda r: r.net or 0.0,
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


def _load_items(df: date, dt: date) -> list:
    """Позиции заказов за диапазон из БД (синхронно — вызывается в отдельном потоке)."""
    with SessionLocal() as db:
        return (
            db.execute(select(OrderItem).where(OrderItem.date >= df, OrderItem.date <= dt))
            .scalars()
            .all()
        )


def _aggregate_rows(items: list, group_fields, data_fields) -> list[dict]:
    """Позиции → строки разреза: группировка по выбранным полям, суммы/максимумы."""
    getters = [_GROUP_GETTERS[f] for f in group_fields]
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


async def order_rows(group_fields, data_fields, date_from, date_to):
    """Строки разреза по заказам: из БД (или живой добор с кассы вне окна истории).

    Чтение БД и агрегация уходят в отдельный поток (`asyncio.to_thread`): месяц данных —
    это десятки тысяч строк и сотни миллисекунд чистого Python. В одном процессе с
    дашбордом живёт ручка табло `/api/orders/today`, и пока event loop занят подсчётом
    разреза, заказы к гостю не едут. Замер до выноса: четыре тяжёлых ручки держали loop
    712 мс подряд.
    """
    df, dt = _parse(date_from), _parse(date_to)
    if stored_covers(OrderItem, date_from, date_to):
        items = await asyncio.to_thread(_load_items, df, dt)
    else:
        # Период старше сохранённой истории — спрашиваем кассу и агрегируем так же.
        # `ItemRow` повторяет имена полей `OrderItem`, поэтому код ниже общий.
        items = to_item_rows(await get_pos().orders(df, dt))
    return await asyncio.to_thread(_aggregate_rows, items, group_fields, data_fields)


async def dish_detail_rows(date_from, date_to):
    """Аналог `dishes_detail`: агрегат блюд из БД (или живой fallback вне окна)."""
    df, dt = _parse(date_from), _parse(date_to)
    if not stored_covers(DishDetail, date_from, date_to):
        # Живой добор по дням: продажи по номенклатуре касса отдаёт за день.
        pos = get_pos()
        live: list[dict] = []
        day = df
        while day <= dt:
            live += [
                {
                    "dish_id": p.product_id,
                    "dish_name": p.name,
                    "category": p.category,
                    "product_type": p.product_type,
                    "quantity": p.quantity,
                    "revenue": p.revenue,
                    "cost_sum": p.cost_sum,
                }
                for p in await pos.products(day)
            ]
            day += timedelta(days=1)
        return _merge_products(live)

    return await asyncio.to_thread(_dish_detail_from_db, df, dt)


def _dish_detail_from_db(df: date, dt: date) -> list[dict]:
    """Агрегат продаж по номенклатуре за период из БД (синхронно, в отдельном потоке)."""
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


def _merge_products(rows: list[dict]) -> list[dict]:
    """Слить дневные строки продаж по номенклатуре в период (как агрегат за диапазон)."""
    agg: dict[str, dict] = {}
    for r in rows:
        a = agg.get(r["dish_id"])
        if a is None:
            a = agg[r["dish_id"]] = {**r, "quantity": 0.0, "revenue": 0.0, "cost_sum": 0.0}
        a["quantity"] += r["quantity"] or 0.0
        a["revenue"] += r["revenue"] or 0.0
        a["cost_sum"] += r["cost_sum"] or 0.0
    out = list(agg.values())
    out.sort(key=lambda r: r["revenue"], reverse=True)
    return out
