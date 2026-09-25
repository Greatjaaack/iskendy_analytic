"""Роутер выручки: по дням (из БД либо живой за произвольный диапазон) и по часам."""

import asyncio
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from constants import (
    CATEGORY_GROUP_ORDER,
    CHANNEL_DELIVERY,
    CHANNEL_DINEIN,
    CHANNEL_TAKEAWAY,
    DAY_NAMES_RU,
    DAYPARTS,
    OLAP_FIELD_COST,
    OLAP_FIELD_DISH_CATEGORY,
    OLAP_FIELD_DISH_NAME,
    OLAP_FIELD_GUESTS,
    OLAP_FIELD_HOUR,
    OLAP_FIELD_OPEN_DATE,
    OLAP_FIELD_ORDER_NUM,
    OLAP_FIELD_QTY,
    OLAP_FIELD_SUM,
    ORDER_STATUS_CATEGORY,
    ORDER_STATUS_CHANNELS,
    PAYMENT_GROUP_ORDER,
    WEEKDAY_TO_GROUP,
)
from models import DaypartPlan, Order, OrderItem, OrderPayment, RevenueDaily, SessionLocal
from pos import get_pos
from services.aggregator import net_revenue
from services.daypart import category_group, hour_to_daypart
from services.delivery import delivery_buckets, exclude_delivery
from services.olap_parse import order_group_fields, split_field_5, split_order_row
from services.ops_aggregation import (
    blank_bucket,
    finalize,
    finalize_cat,
    period_plan,
    plan_pct,
)
from services.order_store import order_rows, stored_covers
from utils import (
    is_delivery,
    payment_group,
    period_range,
    prev_period_range,
    stronger_channel,
    today,
)
from weather import get_weather

CHANNELS = (CHANNEL_DINEIN, CHANNEL_TAKEAWAY, CHANNEL_DELIVERY)


def _channel_revenue(rows: list[dict], bucket_field: str) -> dict[str, dict[str, float]]:
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


router = APIRouter(prefix="/api/revenue", tags=["revenue"])


def _daterange(start: date, end: date):
    """Дни периода включительно."""
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


def _ru_dow(d: date) -> str:
    """Русское сокращение дня недели для даты."""
    return DAY_NAMES_RU[d.weekday()]


def _day_dict(d: date, total, checks, avg, disc, refunds, cost) -> dict:
    total = float(total or 0)
    cost = float(cost or 0)
    return {
        "date": d.isoformat(),
        "day_of_week": _ru_dow(d),
        "total_sum": total,
        "discount_sum": float(disc or 0),
        "refund_count": int(refunds or 0),
        "cost_sum": round(cost, 2),
        "check_count": int(checks or 0),
        "avg_check": round(float(avg or 0), 2),
        "food_cost_pct": round(cost / total * 100, 1) if total else 0,
    }


def _days_from_db(date_from: date, date_to: date) -> list[dict]:
    with SessionLocal() as db:
        rows = (
            db.execute(
                select(RevenueDaily)
                .where(RevenueDaily.date >= date_from, RevenueDaily.date <= date_to)
                .order_by(RevenueDaily.date)
            )
            .scalars()
            .all()
        )
        # food cost — единый iiko-кост позиций (order_items.cost = ProductCostBase),
        # суммарно по дню. Fallback на revenue_daily.cost_sum (теоретич. расход iiko),
        # если позиционный кост за день пуст (день вне окна бэкафилла) — чтобы P&L и
        # food cost не обнулялись на неполных данных.
        item_cost = dict(
            db.execute(
                select(OrderItem.date, func.sum(OrderItem.cost))
                .where(OrderItem.date >= date_from, OrderItem.date <= date_to)
                .group_by(OrderItem.date)
            ).all()
        )
    return [
        _day_dict(
            r.date,
            r.total_sum,
            r.check_count,
            r.avg_check,
            r.discount_sum,
            r.refund_count,
            item_cost.get(r.date) or r.cost_sum,
        )
        for r in rows
    ]


def _days_from_items(date_from: date, date_to: date) -> list[dict]:
    """Дни периода, собранные из позиций заказов (`order_items`).

    Нужны там, где `revenue_daily` пуст, а заказы есть: сводка по дням синкается только
    за последний месяц, а позиции — за всю историю (бэкафилл). Раньше такие периоды
    уходили живым запросом в кассу — 8,4 секунды на месяц и полная зависимость от её
    доступности, хотя данные лежали в двух таблицах рядом.

    Числа те же, что в сводке: выручка — сумма позиций без служебных строк («Статус»),
    чек — заказ с хотя бы одной товарной позицией (номер уникален внутри дня), скидка —
    разница брутто и нетто. Возвратов в позициях нет, поэтому 0.
    """
    товарные = OrderItem.category != ORDER_STATUS_CATEGORY
    window = (OrderItem.date >= date_from, OrderItem.date <= date_to)
    with SessionLocal() as db:
        sums = db.execute(
            select(
                OrderItem.date,
                func.sum(OrderItem.sum),
                func.sum(OrderItem.net),
                func.sum(OrderItem.cost),
            )
            .where(*window, товарные)
            .group_by(OrderItem.date)
        ).all()
        checks = dict(
            db.execute(
                select(OrderItem.date, func.count(func.distinct(OrderItem.order_num)))
                .where(*window, товарные)
                .group_by(OrderItem.date)
            ).all()
        )
    days = []
    for day, gross, net, cost in sums:
        gross = float(gross or 0)
        count = int(checks.get(day, 0))
        days.append(
            _day_dict(
                day,
                gross,
                count,
                gross / count if count else 0,
                max(0.0, gross - float(net or 0)),
                0,
                cost,
            )
        )
    return days


