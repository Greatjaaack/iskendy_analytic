"""Роутер продаж блюд: список с долями/с-с, распределение чеков, почасовая разбивка (OLAP)."""

from collections import Counter, defaultdict
from itertools import combinations

from fastapi import APIRouter, Query
from sqlalchemy import select

from constants import (
    CHANNEL_DELIVERY,
    CHANNEL_DINEIN,
    CHANNEL_TAKEAWAY,
    DELIVERY_CATEGORY,
    NON_PRODUCT_CATEGORIES,
    OLAP_FIELD_DISH_CATEGORY,
    OLAP_FIELD_DISH_NAME,
    OLAP_FIELD_HOUR,
    OLAP_FIELD_ORDER_NUM,
    OLAP_FIELD_ORDER_TYPE,
    OLAP_FIELD_QTY,
    OLAP_FIELD_SUM,
    ORDER_STATUS_CATEGORY,
    ORDER_STATUS_CHANNELS,
    PRODUCT_TYPE_MODIFIER,
)
from iiko_web_client import iiko_web
from models import DishMapping, SessionLocal, Ttk
from utils import (
    classify_channel,
    display_category,
    is_delivery,
    normalize_name,
    period_range,
)

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
        # авто: по совпадению нормализованного имени блюда с НЕ-полуфабрикатной ТТК.
        # П/ф исключаем: их не продают напрямую, а их имя часто совпадает с блюдом
        # («Чечевичный суп» — и блюдо-порция, и п/ф-котёл) — иначе подставилась бы
        # батч-себестоимость п/ф вместо порционной.
        for n, c in db.execute(
            select(Ttk.name_norm, Ttk.cost_full).where(Ttk.is_semi.is_(False))
        ).all():
            if c:
                out[n] = c
        # ручные привязки имеют приоритет (перезаписывают авто)
        for m in db.query(DishMapping).all():
            cost = _ttk_portion_cost(m.ttk) if m.ttk else None
            if cost:
                out[m.sale_name_norm] = cost
    return out


