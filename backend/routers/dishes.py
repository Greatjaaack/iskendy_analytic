"""Роутер продаж блюд: список с долями/с-с, распределение чеков, почасовая разбивка.

Роутер тонкий: разбирает параметры, берёт строки разреза и отдаёт ответ. Сами расчёты —
в `services/dish_cuts.py` и `services/dish_catalog.py`, и вызываются они через
`asyncio.to_thread`: считают чистый Python по десяткам тысяч строк, а в этом же процессе
живёт ручка табло, которой нельзя ждать.
"""

import asyncio

from fastapi import APIRouter, Query

from config import settings
from constants import (
    CHANNEL_DELIVERY,
    DELIVERY_CATEGORY,
    OLAP_FIELD_DISH_CATEGORY,
    OLAP_FIELD_DISH_NAME,
    OLAP_FIELD_HOUR,
    OLAP_FIELD_ORDER_TYPE,
    OLAP_FIELD_QTY,
    OLAP_FIELD_SUM,
    ORDER_STATUS_CATEGORY,
    PRODUCT_TYPE_MODIFIER,
)
from iiko_web_client import iiko_web
from pos import PROVIDER_IIKO
from services.dish_catalog import iiko_unit_cost_by_name, modifier_filters
from services.dish_cuts import (
    build_basket,
    build_check_composition,
    build_check_distribution,
    build_check_fullness,
    build_service_breakdown,
)
from services.olap_parse import order_group_fields
from services.order_store import dish_detail_rows, order_rows
from utils import (
    classify_channel,
    display_category,
    is_delivery,
    normalize_name,
    period_range,
)

router = APIRouter(prefix="/api/dishes", tags=["dishes"])


