"""Роутер выручки: по дням (из БД либо живой за произвольный диапазон) и по часам."""

from datetime import date, timedelta

from fastapi import APIRouter, Query

from constants import (
    CHANNEL_DELIVERY,
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
)
from models import Order, OrderPayment, SessionLocal
from services.aggregator import net_revenue
from services.channels import CHANNELS, channel_revenue
from services.delivery import delivery_buckets, exclude_delivery
from services.olap_parse import order_group_fields, split_order_row
from services.ops_report import build_ops_report
from services.order_store import order_rows
from services.revenue_source import (
    days_stored_or_live,
    hours_for_period,
    load_days,
    ru_dow,
)
from utils import (
    is_delivery,
    payment_group,
    period_range,
    prev_period_range,
)
from weather import get_weather

router = APIRouter(prefix="/api/revenue", tags=["revenue"])


@router.get("")
async def get_revenue(
    period: str = Query("week", enum=["day", "week", "month"]),
    date_from: str | None = None,
    date_to: str | None = None,
    include_delivery: bool = True,
):
    df, dt = period_range(period, date_from, date_to)
    is_custom = bool(date_from and date_to)
    days = await load_days(df, dt, is_custom)

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
    days = await load_days(df, dt, is_custom)

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


@router.get("/hourly")
async def get_hourly(
    period: str = Query("week", enum=["day", "week", "month"]),
    date_from: str | None = None,
    date_to: str | None = None,
    include_delivery: bool = True,
):
    """Продажи по часам (интервалы 11-12, 12-13, …) — почасовой разрез кассы."""
    df, dt = period_range(period, date_from, date_to)

    rev, trn = await hours_for_period(df, dt)

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

    rev, trn = await hours_for_period(df, dt)

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

    Расчёт — в `services/ops_report.py`; здесь только период, один запрос разреза и
    добавление границ периода к ответу.
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
    отчёт = await build_ops_report(rows, df, dt, include_delivery)
    return {
        "period": "custom" if (date_from and date_to) else period,
        "date_from": df.isoformat(),
        "date_to": dt.isoformat(),
        **отчёт,
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
    buckets = channel_revenue(rows, OLAP_FIELD_OPEN_DATE)
    data = []
    for ds in sorted(buckets):
        try:
            d = date.fromisoformat(ds)
        except ValueError:
            continue
        b = buckets[ds]
        row = {
            "date": ds,
            "day_of_week": ru_dow(d),
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
    buckets = channel_revenue(rows, OLAP_FIELD_HOUR)
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