async def _days_live(date_from: date, date_to: date) -> list[dict]:
    """Живой запрос сводки по дням у кассы (для произвольного диапазона вне БД)."""
    days = await get_pos().revenue_days(date_from, date_to)
    return [
        _day_dict(
            d.date,
            d.revenue,
            d.checks,
            d.avg_check,
            d.discount_sum,
            d.refund_count,
            d.cost_sum,
        )
        for d in days
    ]


def _history_start() -> date | None:
    """Первый день, о котором в БД вообще что-то есть (сводка или позиции)."""
    with SessionLocal() as db:
        starts = [
            db.execute(select(func.min(RevenueDaily.date))).scalar(),
            db.execute(select(func.min(OrderItem.date))).scalar(),
        ]
    known = [d for d in starts if d]
    return min(known) if known else None


async def days_stored_or_live(df: date, dt: date) -> list[dict]:
    """Дни периода: из БД, насколько она их покрывает; живой запрос — только за пределами.

    Источники по порядку: `revenue_daily` (сводка, синкается за месяц) → `order_items`
    (позиции, есть за всю историю) → живая касса. Раньше признаком был `is_custom`:
    любой выбор дат календарём уходил в кассу, даже когда все дни лежали в БД. Это
    стоило 8,4 секунды на `/api/pnl` за месяц (против 0,36 с из БД) и делало календарь
    заложником доступности кассы. Тот же путь нужен и для ПРОШЛОГО периода в KPI-дельтах:
    прошлый месяц почти всегда за окном сводки, но внутри истории позиций.

    Пробелы ВНУТРИ истории живым запросом не добираем: день без заказов — это закрытый
    день (у точки таких семь за год), и касса вернёт по нему те же нули.
    """
    days = _days_from_db(df, dt)
    have = {d["date"] for d in days}

    gaps = [d for d in _daterange(df, dt) if d.isoformat() not in have]
    if gaps:
        from_items = await asyncio.to_thread(_days_from_items, min(gaps), max(gaps))
        days += [d for d in from_items if d["date"] not in have]
        have = {d["date"] for d in days}
        gaps = [d for d in _daterange(df, dt) if d.isoformat() not in have]

    start = _history_start()
    # дни старше сохранённой истории — их в БД нет и не будет, только касса их помнит
    before_history = [d for d in gaps if start is None or d < start]
    if before_history:
        live = await _days_live(min(before_history), max(before_history))
        days += [d for d in live if d["date"] not in have]

    return sorted(days, key=lambda d: d["date"])


async def _load_days(df: date, dt: date, is_custom: bool) -> list[dict]:
    """Дни периода для дашборда: `days_stored_or_live` + страховка на «сегодня».

    Сегодня держит в БД частый синк (`sync_today`), но в первые минуты после полуночи
    его там ещё нет — тогда добираем день живым запросом.
    """
    days = await days_stored_or_live(df, dt)
    have = {d["date"] for d in days}
    if dt >= today() and today().isoformat() not in have:
        live_today = await _days_live(today(), today())
        days = sorted(days + live_today, key=lambda d: d["date"])
    return days