async def _modifier_filters(date_from_iso: str, date_to_iso: str) -> tuple[set[str], set[str]]:
    """(норм. имена, категории) платных модификаторов за период.

    OLAP SALES не отдаёт productType, поэтому набор модификаторов («Разрезать 1/2» и пр.)
    берём из `dishes_detail` (get-data, там есть productType) и исключаем их из
    OLAP-разрезов продаж: модификаторы — не блюда и в продажи попадать не должны.
    Категория и имена «Статуса» (Доставка/В зале/С собой) тоже сюда попадают — в разрезах
    они либо уже отсекаются по категории, либо предварительно дают канал заказа.
    """
    rows = await iiko_web.dishes_detail(date_from_iso, date_to_iso)
    names: set[str] = set()
    cats: set[str] = set()
    for r in rows:
        if r.get("product_type") == PRODUCT_TYPE_MODIFIER:
            names.add(normalize_name(r["dish_name"]))
            if r.get("category"):
                cats.add(r["category"])
    return names, cats


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

    rows = await iiko_web.dishes_detail(date_from_d.isoformat(), date_to_d.isoformat())
    # rows: dish_id, dish_name, category, product_type, quantity, revenue, cost_sum
    # MODIFIER (Доставка/В зале/С собой и платные добавки) — не блюда, в список не берём
    rows = [r for r in rows if r.get("product_type") != PRODUCT_TYPE_MODIFIER]

    # с/с по блюду: порционная с/с × количество (iiko-метрика по блюду ~0).
    # канал «доставка» — по принадлежности к категории «Доставка»; имя матчим как есть
    # (привязка несовпадающих имён POS↔ТТК — через DishMapping).
    # has_cost: нашлась ли порционная с/с (ТТК-привязка). Без неё с/с = 0 — НЕ выдаём
    # cost_pct/margin_pct (иначе блюдо выглядело бы как 100% маржа и искажало бы рейтинги).
    # галка «без доставки»: доставка = меню-категория «Доставка» ИЛИ имя с маркером `_д`
    # (get-data уже отдаёт категорию и имя) — просто убираем эти строки.
    if not include_delivery:
        rows = [r for r in rows if not is_delivery(r.get("category"), r.get("dish_name"))]

    unit_cost = _dish_unit_cost()
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
            cat = display_category(r.get("category") or "Без категории")
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

    Считаем УНИКАЛЬНЫЕ заказы (`OrderNum`) по каналу через OLAP — так сумма по типам
    равна реальному числу чеков (раньше суммировали кол-во модификаторов «Статус», и
    оно завышало итог, т.к. на заказ может приходиться больше одной «Статус»-строки).
    Канал заказа: модификатор «Статус» → иначе доставка по категории «Доставка»/маркеру
    `_д` → зал. При `include_delivery=false` доставочные заказы исключаются (галка).
    """
    date_from_d, date_to_d = period_range(period, date_from, date_to)

    rows = await iiko_web.olap_sales(
        group_fields=[
            OLAP_FIELD_ORDER_NUM,
            OLAP_FIELD_DISH_CATEGORY,
            OLAP_FIELD_DISH_NAME,
        ],
        data_fields=[OLAP_FIELD_QTY],
        date_from=date_from_d.isoformat(),
        date_to=date_to_d.isoformat(),
    )

    def _split(value: str) -> tuple[str, str, str]:
        parts = str(value).split(", ")
        if len(parts) < 3:
            return "", "", ""
        return parts[0], parts[1], ", ".join(parts[2:])

    order_channel: dict[str, str] = {}  # канал из «Статус»-строки заказа
    order_has_delivery: set[str] = set()  # в заказе есть позиция меню-категории «Доставка»
    orders: set[str] = set()  # все товарные заказы (по которым считаем чеки)
    for r in rows:
        order_num, category, name = _split(r.get("field0", {}).get("value", ""))
        if not order_num:
            continue
        if category == ORDER_STATUS_CATEGORY:
            ch = ORDER_STATUS_CHANNELS.get(name.strip().lower())
            if ch:
                order_channel[order_num] = ch
            continue
        if not name:
            continue
        orders.add(order_num)
        if is_delivery(category, name):
            order_has_delivery.add(order_num)

    counts = {CHANNEL_DINEIN: 0, CHANNEL_TAKEAWAY: 0, CHANNEL_DELIVERY: 0}
    for o in orders:
        ch = order_channel.get(o) or (
            CHANNEL_DELIVERY if o in order_has_delivery else CHANNEL_DINEIN
        )
        if not include_delivery and ch == CHANNEL_DELIVERY:
            continue  # галка «без доставки»: доставочные заказы не считаем
        counts[ch] += 1

    total = sum(counts.values())
    labels = {
        CHANNEL_DINEIN: "В зале",
        CHANNEL_TAKEAWAY: "С собой",
        CHANNEL_DELIVERY: "Доставка",
    }
    data = sorted(
        (
            {
                "type": labels[ch],
                "count": cnt,
                "share": round(cnt / total * 100, 1) if total else 0,
            }
            for ch, cnt in counts.items()
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
    include_delivery: bool = True,
):
    """Разбивка продаж по часам в разрезе блюд/категорий (#3, через OLAP iiko).

    Для каждого часового интервала — что и на сколько продавалось (понимание «когда что
    берут»). `get-data` такой разрез не умеет, поэтому используем OLAP SALES.
    """
    date_from_d, date_to_d = period_range(period, date_from, date_to)
    dim = OLAP_FIELD_DISH_CATEGORY if group == "category" else OLAP_FIELD_DISH_NAME

    mod_names, mod_cats = await _modifier_filters(date_from_d.isoformat(), date_to_d.isoformat())
    # В режиме блюд ВСЕГДА добавляем категорию в группировку: нужна и для отсева доставки,
    # и для drill-down «категория → её блюда» на фронте (каждый item несёт `category`).
    # В режиме категорий категория и есть измерение (доставку отсекаем по имени).
    with_cat = group == "dish"
    group_fields = (
        [OLAP_FIELD_HOUR, OLAP_FIELD_DISH_CATEGORY, dim] if with_cat else [OLAP_FIELD_HOUR, dim]
    )
    rows = await iiko_web.olap_sales(
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
    категории «Статус» на уровне ЗАКАЗА. Поэтому через OLAP SALES группируем по
    [номер заказа, категория, блюдо]: у каждого заказа из его «Статус»-строки берём канал
    и относим к нему все блюда заказа. Постфикс `_д` форсит «доставка» (заодно подстраховка,
    если у заказа нет «Статуса»).
    """
    date_from_d, date_to_d = period_range(period, date_from, date_to)

    _, mod_cats = await _modifier_filters(date_from_d.isoformat(), date_to_d.isoformat())
    rows = await iiko_web.olap_sales(
        group_fields=[
            OLAP_FIELD_ORDER_NUM,
            OLAP_FIELD_DISH_CATEGORY,
            OLAP_FIELD_DISH_NAME,
        ],
        data_fields=[OLAP_FIELD_QTY, OLAP_FIELD_SUM],
        date_from=date_from_d.isoformat(),
        date_to=date_to_d.isoformat(),
    )

    # field0 = "<OrderNum>, <Категория>, <Имя>". OrderNum и категория без запятых; имя
    # может содержать ", " — поэтому склеиваем хвост обратно.
    def _split(value: str) -> tuple[str, str, str]:
        parts = str(value).split(", ")
        if len(parts) < 3:
            return "", "", ""
        return parts[0], parts[1], ", ".join(parts[2:])

    # 1-й проход: канал каждого заказа из его строки категории «Статус»
    order_channel: dict[str, str] = {}
    for r in rows:
        order_num, category, name = _split(r.get("field0", {}).get("value", ""))
        if category == ORDER_STATUS_CATEGORY:
            ch = ORDER_STATUS_CHANNELS.get(name.strip().lower())
            if ch:
                order_channel[order_num] = ch

    # 2-й проход: канал блюда — по категории «Доставка»/маркеру `_д` (бизнес-правило),
    # иначе «Статус» заказа (по умолчанию зал).
    channels = (CHANNEL_DINEIN, CHANNEL_TAKEAWAY, CHANNEL_DELIVERY)
    agg: dict[str, dict] = {}
    for r in rows:
        order_num, category, name = _split(r.get("field0", {}).get("value", ""))
        # пропускаем «Статус» (он дал канал в 1-м проходе) и платные модификаторы — не блюда
        if not name or category == ORDER_STATUS_CATEGORY or category in mod_cats:
            continue
        qty = float(r.get("field1", {}).get("value", 0) or 0)
        rev = float(r.get("field2", {}).get("value", 0) or 0)
        if is_delivery(category, name):
            channel = CHANNEL_DELIVERY
        else:
            channel = order_channel.get(order_num, CHANNEL_DINEIN)
        key = (category or "Без категории") if group == "category" else name
        a = agg.setdefault(
            key,
            {"name": key, "total": 0.0, "revenue": 0.0, **{c: 0.0 for c in channels}},
        )
        a["total"] += qty
        a["revenue"] += rev
        a[channel] += qty

    result = sorted(agg.values(), key=lambda x: x["total"], reverse=True)
    for a in result:
        a["total"] = round(a["total"], 1)
        a["revenue"] = round(a["revenue"], 2)
        for c in channels:
            a[c] = round(a[c], 1)

    return {
        "group_by": group,
        "period": "custom" if (date_from and date_to) else period,
        "date_from": date_from_d.isoformat(),
        "date_to": date_to_d.isoformat(),
        "channels": list(channels),
        "data": result[:limit],
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
    """
    df, dt = period_range(period, date_from, date_to)
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
    _, mod_cats = await _modifier_filters(df.isoformat(), dt.isoformat())
    rows = await iiko_web.olap_sales(
        group_fields=[
            OLAP_FIELD_HOUR,
            OLAP_FIELD_ORDER_NUM,
            OLAP_FIELD_DISH_CATEGORY,
            OLAP_FIELD_DISH_NAME,
        ],
        data_fields=[OLAP_FIELD_QTY, OLAP_FIELD_SUM],
        date_from=df.isoformat(),
        date_to=dt.isoformat(),
    )
    # заказ → {категория: [qty, sum]}, заказ → час
    orders: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))
    order_hour: dict[str, str] = {}
    for r in rows:
        parts = str(r.get("field0", {}).get("value", "")).split(", ")
        if len(parts) < 4:
            continue
        hour, ordernum, category, name = (
            parts[0],
            parts[1],
            parts[2],
            ", ".join(parts[3:]),
        )
        # галка «без доставки»: доставка = категория «Доставка» ИЛИ имя с маркером `_д`
        if not include_delivery and is_delivery(category, name):
            continue
        if (
            not ordernum
            or not category
            or category in NON_PRODUCT_CATEGORIES
            or category in mod_cats
        ):
            continue
        category = display_category(category)  # отображаемое имя категории для вывода
        orders[ordernum][category][0] += float(r.get("field1", {}).get("value", 0) or 0)
        orders[ordernum][category][1] += float(r.get("field2", {}).get("value", 0) or 0)
        order_hour[ordernum] = hour

    def new_acc():
        return {"checks": 0, "cats": defaultdict(lambda: [0.0, 0.0])}

    total = new_acc()
    hourly: dict[str, dict] = defaultdict(new_acc)
    for ordernum, cats in orders.items():
        tq = sum(c[0] for c in cats.values())
        ts = sum(c[1] for c in cats.values())
        if tq <= 0:
            continue
        for bk in (total, hourly[order_hour.get(ordernum, "")]):
            bk["checks"] += 1
            for cat, (q, s) in cats.items():
                bk["cats"][cat][0] += q / tq
                bk["cats"][cat][1] += (s / ts) if ts else 0

    def fin(bk) -> dict:
        n = bk["checks"] or 1
        return {
            cat: {"qty": round(v[0] / n * 100, 1), "rev": round(v[1] / n * 100, 1)}
            for cat, v in bk["cats"].items()
        }

    cats_sorted = sorted(total["cats"], key=lambda c: total["cats"][c][0], reverse=True)
    hourly_out = []
    for hk in sorted((h for h in hourly if h.isdigit()), key=int):
        h = int(hk)
        hourly_out.append(
            {
                "hour": h,
                "label": f"{h:02d}-{h + 1:02d}",
                "checks": hourly[hk]["checks"],
                "by": fin(hourly[hk]),
            }
        )
    return {
        "period": "custom" if (date_from and date_to) else period,
        "date_from": df.isoformat(),
        "date_to": dt.isoformat(),
        "categories": cats_sorted,
        "total": {"checks": total["checks"], "by": fin(total)},
        "hourly": hourly_out,
    }


@router.get("/check-fullness")
async def get_check_fullness(
    period: str = Query("week", enum=["day", "week", "month"]),
    date_from: str | None = None,
    date_to: str | None = None,
    include_delivery: bool = True,
):
    """Распределение чеков по числу позиций (1 / 2 / 3 / 4+), по часам (#6).

    «Позиция» = проданная единица товара (сумма `qty` по товарным строкам заказа), а не
    число РАЗНЫХ блюд: заказ из двух одинаковых кофе — это чек на 2 позиции, а не на 1
    (иначе занижался бы апсейл-сигнал). Служебные/модификаторные категории не считаются.
    Дробный вес округляется до целого (минимум 1, если в чеке вообще есть товар).
    """
    df, dt = period_range(period, date_from, date_to)
    _, mod_cats = await _modifier_filters(df.isoformat(), dt.isoformat())
    rows = await iiko_web.olap_sales(
        group_fields=[
            OLAP_FIELD_HOUR,
            OLAP_FIELD_ORDER_NUM,
            OLAP_FIELD_DISH_CATEGORY,
            OLAP_FIELD_DISH_NAME,
        ],
        data_fields=[OLAP_FIELD_QTY],
        date_from=df.isoformat(),
        date_to=dt.isoformat(),
    )
    positions: dict[tuple[str, str], float] = defaultdict(float)
    for r in rows:
        parts = str(r.get("field0", {}).get("value", "")).split(", ")
        if len(parts) < 4:
            continue
        hour, ordernum, category, name = (
            parts[0],
            parts[1],
            parts[2],
            ", ".join(parts[3:]),
        )
        # галка «без доставки»: доставка = категория «Доставка» ИЛИ имя с маркером `_д`
        if not include_delivery and is_delivery(category, name):
            continue
        if not name or category in NON_PRODUCT_CATEGORIES or category in mod_cats:
            continue
        positions[(hour, ordernum)] += float(r.get("field1", {}).get("value", 0) or 0)

    buckets = ["1", "2", "3", "4+"]

    def bucket(n: int) -> str:
        return "4+" if n >= 4 else str(n)

    per_hour: dict[str, dict] = defaultdict(lambda: {b: 0 for b in buckets})
    total = {b: 0 for b in buckets}
    for (hour, _ordernum), qty_sum in positions.items():
        if qty_sum <= 0:
            continue
        b = bucket(max(1, round(qty_sum)))
        per_hour[hour][b] += 1
        total[b] += 1

    data = []
    for hk in sorted((h for h in per_hour if h.isdigit()), key=int):
        h = int(hk)
        row = {"hour": h, "label": f"{h:02d}-{h + 1:02d}", **per_hour[hk]}
        row["total"] = sum(per_hour[hk].values())
        data.append(row)
    return {
        "period": "custom" if (date_from and date_to) else period,
        "date_from": df.isoformat(),
        "date_to": dt.isoformat(),
        "buckets": buckets,
        "total": total,
        "data": data,
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
    """Матрица сочетаемости (market basket, #14): что чаще берут вместе в одном чеке.

    Для каждого заказа собираем множество позиций (категорий или блюд), считаем частоту
    совместной встречаемости пар в чеках. Возвращаем:
    - `labels`/`freq` — топ-N позиций по числу чеков (для осей матрицы);
    - `matrix[i][j]` — в скольких чеках встречались обе позиции i и j (диагональ = freq);
    - `pairs` — топ-пар по совместной встречаемости с долей чеков (`support`) и
      «уверенностью» (`confidence` = доля чеков с B среди чеков с A, по сильной позиции пары).
    Источник — OLAP SALES по `OrderNum`. Модификаторы/служебные категории исключены.
    """
    df, dt = period_range(period, date_from, date_to)
    _, mod_cats = await _modifier_filters(df.isoformat(), dt.isoformat())
    rows = await iiko_web.olap_sales(
        group_fields=[
            OLAP_FIELD_ORDER_NUM,
            OLAP_FIELD_DISH_CATEGORY,
            OLAP_FIELD_DISH_NAME,
        ],
        data_fields=[OLAP_FIELD_QTY],
        date_from=df.isoformat(),
        date_to=dt.isoformat(),
    )

    order_labels: dict[str, set[str]] = defaultdict(set)
    for r in rows:
        parts = str(r.get("field0", {}).get("value", "")).split(", ")
        if len(parts) < 3:
            continue
        ordernum, category, name = parts[0], parts[1], ", ".join(parts[2:])
        if not include_delivery and is_delivery(category, name):
            continue
        if not name or category in NON_PRODUCT_CATEGORIES or category in mod_cats:
            continue
        order_labels[ordernum].add(display_category(category) if group == "category" else name)

    total_orders = len(order_labels)
    freq: Counter[str] = Counter()
    pair_counts: Counter[tuple[str, str]] = Counter()
    for labels in order_labels.values():
        for lbl in labels:
            freq[lbl] += 1
        for a, b in combinations(sorted(labels), 2):
            pair_counts[(a, b)] += 1

    top_labels = [lbl for lbl, _ in freq.most_common(max(1, top))]
    idx = {lbl: i for i, lbl in enumerate(top_labels)}
    n = len(top_labels)
    matrix = [[0] * n for _ in range(n)]
    for i, lbl in enumerate(top_labels):
        matrix[i][i] = freq[lbl]
    for (a, b), c in pair_counts.items():
        if a in idx and b in idx:
            matrix[idx[a]][idx[b]] = c
            matrix[idx[b]][idx[a]] = c

    pairs = []
    for (a, b), c in pair_counts.most_common(15):
        strong, weak = (a, b) if freq[a] >= freq[b] else (b, a)
        pairs.append(
            {
                "a": strong,
                "b": weak,
                "count": c,
                "support": round(c / total_orders * 100, 1) if total_orders else 0,
                "confidence": round(c / freq[strong] * 100, 1) if freq[strong] else 0,
            }
        )

    return {
        "period": "custom" if (date_from and date_to) else period,
        "date_from": df.isoformat(),
        "date_to": dt.isoformat(),
        "group_by": group,
        "orders": total_orders,
        "labels": top_labels,
        "freq": [freq[lbl] for lbl in top_labels],
        "matrix": matrix,
        "pairs": pairs,
    }
