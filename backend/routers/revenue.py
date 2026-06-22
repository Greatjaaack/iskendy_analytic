"""Роутер выручки: по дням (из БД либо живой за произвольный диапазон) и по часам."""

from datetime import date, timedelta

from fastapi import APIRouter, Query
from sqlalchemy import select

from constants import (
    CHANNEL_DELIVERY,
    CHANNEL_DINEIN,
    CHANNEL_TAKEAWAY,
    DAY_NAMES_RU,
    DELIVERY_CATEGORY,
    METRIC_AVG_SPEND,
    METRIC_COST,
    METRIC_DISCOUNT,
    METRIC_REFUNDS,
    METRIC_REV_GROSS,
    METRIC_TRN_ALL,
    OLAP_FIELD_DISH_CATEGORY,
    OLAP_FIELD_DISH_NAME,
    OLAP_FIELD_HOUR,
    OLAP_FIELD_OPEN_DATE,
    OLAP_FIELD_ORDER_NUM,
    OLAP_FIELD_SUM,
    ORDER_STATUS_CATEGORY,
    ORDER_STATUS_CHANNELS,
)
from iiko_web_client import iiko_web
from models import RevenueDaily, SessionLocal
from utils import period_range
from weather import get_weather

CHANNELS = (CHANNEL_DINEIN, CHANNEL_TAKEAWAY, CHANNEL_DELIVERY)


def _split4(value: str) -> tuple[str, str, str, str]:
    """field0 «bucket, OrderNum, Категория, Имя» → 4 части (имя может содержать ', ')."""
    parts = str(value).split(", ")
    if len(parts) < 4:
        return "", "", "", ""
    return parts[0], parts[1], parts[2], ", ".join(parts[3:])


def _channel_revenue(rows: list[dict]) -> dict[str, dict[str, float]]:
    """{bucket → {канал: выручка}}. bucket = 1-е group-поле (дата/час). Канал: категория
    «Доставка» → доставка; иначе «Статус» заказа (по умолчанию зал)."""
    order_channel: dict[str, str] = {}
    for r in rows:
        _b, ordernum, category, name = _split4(r.get("field0", {}).get("value", ""))
        if category == ORDER_STATUS_CATEGORY:
            ch = ORDER_STATUS_CHANNELS.get(name.strip().lower())
            if ch:
                order_channel[ordernum] = ch
    out: dict[str, dict[str, float]] = {}
    for r in rows:
        bucket, ordernum, category, name = _split4(r.get("field0", {}).get("value", ""))
        if not name or category == ORDER_STATUS_CATEGORY:
            continue
        rev = float(r.get("field1", {}).get("value", 0) or 0)
        ch = (
            CHANNEL_DELIVERY
            if category == DELIVERY_CATEGORY
            else order_channel.get(ordernum, CHANNEL_DINEIN)
        )
        out.setdefault(bucket, {c: 0.0 for c in CHANNELS})[ch] += rev
    return out


router = APIRouter(prefix="/api/revenue", tags=["revenue"])


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
    return [
        _day_dict(
            r.date,
            r.total_sum,
            r.check_count,
            r.avg_check,
            r.discount_sum,
            r.refund_count,
            r.cost_sum,
        )
        for r in rows
    ]


async def _days_live(date_from: date, date_to: date) -> list[dict]:
    """Живой запрос выручки по дням из iiko (для произвольного диапазона)."""
    data = await iiko_web.revenue_by_day(date_from.isoformat(), date_to.isoformat())

    def g(code, key):
        return data.get(code, {}).get(key)

    all_dates = set()
    for block in data.values():
        if isinstance(block, dict):
            all_dates.update(block.keys())

    days = []
    for ds in sorted(all_dates):
        try:
            d = date.fromisoformat(ds)
        except ValueError:
            continue
        days.append(
            _day_dict(
                d,
                g(METRIC_REV_GROSS, ds),
                g(METRIC_TRN_ALL, ds),
                g(METRIC_AVG_SPEND, ds),
                g(METRIC_DISCOUNT, ds),
                g(METRIC_REFUNDS, ds),
                g(METRIC_COST, ds),
            )
        )
    return days


