"""Роутер слоя «План»: дневные нормы на дейпарт × группу дня недели.

План задаётся одной дневной нормой на сегмент (дейпарт × группа дня недели), а план
на период считается умножением на число подходящих дней — так `% к плану` честен для
любого периода (день/неделя/MTD/диапазон). Метрики: выручка, средний чек, гости.
Заполняется автосидом из истории и правится вручную.
"""

from datetime import date, timedelta

from fastapi import APIRouter, Query
from sqlalchemy import delete, select

from constants import (
    DAYPARTS,
    OLAP_FIELD_DISH_CATEGORY,
    OLAP_FIELD_HOUR,
    OLAP_FIELD_OPEN_DATE,
    OLAP_FIELD_ORDER_NUM,
    OLAP_FIELD_SUM,
    ORDER_STATUS_CATEGORY,
    WEEKDAY_GROUPS,
    WEEKDAY_TO_GROUP,
)
from iiko_web_client import iiko_web
from models import DaypartPlan, SessionLocal
from services.daypart import hour_to_daypart
from services.olap_parse import split_field_4
from utils import today

OLAP_FIELD_GUESTS = "GuestNum"

router = APIRouter(prefix="/api/plan", tags=["plan"])


def _load_plan() -> dict[tuple[str, str], DaypartPlan]:
    with SessionLocal() as db:
        rows = db.execute(select(DaypartPlan)).scalars().all()
        return {(r.daypart_key, r.weekday_group): r for r in rows}


@router.get("")
def get_plan():
    """Текущий план — матрица (дейпарт × группа дня недели) с нормами на день."""
    plan = _load_plan()
    cells = {}
    for dp in DAYPARTS:
        for g in WEEKDAY_GROUPS:
            r = plan.get((dp["key"], g["key"]))
            cells[f"{dp['key']}|{g['key']}"] = {
                "revenue": round(r.revenue, 2) if r else 0,
                "avg_check": round(r.avg_check, 2) if r else 0,
                "guests": round(r.guests, 1) if r else 0,
            }
    return {
        "dayparts": [
            {"key": dp["key"], "label": dp["label"], "range": dp["range"]} for dp in DAYPARTS
        ],
        "weekday_groups": [{"key": g["key"], "label": g["label"]} for g in WEEKDAY_GROUPS],
        "cells": cells,
        "has_plan": any(c["revenue"] for c in cells.values()),
    }


@router.put("")
def save_plan(payload: dict):
    """Сохранить план: payload.cells = {"<дейпарт>|<группа>": {revenue, avg_check, guests}}."""
    cells = payload.get("cells", {})
    with SessionLocal() as db:
        existing = {
            (r.daypart_key, r.weekday_group): r for r in db.execute(select(DaypartPlan)).scalars()
        }
        valid_dp = {dp["key"] for dp in DAYPARTS}
        valid_g = {g["key"] for g in WEEKDAY_GROUPS}
        for ck, vals in cells.items():
            if "|" not in ck:
                continue
            dpk, gk = ck.split("|", 1)
            if dpk not in valid_dp or gk not in valid_g:
                continue
            row = existing.get((dpk, gk))
            if row is None:
                row = DaypartPlan(daypart_key=dpk, weekday_group=gk)
                db.add(row)
            row.revenue = float(vals.get("revenue", 0) or 0)
            row.avg_check = float(vals.get("avg_check", 0) or 0)
            row.guests = float(vals.get("guests", 0) or 0)
        db.commit()
    return {"ok": True}


@router.post("/seed-from-history")
async def seed_from_history(months: int = Query(2, ge=1, le=12)):
    """Заполнить план средними дневными нормами из истории за последние N месяцев.

    Для каждого (дейпарт × группа дня недели) берём среднюю за день выручку/гостей и
    средний чек по историческим дням. Перезаписывает план целиком (потом правится руками).
    """
    dt = today() - timedelta(days=1)  # вчера — последний полный день
    df = dt - timedelta(days=months * 30)

    rows = await iiko_web.olap_sales(
        group_fields=[
            OLAP_FIELD_OPEN_DATE,
            OLAP_FIELD_HOUR,
            OLAP_FIELD_ORDER_NUM,
            OLAP_FIELD_DISH_CATEGORY,
        ],
        data_fields=[OLAP_FIELD_SUM, OLAP_FIELD_GUESTS],
        date_from=df.isoformat(),
        date_to=dt.isoformat(),
    )

    h2dp = hour_to_daypart()
    # (дата, дейпарт) → {revenue, orders:set, guests:{order:n}}
    acc: dict[tuple[str, str], dict] = {}
    for r in rows:
        ds, hs, ordernum, category = split_field_4(r.get("field0", {}).get("value", ""))
        if not ds or category == ORDER_STATUS_CATEGORY:
            continue
        try:
            hour = int(hs)
        except ValueError:
            continue
        dp = h2dp.get(hour)
        if dp is None:
            continue
        rev = float(r.get("field1", {}).get("value", 0) or 0)
        guests = float(r.get("field2", {}).get("value", 0) or 0)
        e = acc.setdefault((ds, dp), {"revenue": 0.0, "orders": set(), "guests": {}})
        e["revenue"] += rev
        e["orders"].add(ordernum)
        e["guests"].setdefault(ordernum, guests)

    # группируем дни по (дейпарт, группа дня недели) и усредняем по дням
    seg: dict[tuple[str, str], dict] = {}
    for (ds, dp), e in acc.items():
        try:
            grp = WEEKDAY_TO_GROUP[date.fromisoformat(ds).weekday()]
        except (ValueError, KeyError):
            continue
        s = seg.setdefault((dp, grp), {"rev": 0.0, "checks": 0, "guests": 0.0, "days": 0})
        s["rev"] += e["revenue"]
        s["checks"] += len(e["orders"])
        s["guests"] += sum(e["guests"].values())
        s["days"] += 1

    with SessionLocal() as db:
        db.execute(delete(DaypartPlan))
        for (dp, grp), s in seg.items():
            n = s["days"] or 1
            db.add(
                DaypartPlan(
                    daypart_key=dp,
                    weekday_group=grp,
                    revenue=round(s["rev"] / n, 2),
                    avg_check=round(s["rev"] / s["checks"], 2) if s["checks"] else 0,
                    guests=round(s["guests"] / n, 1),
                )
            )
        db.commit()

    return {
        "ok": True,
        "date_from": df.isoformat(),
        "date_to": dt.isoformat(),
        "segments": len(seg),
    }
