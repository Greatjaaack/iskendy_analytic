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
    NON_PRODUCT_CATEGORIES,
    OLAP_FIELD_DISH_CATEGORY,
    OLAP_FIELD_DISH_NAME,
    OLAP_FIELD_DISH_TYPE,
    OLAP_FIELD_HOUR,
    OLAP_FIELD_OPEN_DATE,
    OLAP_FIELD_ORDER_NUM,
    OLAP_FIELD_ORDER_TYPE,
    OLAP_FIELD_QTY,
    OLAP_FIELD_SUM,
    PRODUCT_TYPE_MODIFIER,
)
from iiko_web_client import iiko_web
from pos import PROVIDER_IIKO
from services.channels import order_channels
from services.delivery import delivery_sales_by_dish
from services.dish_catalog import iiko_unit_cost_by_name, modifier_filters
from services.dish_cuts import (
    build_basket,
    build_check_composition,
    build_check_distribution,
    build_check_fullness,
    build_service_breakdown,
)
from services.olap_parse import ORDER_KEY_SEP, order_group_fields, split_field
from services.order_store import dish_detail_rows, order_rows
from utils import (
    classify_channel,
    display_category,
    is_delivery,
    normalize_name,
    period_range,
)

router = APIRouter(prefix="/api/dishes", tags=["dishes"])


def without_delivery(rows: list[dict], sold: dict[tuple[str, str], list]) -> list[dict]:
    """Строки `dish_detail` за вычетом продаж в заказах доставки (по категории и имени).

    Одной паре (категория, имя) может соответствовать несколько позиций номенклатуры —
    вычитаем по очереди, не уходя в минус. Строка без остатка продаж убирается.
    """
    left = {k: list(v) for k, v in sold.items()}
    out = []
    for r in rows:
        rest = left.get((r.get("category") or "", r.get("dish_name") or ""))
        if rest:
            qty, rev = min(rest[0], r["quantity"]), min(rest[1], r["revenue"])
            r = {**r, "quantity": r["quantity"] - qty, "revenue": r["revenue"] - rev}
            rest[0] -= qty
            rest[1] -= rev
        if r["quantity"] > 1e-9 or r["revenue"] > 0.005:
            out.append(r)
    return out


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
    # галка «без доставки»: вычитаем всё, что продано в заказах доставки (заказ целиком,
    # см. `services.channels`) — и позиции с пометкой доставки, и напитки из её комбо.
    # У `dish_detail` нет заказов, поэтому продажи доставки берём из позиций заказов.
    if not include_delivery:
        rows = without_delivery(rows, await delivery_sales_by_dish(date_from_d, date_to_d))

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
    _, mod_cats = await modifier_filters(date_from_d.isoformat(), date_to_d.isoformat())
    # Строки — по заказам и с типом позиции: заказ нужен галке «без доставки» (заказ
    # доставки отсекается целиком), тип — отсеву модификаторов. До 09.10.2026 модификаторы
    # отсекались по ИМЕНИ, и в режиме блюд вместе с бесплатным модификатором «Айран»
    # пропадал платный «Айран» (февраль–июль: 5–8 % выручки), а в режиме категорий — нет.
    rows = await order_rows(
        group_fields=[
            OLAP_FIELD_OPEN_DATE,
            OLAP_FIELD_HOUR,
            OLAP_FIELD_ORDER_NUM,
            OLAP_FIELD_DISH_CATEGORY,
            OLAP_FIELD_DISH_TYPE,
            OLAP_FIELD_DISH_NAME,
        ],
        data_fields=[OLAP_FIELD_SUM, OLAP_FIELD_QTY],
        date_from=date_from_d.isoformat(),
        date_to=date_to_d.isoformat(),
    )
    parsed = [(split_field(r.get("field0", {}).get("value", ""), 6), r) for r in rows]
    skip: set[str] = set()
    if not include_delivery:
        channels = order_channels(
            (f"{day}{ORDER_KEY_SEP}{num}", category, name)
            for (day, _h, num, category, _t, name), _r in parsed
        )
        skip = {k for k, ch in channels.items() if ch == CHANNEL_DELIVERY}

    # строка: field0="<дата>, <час>, <заказ>, <категория>, <тип>, <имя>", field1/2=выручка/кол-во
    hours: dict[int, dict] = {}
    for (day, hs, num, category, dish_type, dish_name), r in parsed:
        if not hs.isdigit() or not dish_name or f"{day}{ORDER_KEY_SEP}{num}" in skip:
            continue
        # модификаторы и «Статус» — не товар; категорию «модификаторы» отсекаем целиком
        if (
            dish_type == PRODUCT_TYPE_MODIFIER
            or category in NON_PRODUCT_CATEGORIES
            or category in mod_cats
        ):
            continue
        hour = int(hs)
        category = display_category(category)
        name = category if group == "category" else dish_name
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