@router.get("")
async def get_revenue(
    period: str = Query("week", enum=["day", "week", "month"]),
    date_from: str | None = None,
    date_to: str | None = None,
    include_delivery: bool = True,
):
    df, dt = period_range(period, date_from, date_to)
    is_custom = bool(date_from and date_to)
    days = await _load_days(df, dt, is_custom)

    # галка «без доставки»: вычитаем выручку/чеки доставки (OLAP) из REV_GROSS-дней
    if not include_delivery:
        exclude_delivery(days, await delivery_buckets(df, dt, OLAP_FIELD_OPEN_DATE))

    # погода по Москве за те же дни (не критично — при сбое просто не покажем)
    weather = await get_weather(df.isoformat(), dt.isoformat())
    for d in days:
        d["weather"] = weather.get(d["date"])

    total = sum(r["total_sum"] for r in days)
    total_checks = sum(r["check_count"] for r in days)
    total_cost = sum(r["cost_sum"] for r in days)

    # ОСНОВНАЯ метрика — чистая выручка (после комиссии агрегатора): то, что реально
    # упало в карман. Комиссия вычитается только из агрегаторской части (зал не трогаем).
    # Без доставки агрегаторская часть уже убрана из total → комиссии нет.
    if include_delivery:
        net, agg_rev, commission = net_revenue(total, df, dt)
    else:
        net, agg_rev, commission = total, 0.0, 0.0

    # предыдущий сопоставимый период — для дельт. Месяц (MTD) сравнивается с тем же
    # отрезком прошлого месяца, день/неделя/диапазон — со скользящим окном (см. хелпер).
    # Берём из БД (быстро); если истории нет, дельта по этому показателю просто скрыта.
    prev_df, prev_dt = prev_period_range(period, df, dt, is_custom)
    # тот же путь, что у текущего периода: сводка → позиции → касса. Для «месяца»
    # прошлый период (31–60 дн. назад) за окном сводки, но внутри истории позиций —
    # раньше это означало живой запрос в кассу на каждое открытие дашборда.
    prev_days = await days_stored_or_live(prev_df, prev_dt)
    # без доставки — вычитаем её и из прошлого периода, чтобы дельта сравнивала сопоставимое
    if not include_delivery and prev_days:
        exclude_delivery(prev_days, await delivery_buckets(prev_df, prev_dt, OLAP_FIELD_OPEN_DATE))
    prev_rev = sum(r["total_sum"] for r in prev_days)
    prev_checks = sum(r["check_count"] for r in prev_days)
    # чистая выручка прошлого периода — для сопоставимых дельт (та же база, что у текущего)
    if include_delivery and prev_days:
        prev_net, _, _ = net_revenue(prev_rev, prev_df, prev_dt)
    else:
        prev_net = prev_rev

    # прошлый период, выровненный по позиции дня (для сравнения выручка×погода)
    prev_weather = await get_weather(prev_df.isoformat(), prev_dt.isoformat())
    prev_map = {r["date"]: r for r in prev_days}
    prev_data = []
    for i in range(len(days)):
        pd = (prev_df + timedelta(days=i)).isoformat()
        pm = prev_map.get(pd)
        pw = prev_weather.get(pd)
        prev_data.append(
            {
                "date": pd,
                "total_sum": pm["total_sum"] if pm else None,
                "temp_max": pw.get("temp_max") if pw else None,
            }
        )

    return {
        "period": "custom" if is_custom else period,
        "date_from": df.isoformat(),
        "date_to": dt.isoformat(),
        "summary": {
            # total_revenue — ОСНОВНАЯ (чистая, после комиссии). Все производные (ср.
            # чек, food cost %) считаются от неё. Сырая и агрегатор — рядом, для контекста.
            "total_revenue": round(net, 2),
            "gross_revenue": round(total, 2),
            "aggregator_revenue": round(agg_rev, 2),
            "aggregator_commission": round(commission, 2),
            "avg_daily_revenue": round(net / len(days), 2) if days else 0,
            "total_checks": total_checks,
            "avg_check": round(net / total_checks, 2) if total_checks else 0,
            "total_cost": round(total_cost, 2),
            "food_cost_pct": round(total_cost / net * 100, 1) if net else 0,
            # значения прошлого периода (None — если истории нет, тогда дельту не показываем)
            "prev": {
                "total_revenue": round(prev_net, 2) if prev_days else None,
                "total_checks": prev_checks if prev_days else None,
                "avg_check": round(prev_net / prev_checks, 2) if prev_checks else None,
            },
        },
        "data": days,
        "prev_data": prev_data,
    }


@router.get("/by-weekday")
async def get_revenue_by_weekday(
    period: str = Query("week", enum=["day", "week", "month"]),
    date_from: str | None = None,
    date_to: str | None = None,
    include_delivery: bool = True,
):
    """Свод выручки по дням недели за период: суммируем дни одного дня недели (Пн…Вс).

    На каждый день недели: сколько таких дней попало в период, суммарная и средняя
    выручка за день, чеки и средний чек. Источник тот же, что у `/api/revenue`
    (произвольный диапазон → живой запрос, пресет → из БД).
    """
    df, dt = period_range(period, date_from, date_to)
    is_custom = bool(date_from and date_to)
    days = await _load_days(df, dt, is_custom)

    # food cost считаем от полной выручки дня (с/с по каналам не делится) — фиксируем до вычета
    full_rev = {d["date"]: d["total_sum"] for d in days}
    if not include_delivery:
        exclude_delivery(days, await delivery_buckets(df, dt, OLAP_FIELD_OPEN_DATE))

    agg: dict[int, dict] = {
        i: {"revenue": 0.0, "checks": 0, "cost": 0.0, "days": 0, "full_rev": 0.0} for i in range(7)
    }
    for d in days:
        idx = date.fromisoformat(d["date"]).weekday()
        a = agg[idx]
        a["revenue"] += d["total_sum"]
        a["checks"] += d["check_count"]
        a["cost"] += d["cost_sum"]
        a["full_rev"] += full_rev[d["date"]]
        a["days"] += 1

    data = []
    for i in range(7):
        a = agg[i]
        if not a["days"]:  # нет такого дня недели в периоде — не показываем строку
            continue
        rev = a["revenue"]
        data.append(
            {
                "weekday": DAY_NAMES_RU[i],
                "days": a["days"],
                "revenue": round(rev, 2),
                "avg_day_revenue": round(rev / a["days"], 2),
                "checks": a["checks"],
                "avg_check": round(rev / a["checks"], 2) if a["checks"] else 0,
                "food_cost_pct": (
                    round(a["cost"] / a["full_rev"] * 100, 1) if a["full_rev"] else 0
                ),
            }
        )

    return {
        "period": "custom" if is_custom else period,
        "date_from": df.isoformat(),
        "date_to": dt.isoformat(),
        "data": data,
    }