@router.get("")
async def get_revenue(
    period: str = Query("week", enum=["day", "week", "month"]),
    date_from: str | None = None,
    date_to: str | None = None,
):
    df, dt = period_range(period, date_from, date_to)
    is_custom = bool(date_from and date_to)
    # произвольный диапазон → живой запрос (в БД может не быть истории); пресет → из БД
    days = await _days_live(df, dt) if is_custom else _days_from_db(df, dt)

    # погода по Москве за те же дни (не критично — при сбое просто не покажем)
    weather = await get_weather(df.isoformat(), dt.isoformat())
    for d in days:
        d["weather"] = weather.get(d["date"])

    total = sum(r["total_sum"] for r in days)
    total_checks = sum(r["check_count"] for r in days)
    total_cost = sum(r["cost_sum"] for r in days)

    # предыдущий аналогичный период (такой же длины, вплотную перед текущим) — для дельт.
    # Берём из БД (быстро); если истории нет, дельта по этому показателю просто скрыта.
    span = (dt - df).days
    prev_dt = df - timedelta(days=1)
    prev_df = prev_dt - timedelta(days=span)
    prev_days = _days_from_db(prev_df, prev_dt)
    # для «месяца» прошлый период (31–60 дн. назад) обычно не в БД (синк 30 дн.) —
    # тогда берём живым запросом, иначе дельта не показывалась бы
    if not prev_days:
        prev_days = await _days_live(prev_df, prev_dt)
    prev_rev = sum(r["total_sum"] for r in prev_days)
    prev_checks = sum(r["check_count"] for r in prev_days)

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
            "total_revenue": total,
            "avg_daily_revenue": round(total / len(days), 2) if days else 0,
            "total_checks": total_checks,
            "avg_check": round(total / total_checks, 2) if total_checks else 0,
            "total_cost": round(total_cost, 2),
            "food_cost_pct": round(total_cost / total * 100, 1) if total else 0,
            # значения прошлого периода (None — если истории нет, тогда дельту не показываем)
            "prev": {
                "total_revenue": prev_rev if prev_days else None,
                "total_checks": prev_checks if prev_days else None,
                "avg_check": round(prev_rev / prev_checks, 2) if prev_checks else None,
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
):
    """Свод выручки по дням недели за период: суммируем дни одного дня недели (Пн…Вс).

    На каждый день недели: сколько таких дней попало в период, суммарная и средняя
    выручка за день, чеки и средний чек. Источник тот же, что у `/api/revenue`
    (произвольный диапазон → живой запрос, пресет → из БД).
    """
    df, dt = period_range(period, date_from, date_to)
    is_custom = bool(date_from and date_to)
    days = await _days_live(df, dt) if is_custom else _days_from_db(df, dt)

    agg: dict[int, dict] = {
        i: {"revenue": 0.0, "checks": 0, "cost": 0.0, "days": 0} for i in range(7)
    }
    for d in days:
        idx = date.fromisoformat(d["date"]).weekday()
        a = agg[idx]
        a["revenue"] += d["total_sum"]
        a["checks"] += d["check_count"]
        a["cost"] += d["cost_sum"]
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
                "food_cost_pct": round(a["cost"] / rev * 100, 1) if rev else 0,
            }
        )

    return {
        "period": "custom" if is_custom else period,
        "date_from": df.isoformat(),
        "date_to": dt.isoformat(),
        "data": data,
    }


def _parse_hour_matrix(block: dict) -> dict[int, float]:
    """DATA_SUMMARY_BY_HOURS: rows={"D11":0,...}, data=[[по датам], ...].
    Возвращает {час: сумма по всем датам}."""
    rows = block.get("rows", {})
    data = block.get("data", [])
    out: dict[int, float] = {}
    for key, ri in rows.items():
        try:
            hour = int(str(key).lstrip("D"))
        except ValueError:
            continue
        row = data[ri] if ri < len(data) else []
        out[hour] = sum(v for v in row if v is not None)
    return out


