"""Роутер выручки: по дням (из БД либо живой за произвольный диапазон) и по часам."""

from datetime import date, timedelta

from fastapi import APIRouter, Query
from sqlalchemy import select

from constants import (
    DAY_NAMES_RU,
    METRIC_AVG_SPEND,
    METRIC_COST,
    METRIC_DISCOUNT,
    METRIC_REFUNDS,
    METRIC_REV_GROSS,
    METRIC_TRN_ALL,
)
from iiko_web_client import iiko_web
from models import RevenueDaily, SessionLocal
from utils import period_range
from weather import get_weather

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
    prev_rev = sum(r["total_sum"] for r in prev_days)
    prev_checks = sum(r["check_count"] for r in prev_days)

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