def _hours_from_db(df: date, dt: date) -> tuple[dict[int, float], dict[int, int]]:
    """Выручка и чеки по часам суток из таблицы `orders`.

    Час берём по **закрытию** заказа, а не по открытию: именно так считает iiko, и это
    проверено на боевых данных за 01–20.09.2026 — все 12 часов сошлись с ответом кассы
    до рубля и до чека, тогда как по часу открытия расхождение было 1–2 % в каждом часе
    (чек, открытый в 10:59 и закрытый в 11:01, у кассы попадает в 11). У этой точки заказы
    короткие (в среднем 0,6 минуты), поэтому расхождение и было небольшим — но оно было.

    Если время закрытия не записано, используем час открытия (`orders.hour`).
    """
    rev: dict[int, float] = {}
    trn: dict[int, int] = {}
    with SessionLocal() as db:
        rows = db.execute(
            select(Order.hour, Order.close_time, Order.total_sum).where(
                Order.date >= df, Order.date <= dt
            )
        ).all()
    for open_hour, close_time, total in rows:
        hour = open_hour
        if close_time:
            try:
                hour = datetime.fromisoformat(str(close_time)).hour
            except ValueError:
                pass
        if hour is None:
            continue
        rev[hour] = round(rev.get(hour, 0.0) + float(total or 0), 2)
        trn[hour] = trn.get(hour, 0) + 1
    return rev, trn


async def _hours(df: date, dt: date) -> tuple[dict[int, float], dict[int, int]]:
    """Выручка и чеки по часам суток за период: {час: выручка}, {час: чеки}.

    Из БД, если период покрыт сохранёнными заказами; иначе — живой почасовой разрез
    кассы. Раньше ходили в кассу всегда, хотя те же заказы лежат в БД.
    """
    if stored_covers(Order, df.isoformat(), dt.isoformat()):
        return await asyncio.to_thread(_hours_from_db, df, dt)
    hours = await get_pos().hourly(df, dt)
    rev = {h: v.revenue for h, v in hours.items()}
    trn = {h: v.checks for h, v in hours.items()}
    return rev, trn


@router.get("/hourly")
async def get_hourly(
    period: str = Query("week", enum=["day", "week", "month"]),
    date_from: str | None = None,
    date_to: str | None = None,
    include_delivery: bool = True,
):
    """Продажи по часам (интервалы 11-12, 12-13, …) — почасовой разрез кассы."""
    df, dt = period_range(period, date_from, date_to)

    rev, trn = await _hours(df, dt)

    hours = sorted(set(rev) | set(trn))
    data = [
        {
            "hour": h,
            "label": f"{h:02d}-{h + 1:02d}",
            "revenue": round(rev.get(h, 0) or 0, 2),
            "checks": int(trn.get(h, 0) or 0),
            "avg_check": (round((rev.get(h, 0) or 0) / trn.get(h, 0), 2) if trn.get(h) else 0),
        }
        for h in hours
    ]

    # галка «без доставки»: вычитаем выручку/чеки доставки по каждому часу (OLAP)
    if not include_delivery:
        del_h = await delivery_buckets(df, dt, OLAP_FIELD_HOUR)
        for row in data:
            dd = del_h.get(str(row["hour"]))
            if not dd:
                continue
            row["revenue"] = round(max(0.0, row["revenue"] - dd["revenue"]), 2)
            row["checks"] = max(0, row["checks"] - dd["checks"])
            row["avg_check"] = round(row["revenue"] / row["checks"], 2) if row["checks"] else 0

    return {
        "period": period,
        "date_from": df.isoformat(),
        "date_to": dt.isoformat(),
        "data": data,
    }