@router.get("")
async def get_dishes(
    period: str = Query("week", enum=["day", "week", "month"]),
    group_by: str = Query("dish", enum=["dish", "category"]),
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 200,
    include_delivery: bool = True,
):
    """Продажи блюд за период (живой запрос в iiko).
    group_by=dish — по блюдам, group_by=category — по категориям.
    Возвращает кол-во, выручку, с/с, маржу и доли (% от выручки и % от кол-ва)."""
    date_from_d, date_to_d = period_range(period, date_from, date_to)

    rows = await dish_detail_rows(date_from_d.isoformat(), date_to_d.isoformat())
    # rows: dish_id, dish_name, category, product_type, quantity, revenue, cost_sum
    # MODIFIER (Доставка/В зале/С собой и платные добавки) — не блюда, в список не берём
    rows = [r for r in rows if r.get("product_type") != PRODUCT_TYPE_MODIFIER]

    # с/с по блюду: iiko-с/с позиций (`order_items.cost` = ProductCostBase) за период,
    # сопоставленная по нормализованному имени. Единый источник food cost для всех
    # экранов; легаси-костинг по ТТК-файлу больше не используется.
    # канал «доставка» — по принадлежности к категории «Доставка».
    # has_cost: нашлась ли iiko-с/с по имени. Без неё с/с = 0 — НЕ выдаём
    # cost_pct/margin_pct (иначе блюдо выглядело бы как 100% маржа и искажало бы рейтинги).
    # галка «без доставки»: доставка = меню-категория «Доставка» ИЛИ имя с маркером `_д`
    # (get-data уже отдаёт категорию и имя) — просто убираем эти строки.
    if not include_delivery:
        rows = [r for r in rows if not is_delivery(r.get("category"), r.get("dish_name"))]

    unit_cost = await iiko_unit_cost_by_name(date_from_d.isoformat(), date_to_d.isoformat())
    for r in rows:
        r["channel"] = (
            CHANNEL_DELIVERY if is_delivery(r.get("category"), r.get("dish_name")) else ""
        )
        c = unit_cost.get(normalize_name(r["dish_name"]))
        r["has_cost"] = c is not None
        r["cost_sum"] = c * r["quantity"] if c is not None else 0.0

    if group_by == "category":
        agg: dict[str, dict] = {}
        for r in rows:
            cat = display_category(r.get("category"))
            a = agg.setdefault(
                cat,
                {
                    "name": cat,
                    "quantity": 0.0,
                    "revenue": 0.0,
                    "cost_sum": 0.0,
                    "has_cost": True,
                },
            )
            a["quantity"] += r["quantity"]
            a["revenue"] += r["revenue"]
            a["cost_sum"] += r["cost_sum"]
            # с/с категории полна только если у ВСЕХ её блюд есть привязка
            a["has_cost"] = a["has_cost"] and r["has_cost"]
        items = list(agg.values())
    else:
        items = [
            {
                "key": r["dish_id"],
                "name": r["dish_name"],
                "group_name": display_category(r.get("category", "")),
                "channel": r.get("channel", ""),
                "quantity": r["quantity"],
                "revenue": r["revenue"],
                "cost_sum": r["cost_sum"],
                "has_cost": r["has_cost"],
            }
            for r in rows
        ]

    total_rev = sum(i["revenue"] for i in items) or 0.0
    total_qty = sum(i["quantity"] for i in items) or 0.0

    result = []
    for i in items:
        rev = i["revenue"] or 0.0
        cost = i["cost_sum"] or 0.0
        has_cost = i.get("has_cost", False)
        # с/с-проценты считаем только при наличии полной с/с — иначе null («—» на фронте)
        cost_pct = round(cost / rev * 100, 1) if (rev and has_cost) else None
        margin_pct = round((rev - cost) / rev * 100, 1) if (rev and has_cost) else None
        result.append(
            {
                "key": i.get("key", i["name"]),
                "name": i["name"],
                "group_name": i.get("group_name", ""),
                "channel": i.get("channel", ""),
                "quantity": round(i["quantity"], 1),
                "revenue": round(rev, 2),
                "cost_sum": round(cost, 2),
                "has_cost": has_cost,
                "cost_pct": cost_pct,
                "margin_pct": margin_pct,
                "revenue_share": round(rev / total_rev * 100, 1) if total_rev else 0,
                "qty_share": (round(i["quantity"] / total_qty * 100, 1) if total_qty else 0),
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
    include_delivery: bool = True,
):
    """Распределение чеков по типу обслуживания: Доставка / В зале / С собой.

    Считаем УНИКАЛЬНЫЕ заказы по каналу — так сумма по типам равна реальному числу
    чеков (раньше суммировали кол-во модификаторов «Статус», и оно завышало итог,
    т.к. на заказ может приходиться больше одной «Статус»-строки). Заказ опознаётся
    парой (дата, номер): номер сам по себе повторяется каждый день.
    Канал заказа: модификатор «Статус» → иначе доставка по категории «Доставка»/маркеру
    `_д` → зал. При `include_delivery=false` доставочные заказы исключаются (галка).
    """
    date_from_d, date_to_d = period_range(period, date_from, date_to)

    rows = await order_rows(
        group_fields=order_group_fields(),
        data_fields=[OLAP_FIELD_QTY],
        date_from=date_from_d.isoformat(),
        date_to=date_to_d.isoformat(),
    )
    return {
        "period": "custom" if (date_from and date_to) else period,
        "date_from": date_from_d.isoformat(),
        "date_to": date_to_d.isoformat(),
        **await asyncio.to_thread(build_check_distribution, rows, include_delivery),
    }


@router.get("/hourly-breakdown")
async def get_hourly_breakdown(
    group: str = Query("category", enum=["category", "dish"]),
    period: str = Query("week", enum=["day", "week", "month"]),
    date_from: str | None = None,
    date_to: str | None = None,
    include_delivery: bool = True,
):
    """Разбивка продаж по часам в разрезе блюд/категорий (#3, через OLAP iiko).

    Для каждого часового интервала — что и на сколько продавалось (понимание «когда что
    берут»). `get-data` такой разрез не умеет, поэтому используем OLAP SALES.
    """
    date_from_d, date_to_d = period_range(period, date_from, date_to)
    dim = OLAP_FIELD_DISH_CATEGORY if group == "category" else OLAP_FIELD_DISH_NAME

    mod_names, mod_cats = await modifier_filters(date_from_d.isoformat(), date_to_d.isoformat())
    # В режиме блюд ВСЕГДА добавляем категорию в группировку: нужна и для отсева доставки,
    # и для drill-down «категория → её блюда» на фронте (каждый item несёт `category`).
    # В режиме категорий категория и есть измерение (доставку отсекаем по имени).
    with_cat = group == "dish"
    group_fields = (
        [OLAP_FIELD_HOUR, OLAP_FIELD_DISH_CATEGORY, dim] if with_cat else [OLAP_FIELD_HOUR, dim]
    )
    rows = await order_rows(
        group_fields=group_fields,
        data_fields=[OLAP_FIELD_SUM, OLAP_FIELD_QTY],
        date_from=date_from_d.isoformat(),
        date_to=date_to_d.isoformat(),
    )

    # строка: field0="<час>[, <категория>], <имя>", field1=выручка, field2=кол-во
    hours: dict[int, dict] = {}
    for r in rows:
        key = str(r.get("field0", {}).get("value", ""))
        category = ""
        if with_cat:
            parts = key.split(", ", 2)
            if len(parts) < 3 or not parts[0].isdigit():
                continue
            hour, category, name = int(parts[0]), parts[1], parts[2]
            # галка «без доставки»: доставка = категория «Доставка» ИЛИ имя с маркером `_д`
            if not include_delivery and is_delivery(category, name):
                continue
        else:
            parts = key.split(", ", 1)
            if not parts[0].isdigit():
                continue
            hour = int(parts[0])
            name = parts[1] if len(parts) > 1 else "—"
            # в режиме категорий name = категория: отсекаем «Доставка» при выключенной доставке
            if not include_delivery and name == DELIVERY_CATEGORY:
                continue
        # модификаторы — не товар: в режиме категорий name = категория, в режиме блюд = имя
        is_mod = name in mod_cats if group == "category" else normalize_name(name) in mod_names
        if name == ORDER_STATUS_CATEGORY or is_mod:
            continue
        # отображаемое имя категории (для вывода/drill): в режиме категорий это name,
        # в режиме блюд — поле category. На детект доставки/модификаторов выше не влияет.
        if group == "category":
            name = display_category(name)
        else:
            category = display_category(category)
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
        it = h["items"].setdefault(
            name, {"name": name, "category": category, "revenue": 0.0, "quantity": 0.0}
        )
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


@router.get("/service-breakdown")
async def get_service_breakdown(
    group: str = Query("dish", enum=["category", "dish"]),
    period: str = Query("week", enum=["day", "week", "month"]),
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 200,
):
    """Разрез блюдо/категория × канал обслуживания (#4): в зале / с собой / в доставку.

    Тип обслуживания у точки не пишется в OrderType (он пуст) — он задаётся модификатором
    категории «Статус» на уровне ЗАКАЗА. Поэтому группируем по [дата, номер заказа,
    категория, блюдо]: у каждого заказа из его «Статус»-строки берём канал и относим к
    нему все блюда заказа. Дата в группировке обязательна — без неё заказы с одинаковым
    номером из разных дней склеились бы в один, и часть блюд ушла бы не в свой канал.
    Постфикс `_д` форсит «доставка» (заодно подстраховка, если у заказа нет «Статуса»).
    """
    date_from_d, date_to_d = period_range(period, date_from, date_to)

    _, mod_cats = await modifier_filters(date_from_d.isoformat(), date_to_d.isoformat())
    rows = await order_rows(
        group_fields=order_group_fields(),
        data_fields=[OLAP_FIELD_QTY, OLAP_FIELD_SUM],
        date_from=date_from_d.isoformat(),
        date_to=date_to_d.isoformat(),
    )
    return {
        "period": "custom" if (date_from and date_to) else period,
        "date_from": date_from_d.isoformat(),
        "date_to": date_to_d.isoformat(),
        **await asyncio.to_thread(build_service_breakdown, rows, group, mod_cats, limit),
    }


@router.get("/order-types")
async def get_order_types(
    period: str = Query("week", enum=["day", "week", "month"]),
    date_from: str | None = None,
    date_to: str | None = None,
):
    """Диагностика #4: распределение количества по «сырому» полю типа заказа OLAP.

    Нужна, чтобы подтвердить имя поля `OLAP_FIELD_ORDER_TYPE` и увидеть реальные значения
    (доставка/самовывоз/обычный…). При неверном имени поля OLAP вернёт ошибку.

    Ручка привязана к OLAP iiko: это единственное место, где мы намеренно смотрим в
    «сырое» поле кассы. На другой кассе такого поля нет — отдаём пустой ответ с
    пояснением, а не 500.
    """
    if (settings.pos_provider or "").strip().lower() != PROVIDER_IIKO:
        return {
            "field": OLAP_FIELD_ORDER_TYPE,
            "values": [],
            "note": f"диагностика доступна только на кассе {PROVIDER_IIKO}",
        }
    df, dt = period_range(period, date_from, date_to)
    # диагностика OrderType — намеренно живой запрос (поле в БД не храним, оно пусто)
    rows = await iiko_web.olap_sales(
        group_fields=[OLAP_FIELD_ORDER_TYPE],
        data_fields=[OLAP_FIELD_QTY],
        date_from=df.isoformat(),
        date_to=dt.isoformat(),
    )
    values = [
        {
            "order_type": str(r.get("field0", {}).get("value", "")),
            "qty": float(r.get("field1", {}).get("value", 0) or 0),
            "channel": classify_channel(str(r.get("field0", {}).get("value", ""))),
        }
        for r in rows
    ]
    values.sort(key=lambda x: x["qty"], reverse=True)
    return {"field": OLAP_FIELD_ORDER_TYPE, "values": values}


@router.get("/check-composition")
async def get_check_composition(
    period: str = Query("week", enum=["day", "week", "month"]),
    date_from: str | None = None,
    date_to: str | None = None,
    include_delivery: bool = True,
):
    """Состав чека (#5): средняя доля категорий в чеке — по кол-ву и по выручке, за период
    и по часам. Доля считается на каждый чек (категория / итог чека), затем усредняется.
    """
    df, dt = period_range(period, date_from, date_to)
    _, mod_cats = await modifier_filters(df.isoformat(), dt.isoformat())
    rows = await order_rows(
        group_fields=order_group_fields(OLAP_FIELD_HOUR),
        data_fields=[OLAP_FIELD_QTY, OLAP_FIELD_SUM],
        date_from=df.isoformat(),
        date_to=dt.isoformat(),
    )
    return {
        "period": "custom" if (date_from and date_to) else period,
        "date_from": df.isoformat(),
        "date_to": dt.isoformat(),
        **await asyncio.to_thread(build_check_composition, rows, mod_cats, include_delivery),
    }


@router.get("/check-fullness")
async def get_check_fullness(
    period: str = Query("week", enum=["day", "week", "month"]),
    date_from: str | None = None,
    date_to: str | None = None,
    include_delivery: bool = True,
):
    """Распределение чеков по числу позиций (1 / 2 / 3 / 4+), по часам.

    Расчёт — `services/dish_cuts.build_check_fullness`.
    """
    df, dt = period_range(period, date_from, date_to)
    _, mod_cats = await modifier_filters(df.isoformat(), dt.isoformat())
    rows = await order_rows(
        group_fields=order_group_fields(OLAP_FIELD_HOUR),
        data_fields=[OLAP_FIELD_QTY],
        date_from=df.isoformat(),
        date_to=dt.isoformat(),
    )
    return {
        "period": "custom" if (date_from and date_to) else period,
        "date_from": df.isoformat(),
        "date_to": dt.isoformat(),
        **await asyncio.to_thread(build_check_fullness, rows, mod_cats, include_delivery),
    }


@router.get("/basket")
async def get_basket(
    period: str = Query("week", enum=["day", "week", "month"]),
    group: str = Query("category", enum=["category", "dish"]),
    top: int = 12,
    date_from: str | None = None,
    date_to: str | None = None,
    include_delivery: bool = True,
):
    """Матрица сочетаемости (market basket): что чаще берут вместе в одном чеке.

    Расчёт — `services/dish_cuts.build_basket`; здесь период, запрос разреза и границы.
    """
    df, dt = period_range(period, date_from, date_to)
    _, mod_cats = await modifier_filters(df.isoformat(), dt.isoformat())
    rows = await order_rows(
        group_fields=order_group_fields(),
        data_fields=[OLAP_FIELD_QTY],
        date_from=df.isoformat(),
        date_to=dt.isoformat(),
    )
    return {
        "period": "custom" if (date_from and date_to) else period,
        "date_from": df.isoformat(),
        "date_to": dt.isoformat(),
        **await asyncio.to_thread(build_basket, rows, group, top, mod_cats, include_delivery),
    }