@router.get("/hourly")
async def get_hourly(
    period: str = Query("week", enum=["day", "week", "month"]),
    date_from: str | None = None,
    date_to: str | None = None,
):
    """Продажи по часам (интервалы 11-12, 12-13, …) — живой запрос в iiko."""
    df, dt = period_range(period, date_from, date_to)

    raw = await iiko_web.revenue_by_hour(df.isoformat(), dt.isoformat())
    rev = _parse_hour_matrix(raw.get(METRIC_REV_GROSS, {}))
    trn = _parse_hour_matrix(raw.get(METRIC_TRN_ALL, {}))

    hours = sorted(set(rev) | set(trn))
    data = [
        {
            "hour": h,
            "label": f"{h:02d}-{h + 1:02d}",
            "revenue": round(rev.get(h, 0) or 0, 2),
            "checks": int(trn.get(h, 0) or 0),
            "avg_check": round((rev.get(h, 0) or 0) / trn.get(h, 0), 2) if trn.get(h) else 0,
        }
        for h in hours
    ]
    return {"period": period, "date_from": df.isoformat(), "date_to": dt.isoformat(), "data": data}


@router.get("/by-channel")
async def get_revenue_by_channel(
    period: str = Query("week", enum=["day", "week", "month"]),
    date_from: str | None = None,
    date_to: str | None = None,
):
    """Выручка по дням в разрезе каналов (зал/с собой/доставка) — через OLAP SALES."""
    df, dt = period_range(period, date_from, date_to)
    rows = await iiko_web.olap_sales(
        group_fields=[
            OLAP_FIELD_OPEN_DATE,
            OLAP_FIELD_ORDER_NUM,
            OLAP_FIELD_DISH_CATEGORY,
            OLAP_FIELD_DISH_NAME,
        ],
        data_fields=[OLAP_FIELD_SUM],
        date_from=df.isoformat(),
        date_to=dt.isoformat(),
    )
    buckets = _channel_revenue(rows)
    data = []
    for ds in sorted(buckets):
        try:
            d = date.fromisoformat(ds)
        except ValueError:
            continue
        b = buckets[ds]
        row = {"date": ds, "day_of_week": _ru_dow(d), "total": round(sum(b.values()), 2)}
        row.update({c: round(b[c], 2) for c in CHANNELS})
        data.append(row)
    return {
        "period": "custom" if (date_from and date_to) else period,
        "date_from": df.isoformat(),
        "date_to": dt.isoformat(),
        "channels": list(CHANNELS),
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
    rows = await iiko_web.olap_sales(
        group_fields=[
            OLAP_FIELD_HOUR,
            OLAP_FIELD_ORDER_NUM,
            OLAP_FIELD_DISH_CATEGORY,
            OLAP_FIELD_DISH_NAME,
        ],
        data_fields=[OLAP_FIELD_SUM],
        date_from=df.isoformat(),
        date_to=dt.isoformat(),
    )
    buckets = _channel_revenue(rows)
    data = []
    for hk in sorted((h for h in buckets if h.isdigit()), key=int):
        h = int(hk)
        b = buckets[hk]
        row = {"hour": h, "label": f"{h:02d}-{h + 1:02d}", "total": round(sum(b.values()), 2)}
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
    меню-категории «Доставка»; иначе — не доставка. Через OLAP SALES по `OrderNum`.
    """
    df, dt = period_range(period, date_from, date_to)
    rows = await iiko_web.olap_sales(
        group_fields=[OLAP_FIELD_ORDER_NUM, OLAP_FIELD_DISH_CATEGORY, OLAP_FIELD_DISH_NAME],
        data_fields=[OLAP_FIELD_SUM],
        date_from=df.isoformat(),
        date_to=dt.isoformat(),
    )

    order_rev: dict[str, float] = {}
    order_delivery: dict[str, bool] = {}
    for r in rows:
        parts = str(r.get("field0", {}).get("value", "")).split(", ")
        if len(parts) < 3:
            continue
        order_num, category, name = parts[0], parts[1], ", ".join(parts[2:])
        if category == ORDER_STATUS_CATEGORY:
            if ORDER_STATUS_CHANNELS.get(name.strip().lower()) == CHANNEL_DELIVERY:
                order_delivery[order_num] = True
            continue
        if category == DELIVERY_CATEGORY:
            order_delivery[order_num] = True
        rev = float(r.get("field1", {}).get("value", 0) or 0)
        order_rev[order_num] = order_rev.get(order_num, 0.0) + rev
        order_delivery.setdefault(order_num, False)

    groups = {"delivery": {"revenue": 0.0, "checks": 0}, "other": {"revenue": 0.0, "checks": 0}}
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