@router.get("/by-daypart")
async def get_by_daypart(
    period: str = Query("week", enum=["day", "week", "month"]),
    date_from: str | None = None,
    date_to: str | None = None,
    include_delivery: bool = True,
):
    """Выручка/чеки/средний чек по дейпартам (Завтрак/Ланч/Полдник/Ужин/Ночь).

    Источник — почасовой разрез кассы, свёрнутый в операционные окна (границы — в
    `DAYPARTS`). При `include_delivery=false` вычитаем выручку/чеки доставки по
    каждому часу до свёртки — как в `/hourly`.
    """
    df, dt = period_range(period, date_from, date_to)

    rev, trn = await _hours(df, dt)

    if not include_delivery:
        del_h = await delivery_buckets(df, dt, OLAP_FIELD_HOUR)
        for hk, dd in del_h.items():
            if not hk.isdigit():
                continue
            h = int(hk)
            rev[h] = max(0.0, rev.get(h, 0) - dd["revenue"])
            trn[h] = max(0, trn.get(h, 0) - dd["checks"])

    total_rev = sum(v for v in rev.values() if v)
    data = []
    for dp in DAYPARTS:
        r = sum(rev.get(h, 0) or 0 for h in dp["hours"])
        c = sum(trn.get(h, 0) or 0 for h in dp["hours"])
        data.append(
            {
                "key": dp["key"],
                "label": dp["label"],
                "range": dp["range"],
                "revenue": round(r, 2),
                "checks": int(c),
                "avg_check": round(r / c, 2) if c else 0,
                "revenue_share": round(r / total_rev * 100, 1) if total_rev else 0,
            }
        )

    return {
        "period": "custom" if (date_from and date_to) else period,
        "date_from": df.isoformat(),
        "date_to": dt.isoformat(),
        "data": data,
    }


