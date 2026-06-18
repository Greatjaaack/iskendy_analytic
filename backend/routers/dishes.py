"""Роутер продаж блюд: список с долями/с-с, распределение чеков, почасовая разбивка (OLAP)."""

from fastapi import APIRouter, Query
from sqlalchemy import select

from constants import (
    OLAP_FIELD_DISH_CATEGORY,
    OLAP_FIELD_DISH_NAME,
    OLAP_FIELD_HOUR,
    OLAP_FIELD_QTY,
    OLAP_FIELD_SUM,
    ORDER_STATUS_CATEGORY,
    PRODUCT_TYPE_MODIFIER,
)
from iiko_web_client import iiko_web
from models import DishMapping, SessionLocal, Ttk
from utils import normalize_name, period_range, split_delivery

router = APIRouter(prefix="/api/dishes", tags=["dishes"])


def _ttk_portion_cost(t: Ttk) -> float | None:
    """С/с ОДНОЙ ПОРЦИИ блюда: только `cost_full` (порционная «Итого с/с»).

    `cost_total` сознательно НЕ используется как запасной вариант: это с/с за весь
    выход карты (батч), а не за порцию (напр. чай — 4800 мл ≈ 24 чашки), и умножение
    его на проданное количество завышает с/с в разы.
    """
    return t.cost_full or None


def _dish_unit_cost() -> dict[str, float]:
    """С/с одной ПОРЦИИ блюда по нормализованному имени продажи.

    Приоритет: ручная привязка `DishMapping` (продажа→ТТК) → авто-совпадение имени с ТТК.
    Источник с/с — порция из «Сводной» (`cost_full`); метрика iiko относит расход к
    ингредиентам, а не к блюду, поэтому для с/с не годится.
    """
    out: dict[str, float] = {}
    with SessionLocal() as db:
        # авто: по совпадению нормализованного имени блюда с именем ТТК
        for n, c in db.execute(select(Ttk.name_norm, Ttk.cost_full)).all():
            if c:
                out[n] = c
        # ручные привязки имеют приоритет (перезаписывают авто)
        for m in db.query(DishMapping).all():
            cost = _ttk_portion_cost(m.ttk) if m.ttk else None
            if cost:
                out[m.sale_name_norm] = cost
    return out


@router.get("")
async def get_dishes(
    period: str = Query("week", enum=["day", "week", "month"]),
    group_by: str = Query("dish", enum=["dish", "category"]),
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 200,
):
    """Продажи блюд за период (живой запрос в iiko).
    group_by=dish — по блюдам, group_by=category — по категориям.
    Возвращает кол-во, выручку, с/с, маржу и доли (% от выручки и % от кол-ва)."""
    date_from_d, date_to_d = period_range(period, date_from, date_to)

    rows = await iiko_web.dishes_detail(date_from_d.isoformat(), date_to_d.isoformat())
    # rows: dish_id, dish_name, category, product_type, quantity, revenue, cost_sum
    # MODIFIER (Доставка/В зале/С собой и платные добавки) — не блюда, в список не берём
    rows = [r for r in rows if r.get("product_type") != PRODUCT_TYPE_MODIFIER]

    # с/с по блюду: порционная с/с × количество (iiko-метрика по блюду ~0).
    # постфикс «_д» (доставка) срезаем перед матчингом — у доставочной позиции та же ТТК.
    unit_cost = _dish_unit_cost()
    for r in rows:
        base_name, is_delivery = split_delivery(r["dish_name"])
        r["channel"] = "доставка" if is_delivery else ""
        c = unit_cost.get(normalize_name(base_name))
        if c is not None:
            r["cost_sum"] = c * r["quantity"]

    if group_by == "category":
        agg: dict[str, dict] = {}
        for r in rows:
            cat = r.get("category") or "Без категории"
            a = agg.setdefault(cat, {"name": cat, "quantity": 0.0, "revenue": 0.0, "cost_sum": 0.0})
            a["quantity"] += r["quantity"]
            a["revenue"] += r["revenue"]
            a["cost_sum"] += r["cost_sum"]
        items = list(agg.values())
    else:
        items = [
            {
                "key": r["dish_id"],
                "name": r["dish_name"],
                "group_name": r.get("category", ""),
                "channel": r.get("channel", ""),
                "quantity": r["quantity"],
                "revenue": r["revenue"],
                "cost_sum": r["cost_sum"],
            }
            for r in rows
        ]

    total_rev = sum(i["revenue"] for i in items) or 0.0
    total_qty = sum(i["quantity"] for i in items) or 0.0

    result = []
    for i in items:
        rev = i["revenue"] or 0.0
        cost = i["cost_sum"] or 0.0
        result.append(
            {
                "key": i.get("key", i["name"]),
                "name": i["name"],
                "group_name": i.get("group_name", ""),
                "channel": i.get("channel", ""),
                "quantity": round(i["quantity"], 1),
                "revenue": round(rev, 2),
                "cost_sum": round(cost, 2),
                "cost_pct": round(cost / rev * 100, 1) if rev else 0,
                "margin_pct": round((rev - cost) / rev * 100, 1) if rev else 0,
                "revenue_share": round(rev / total_rev * 100, 1) if total_rev else 0,
                "qty_share": round(i["quantity"] / total_qty * 100, 1) if total_qty else 0,
            }
        )
    result.sort(key=lambda x: x["revenue"], reverse=True)

    return {
        "period": "custom" if (date_from and date_to) else period,
        "group_by": group_by,
        "date_from": date_from_d.isoformat(),
        "date_to": date_to_d.isoformat(),
        "totals": {"revenue": round(total_rev, 2), "quantity": round(total_qty, 1)},
        "data": result[:limit],
    }