@router.get("/ops-report")
async def get_ops_report(
    period: str = Query("month", enum=["day", "week", "month"]),
    date_from: str | None = None,
    date_to: str | None = None,
    include_delivery: bool = True,
):
    """Ежедневный операционный отчёт: дни (столбцы) × дейпарты (строки).

    Аналог исторического Excel-свода «Ежедневный ОП». По каждому дню × дейпарту —
    выручка, чеки, гости (`GuestNum`), средний чек и food cost % (iiko-с/с позиций
    `ProductCostBase` ÷ выручка окна). Справа — Факт (сумма за период), Среднее (на
    активный день) и доля % дейпарта. Один OLAP-запрос по [дата, час, заказ, категория,
    имя] + DishSumInt/Qty/GuestNum/ProductCost.
    План пока не показываем (нет источника в iiko). `include_delivery=false` — отсев
    доставочных позиций (`utils.is_delivery`).
    """
    df, dt = period_range(period, date_from, date_to)

    rows = await order_rows(
        group_fields=[
            OLAP_FIELD_OPEN_DATE,
            OLAP_FIELD_HOUR,
            OLAP_FIELD_ORDER_NUM,
            OLAP_FIELD_DISH_CATEGORY,
            OLAP_FIELD_DISH_NAME,
        ],
        data_fields=[OLAP_FIELD_SUM, OLAP_FIELD_QTY, OLAP_FIELD_GUESTS, OLAP_FIELD_COST],
        date_from=df.isoformat(),
        date_to=dt.isoformat(),
    )

    h2dp = hour_to_daypart()
    # накопитель: (дата, ключ дейпарта) → bucket
    agg: dict[tuple[str, str], dict] = {}
    # food cost по группам категорий (Еда/Напитки/Алкоголь) на дейпарт — нижний блок свода
    cat_agg: dict[tuple[str, str], dict] = (
        {}
    )  # (ключ дейпарта, группа) → {revenue,cost,rev_with_cost}

    for r in rows:
        ds, hs, ordernum, category, name = split_field_5(r.get("field0", {}).get("value", ""))
        if not name or category == ORDER_STATUS_CATEGORY:
            continue
        if not include_delivery and is_delivery(category, name):
            continue
        try:
            hour = int(hs)
        except ValueError:
            continue
        dp = h2dp.get(hour)
        if dp is None:
            continue
        rev = float(r.get("field1", {}).get("value", 0) or 0)
        guests = float(r.get("field3", {}).get("value", 0) or 0)
        cost = float(r.get("field4", {}).get("value", 0) or 0)
        key = (ds, dp)
        b = agg.get(key)
        if b is None:
            b = agg[key] = blank_bucket()
        b["revenue"] += rev
        b["orders"].add(ordernum)
        b["guests"].setdefault(ordernum, guests)
        # группа категории для food cost (дейпарт × Еда/Напитки/Алкоголь)
        ck = (dp, category_group(category))
        cb = cat_agg.get(ck)
        if cb is None:
            cb = cat_agg[ck] = {"revenue": 0.0, "cost": 0.0, "rev_with_cost": 0.0}
        cb["revenue"] += rev
        # food cost % считаем от ВСЕЙ выручки окна (честный P&L-знаменатель, сходится
        # с P&L). rev_with_cost копит только прокостованную выручку (cost>0) → coverage
        # показывает дыру: у доставочных дублей («…доставка»/«_д») iiko не ставит
        # ProductCostBase, поэтому на окнах с доставкой coverage < 100%.
        b["cost"] += cost
        cb["cost"] += cost
        if cost > 0:
            b["rev_with_cost"] += rev
            cb["rev_with_cost"] += rev

    # столбцы — все календарные дни периода
    days = []
    d = df
    while d <= dt:
        days.append(
            {
                "date": d.isoformat(),
                "dom": d.day,
                "weekday": DAY_NAMES_RU[d.weekday()],
            }
        )
        d += timedelta(days=1)
    day_keys = [x["date"] for x in days]

    # число дней каждой группы дня недели в периоде — для масштабирования плана
    group_day_count: dict[str, int] = {}
    for x in days:
        grp = WEEKDAY_TO_GROUP.get(date.fromisoformat(x["date"]).weekday())
        if grp:
            group_day_count[grp] = group_day_count.get(grp, 0) + 1
    total_days = len(days)
    with SessionLocal() as db:
        plan_rows = {
            (r.daypart_key, r.weekday_group): r for r in db.execute(select(DaypartPlan)).scalars()
        }
    has_plan = any((r.revenue or 0) for r in plan_rows.values())

    grand_revenue = sum(b["revenue"] for b in agg.values()) or 0.0

    dayparts = []
    for dp in DAYPARTS:
        cells = {}
        tot = blank_bucket()
        active = 0
        for dk in day_keys:
            b = agg.get((dk, dp["key"]))
            if b is None:
                continue
            cells[dk] = finalize(b)
            if b["revenue"] > 0 or b["orders"]:
                active += 1
            # копим в total
            tot["revenue"] += b["revenue"]
            tot["cost"] += b["cost"]
            tot["rev_with_cost"] += b["rev_with_cost"]
            tot["orders"] |= b["orders"]
            for on, g in b["guests"].items():
                tot["guests"].setdefault((dk, on), g)
        total = finalize(tot)
        # Среднее — на активный день (как в Excel «Среднее»)
        avg_per_day = {
            "revenue": round(total["revenue"] / active, 2) if active else 0,
            "checks": round(total["checks"] / active, 1) if active else 0,
            "guests": round(total["guests"] / active, 1) if active else 0,
            "avg_check": total["avg_check"],
        }
        # food cost по группам категорий внутри дейпарта (Еда/Напитки/Алкоголь)
        cats = {}
        for grp in CATEGORY_GROUP_ORDER:
            cb = cat_agg.get((dp["key"], grp))
            if cb and cb["revenue"] > 0:
                cats[grp] = finalize_cat(cb, total["revenue"])
        dp_plan = period_plan(plan_rows, dp["key"], group_day_count, total_days)
        dayparts.append(
            {
                "key": dp["key"],
                "label": dp["label"],
                "range": dp["range"],
                "cells": cells,
                "total": total,
                "avg_per_day": avg_per_day,
                "active_days": active,
                "revenue_share": (
                    round(total["revenue"] / grand_revenue * 100, 1) if grand_revenue else 0
                ),
                "categories": cats,
                "plan": dp_plan,
                "plan_pct": plan_pct(total, dp_plan),
            }
        )

    # строка Итого — сумма по всем дейпартам в каждый день
    tot_cells = {}
    grand = blank_bucket()
    active_total = 0
    for dk in day_keys:
        acc = blank_bucket()
        has = False
        for dp in DAYPARTS:
            b = agg.get((dk, dp["key"]))
            if b is None:
                continue
            has = True
            acc["revenue"] += b["revenue"]
            acc["cost"] += b["cost"]
            acc["rev_with_cost"] += b["rev_with_cost"]
            acc["orders"] |= b["orders"]
            for on, g in b["guests"].items():
                acc["guests"].setdefault(on, g)
        if has:
            tot_cells[dk] = finalize(acc)
            active_total += 1
            grand["revenue"] += acc["revenue"]
            grand["cost"] += acc["cost"]
            grand["rev_with_cost"] += acc["rev_with_cost"]
            grand["orders"] |= acc["orders"]
            for on, g in acc["guests"].items():
                grand["guests"].setdefault((dk, on), g)
    grand_total = finalize(grand)
    # план на период по всей точке = сумма планов дейпартов
    grand_plan = {m: round(sum(dp["plan"][m] for dp in dayparts), 2) for m in ("revenue", "guests")}
    grand_plan["avg_check"] = (
        round(grand_plan["revenue"] / grand_plan["guests"], 2) if grand_plan["guests"] else 0
    )
    totals = {
        "cells": tot_cells,
        "total": grand_total,
        "avg_per_day": {
            "revenue": round(grand_total["revenue"] / active_total, 2) if active_total else 0,
            "checks": round(grand_total["checks"] / active_total, 1) if active_total else 0,
            "guests": round(grand_total["guests"] / active_total, 1) if active_total else 0,
            "avg_check": grand_total["avg_check"],
        },
        "plan": grand_plan,
        "plan_pct": plan_pct(grand_total, grand_plan),
    }

    # сводный блок food cost по группам категорий (нижний блок Excel-свода «ОП»)
    cat_total_acc: dict[str, dict] = {}
    for (_dpk, grp), cb in cat_agg.items():
        a = cat_total_acc.setdefault(grp, {"revenue": 0.0, "cost": 0.0, "rev_with_cost": 0.0})
        a["revenue"] += cb["revenue"]
        a["cost"] += cb["cost"]
        a["rev_with_cost"] += cb["rev_with_cost"]
    cat_grand_rev = sum(a["revenue"] for a in cat_total_acc.values()) or 0.0
    category_groups = [
        g for g in CATEGORY_GROUP_ORDER if cat_total_acc.get(g, {}).get("revenue", 0)
    ]
    category_totals = {g: finalize_cat(cat_total_acc[g], cat_grand_rev) for g in category_groups}

    return {
        "period": "custom" if (date_from and date_to) else period,
        "date_from": df.isoformat(),
        "date_to": dt.isoformat(),
        "days": days,
        "dayparts": dayparts,
        "totals": totals,
        "category_groups": category_groups,
        "category_totals": category_totals,
        "has_plan": has_plan,
    }


@router.get("/by-channel")
async def get_revenue_by_channel(
    period: str = Query("week", enum=["day", "week", "month"]),
    date_from: str | None = None,
    date_to: str | None = None,
    include_delivery: bool = True,
):
    """Выручка по дням в разрезе каналов (зал/с собой/доставка) — через OLAP SALES.

    При `include_delivery=false` канал «доставка» исключается из разреза (для галки
    «без доставки» в виджете «Чеки и выручка по типу обслуживания»).
    """
    df, dt = period_range(period, date_from, date_to)
    channels = [c for c in CHANNELS if include_delivery or c != CHANNEL_DELIVERY]
    rows = await order_rows(
        group_fields=order_group_fields(OLAP_FIELD_OPEN_DATE),
        data_fields=[OLAP_FIELD_SUM],
        date_from=df.isoformat(),
        date_to=dt.isoformat(),
    )
    buckets = _channel_revenue(rows, OLAP_FIELD_OPEN_DATE)
    data = []
    for ds in sorted(buckets):
        try:
            d = date.fromisoformat(ds)
        except ValueError:
            continue
        b = buckets[ds]
        row = {
            "date": ds,
            "day_of_week": _ru_dow(d),
            "total": round(sum(b[c] for c in channels), 2),
        }
        row.update({c: round(b[c], 2) for c in channels})
        data.append(row)
    return {
        "period": "custom" if (date_from and date_to) else period,
        "date_from": df.isoformat(),
        "date_to": dt.isoformat(),
        "channels": channels,
        "data": data,
    }


@router.get("/hourly-by-channel")
async def get_hourly_by_channel(
    period: str = Query("week", enum=["day", "week", "month"]),
    date_from: str | None = None,
    date_to: str | None = None,
):
    """Продажи по часам в разрезе каналов (зал/с собой/доставка) — через OLAP SALES."""
    df, dt = period_range(period, date_from, date_to)
    rows = await order_rows(
        group_fields=order_group_fields(OLAP_FIELD_HOUR),
        data_fields=[OLAP_FIELD_SUM],
        date_from=df.isoformat(),
        date_to=dt.isoformat(),
    )
    buckets = _channel_revenue(rows, OLAP_FIELD_HOUR)
    data = []
    for hk in sorted((h for h in buckets if h.isdigit()), key=int):
        h = int(hk)
        b = buckets[hk]
        row = {
            "hour": h,
            "label": f"{h:02d}-{h + 1:02d}",
            "total": round(sum(b.values()), 2),
        }
        row.update({c: round(b[c], 2) for c in CHANNELS})
        data.append(row)
    return {
        "period": "custom" if (date_from and date_to) else period,
        "date_from": df.isoformat(),
        "date_to": dt.isoformat(),
        "channels": list(CHANNELS),
        "data": data,
    }