@router.get("/check-distribution")
async def get_check_distribution(
    period: str = Query("week", enum=["day", "week", "month"]),
    date_from: str | None = None,
    date_to: str | None = None,
):
    """Распределение чеков по типу обслуживания: Доставка / В зале / С собой.

    Считается по модификаторам категории «Статус» (один на заказ) — их количество
    приблизительно равно числу заказов соответствующего типа.
    """
    date_from_d, date_to_d = period_range(period, date_from, date_to)

    rows = await iiko_web.dishes_detail(date_from_d.isoformat(), date_to_d.isoformat())
    status_rows = [r for r in rows if r.get("category") == ORDER_STATUS_CATEGORY]

    total = sum(r["quantity"] for r in status_rows) or 0.0
    data = sorted(
        (
            {
                "type": r["dish_name"],
                "count": int(r["quantity"]),
                "share": round(r["quantity"] / total * 100, 1) if total else 0,
            }
            for r in status_rows
        ),
        key=lambda x: x["count"],
        reverse=True,
    )

    return {
        "period": "custom" if (date_from and date_to) else period,
        "date_from": date_from_d.isoformat(),
        "date_to": date_to_d.isoformat(),
        "total": int(total),
        "data": data,
    }


@router.get("/hourly-breakdown")
async def get_hourly_breakdown(
    group: str = Query("category", enum=["category", "dish"]),
    period: str = Query("week", enum=["day", "week", "month"]),
    date_from: str | None = None,
    date_to: str | None = None,
):
    """Разбивка продаж по часам в разрезе блюд/категорий (#3, через OLAP iiko).

    Для каждого часового интервала — что и на сколько продавалось (понимание «когда что
    берут»). `get-data` такой разрез не умеет, поэтому используем OLAP SALES.
    """
    date_from_d, date_to_d = period_range(period, date_from, date_to)
    dim = OLAP_FIELD_DISH_CATEGORY if group == "category" else OLAP_FIELD_DISH_NAME

    rows = await iiko_web.olap_sales(
        group_fields=[OLAP_FIELD_HOUR, dim],
        data_fields=[OLAP_FIELD_SUM, OLAP_FIELD_QTY],
        date_from=date_from_d.isoformat(),
        date_to=date_to_d.isoformat(),
    )

    # строка: field0="<час>, <имя>", field1=выручка, field2=кол-во
    hours: dict[int, dict] = {}
    for r in rows:
        key = str(r.get("field0", {}).get("value", ""))
        parts = key.split(", ", 1)
        if not parts[0].isdigit():
            continue
        hour = int(parts[0])
        name = parts[1] if len(parts) > 1 else "—"
        if name == ORDER_STATUS_CATEGORY:  # модификаторы типа обслуживания — не товар
            continue
        rev = float(r.get("field1", {}).get("value", 0) or 0)
        qty = float(r.get("field2", {}).get("value", 0) or 0)

        h = hours.setdefault(
            hour,
            {
                "hour": hour,
                "label": f"{hour:02d}-{hour + 1:02d}",
                "revenue": 0.0,
                "quantity": 0.0,
                "items": {},
            },
        )
        h["revenue"] += rev
        h["quantity"] += qty
        it = h["items"].setdefault(name, {"name": name, "revenue": 0.0, "quantity": 0.0})
        it["revenue"] += rev
        it["quantity"] += qty

    result = []
    for hour in sorted(hours):
        h = hours[hour]
        items = sorted(h["items"].values(), key=lambda x: x["revenue"], reverse=True)
        for it in items:
            it["revenue"] = round(it["revenue"], 2)
            it["quantity"] = round(it["quantity"], 1)
        result.append(
            {
                "hour": hour,
                "label": h["label"],
                "revenue": round(h["revenue"], 2),
                "quantity": round(h["quantity"], 1),
                "items": items,
            }
        )

    return {
        "group_by": group,
        "period": "custom" if (date_from and date_to) else period,
        "date_from": date_from_d.isoformat(),
        "date_to": date_to_d.isoformat(),
        "data": result,
    }