@router.get("/kpi-by-channel")
async def get_kpi_by_channel(
    period: str = Query("week", enum=["day", "week", "month"]),
    date_from: str | None = None,
    date_to: str | None = None,
):
    """KPI (выручка/чеки/средний чек) в разрезе ДОСТАВКА vs НЕ ДОСТАВКА (зал + с собой).

    Канал заказа: доставка, если у заказа «Статус» = Доставка ИЛИ есть позиция из
    меню-категории «Доставка»; иначе — не доставка. Заказ опознаётся парой (дата, номер).
    """
    df, dt = period_range(period, date_from, date_to)
    rows = await order_rows(
        group_fields=order_group_fields(),
        data_fields=[OLAP_FIELD_SUM],
        date_from=df.isoformat(),
        date_to=dt.isoformat(),
    )

    order_rev: dict[str, float] = {}
    order_delivery: dict[str, bool] = {}
    for r in rows:
        order_num, _day, category, name = split_order_row(r.get("field0", {}).get("value", ""))
        if not order_num:
            continue
        if category == ORDER_STATUS_CATEGORY:
            if ORDER_STATUS_CHANNELS.get(name.strip().lower()) == CHANNEL_DELIVERY:
                order_delivery[order_num] = True
            continue
        if is_delivery(category, name):
            order_delivery[order_num] = True
        rev = float(r.get("field1", {}).get("value", 0) or 0)
        order_rev[order_num] = order_rev.get(order_num, 0.0) + rev
        order_delivery.setdefault(order_num, False)

    groups = {
        "delivery": {"revenue": 0.0, "checks": 0},
        "other": {"revenue": 0.0, "checks": 0},
    }
    for order_num, rev in order_rev.items():
        g = "delivery" if order_delivery.get(order_num) else "other"
        groups[g]["revenue"] += rev
        groups[g]["checks"] += 1
    for g in groups.values():
        g["avg_check"] = round(g["revenue"] / g["checks"], 2) if g["checks"] else 0
        g["revenue"] = round(g["revenue"], 2)

    return {
        "period": "custom" if (date_from and date_to) else period,
        "date_from": df.isoformat(),
        "date_to": dt.isoformat(),
        **groups,
    }


@router.get("/by-payment")
async def get_by_payment(
    period: str = Query("week", enum=["day", "week", "month"]),
    date_from: str | None = None,
    date_to: str | None = None,
    include_delivery: bool = True,
):
    """Структура выручки по способам оплаты (Карта/Наличные/Агрегатор) за период.

    Источник — `order_payments` (нормализованные оплаты, сплит-чек разложен на строки,
    Σ=выручке). Возвращает доли по выручке и чекам за период (`totals`) и стек по дням
    (`daily`) для тренда структуры. При `include_delivery=false` исключаются оплаты
    доставочных заказов (`orders.is_delivery`). Данные только из БД (для дат старше
    начала сохранённой истории оплат нет — вернётся пусто).
    """
    df, dt = period_range(period, date_from, date_to)

    with SessionLocal() as db:
        excluded: set[tuple] = set()
        if not include_delivery:
            for d, on in db.query(Order.date, Order.order_num).filter(
                Order.date >= df, Order.date <= dt, Order.is_delivery.is_(True)
            ):
                excluded.add((d, on))
        pays = (
            db.query(
                OrderPayment.date,
                OrderPayment.order_num,
                OrderPayment.pay_type,
                OrderPayment.amount,
            )
            .filter(OrderPayment.date >= df, OrderPayment.date <= dt)
            .all()
        )

    # агрегаты: сумма+уникальные чеки на группу; стек по дням; общий счётчик чеков
    group_amount: dict[str, float] = {}
    group_orders: dict[str, set] = {}
    daily: dict[str, dict[str, float]] = {}
    all_orders: set[tuple] = set()
    for d, on, pt, amt in pays:
        if (d, on) in excluded:
            continue
        g = payment_group(pt)
        a = float(amt or 0)
        group_amount[g] = group_amount.get(g, 0.0) + a
        group_orders.setdefault(g, set()).add((d, on))
        daily.setdefault(d.isoformat(), {})[g] = daily.setdefault(d.isoformat(), {}).get(g, 0.0) + a
        all_orders.add((d, on))

    # только реально встретившиеся группы, в фиксированном порядке
    groups = [g for g in PAYMENT_GROUP_ORDER if group_amount.get(g)]
    total_amount = sum(group_amount.values())
    total_checks = len(all_orders)

    totals = [
        {
            "group": g,
            "amount": round(group_amount[g], 2),
            "share": round(group_amount[g] / total_amount * 100, 1) if total_amount else 0,
            "checks": len(group_orders[g]),
            "check_share": (
                round(len(group_orders[g]) / total_checks * 100, 1) if total_checks else 0
            ),
        }
        for g in groups
    ]

    daily_out = [
        {"date": day, **{g: round(daily[day].get(g, 0.0), 2) for g in groups}}
        for day in sorted(daily)
    ]

    return {
        "period": "custom" if (date_from and date_to) else period,
        "date_from": df.isoformat(),
        "date_to": dt.isoformat(),
        "groups": groups,
        "totals": totals,
        "total_amount": round(total_amount, 2),
        "total_checks": total_checks,
        "daily": daily_out,
    }
