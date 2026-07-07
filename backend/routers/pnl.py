"""Роутер «P&L дня» — управленческий отчёт о прибыли за период.

Собирает P&L по структуре финансовой модели ресторана (Google Sheet):
выручка/чеки/food-cost считаются автоматом из БД, ручные затраты (аренда, ФОТ,
маркетинг…) вводятся помесячно (`PnlMonth`) и аллоцируются на день делением на
календарные дни месяца — поэтому отчёт честен для любого периода (день/неделя/
MTD/диапазон). Ставки-% (налог УСН, комиссия агрегатора, мотивация) применяются к
выручке. Каждая строка раскрашивается по бенчмаркам `PNL_BENCHMARKS`.

Доставка считается брутто (полная выручка), а удержание агрегатора — отдельной
строкой расхода в OPEX (решение пользователя).
"""

import calendar
from datetime import date, timedelta

from fastapi import APIRouter, Query
from sqlalchemy import select

from constants import (
    CHANNEL_DELIVERY,
    OLAP_FIELD_DISH_CATEGORY,
    OLAP_FIELD_DISH_NAME,
    OLAP_FIELD_GUESTS,
    OLAP_FIELD_OPEN_DATE,
    OLAP_FIELD_ORDER_NUM,
    OLAP_FIELD_SUM,
    PNL_BENCHMARKS,
    PNL_FIXED_MANUAL,
    PNL_MANUAL_FIELDS,
    PNL_RATE_FIELDS,
)
from models import PnlMonth, SessionLocal
from routers.revenue import _channel_revenue, _load_days
from routers.schedule import labor_for_period
from utils import period_range

router = APIRouter(prefix="/api/pnl", tags=["pnl"])


def _rate(key: str, pct: float, absval: float) -> str | None:
    """Цвет строки по бенчмарку: green/yellow/red. None — если бенчмарка нет."""
    b = PNL_BENCHMARKS.get(key)
    if not b:
        return None
    v = absval if b["unit"] in ("rub", "num") else pct
    good, warn = b["good"], b["warn"]
    if b["dir"] == "low":
        return "green" if v <= good else ("yellow" if v <= warn else "red")
    return "green" if v >= good else ("yellow" if v >= warn else "red")


def _default_month(year: int, month: int) -> dict:
    """Значения PnlMonth по умолчанию (когда за месяц ничего не введено)."""
    d = {f: 0.0 for f, _ in PNL_MANUAL_FIELDS}
    d.update({"tax_pct": 6.0, "aggregator_pct": 0.0, "motivation_pct": 15.0, "work_hours": 12})
    d.update({"year": year, "month": month})
    return d


def _row_to_dict(row: PnlMonth) -> dict:
    d = {f: float(getattr(row, f) or 0) for f, _ in PNL_MANUAL_FIELDS}
    d["tax_pct"] = float(row.tax_pct or 0)
    d["aggregator_pct"] = float(row.aggregator_pct or 0)
    d["motivation_pct"] = float(row.motivation_pct or 0)
    d["work_hours"] = int(row.work_hours or 12)
    d["year"] = row.year
    d["month"] = row.month
    return d


def _load_months(df: date, dt: date) -> dict[tuple[int, int], dict]:
    """PnlMonth-строки (как dict) для всех месяцев, которые пересекает период."""
    needed = set()
    d = df
    while d <= dt:
        needed.add((d.year, d.month))
        d += timedelta(days=1)
    out: dict[tuple[int, int], dict] = {}
    with SessionLocal() as db:
        for r in db.execute(select(PnlMonth)).scalars():
            if (r.year, r.month) in needed:
                out[(r.year, r.month)] = _row_to_dict(r)
    return out


@router.get("/costs")
def get_costs(year: int = Query(...), month: int = Query(..., ge=1, le=12)):
    """Ручные затраты за один месяц — для редактора (значения по умолчанию, если нет)."""
    with SessionLocal() as db:
        row = db.execute(
            select(PnlMonth).where(PnlMonth.year == year, PnlMonth.month == month)
        ).scalar_one_or_none()
    values = _row_to_dict(row) if row else _default_month(year, month)
    return {
        "values": values,
        "manual_fields": [{"key": k, "label": lbl} for k, lbl in PNL_MANUAL_FIELDS],
        "rate_fields": [{"key": k, "label": lbl} for k, lbl in PNL_RATE_FIELDS],
    }


@router.put("/costs")
def save_costs(payload: dict):
    """Сохранить затраты месяца. payload: {year, month, <поля>...}."""
    year = int(payload.get("year"))
    month = int(payload.get("month"))
    with SessionLocal() as db:
        row = db.execute(
            select(PnlMonth).where(PnlMonth.year == year, PnlMonth.month == month)
        ).scalar_one_or_none()
        if row is None:
            row = PnlMonth(year=year, month=month)
            db.add(row)
        for f, _ in PNL_MANUAL_FIELDS:
            setattr(row, f, float(payload.get(f, 0) or 0))
        row.tax_pct = float(payload.get("tax_pct", 6) or 0)
        row.aggregator_pct = float(payload.get("aggregator_pct", 0) or 0)
        row.motivation_pct = float(payload.get("motivation_pct", 15) or 0)
        row.work_hours = int(payload.get("work_hours", 12) or 12)
        db.commit()
    return {"ok": True}


async def _delivery_share(df: date, dt: date) -> float:
    """Доля выручки доставки в общей (по OLAP-каналам). 0..1."""
    rows = await _channel_revenue_rows(df, dt)
    buckets = _channel_revenue(rows)
    total = 0.0
    delivery = 0.0
    for b in buckets.values():
        for ch, v in b.items():
            total += v
            if ch == CHANNEL_DELIVERY:
                delivery += v
    return (delivery / total) if total else 0.0


async def _channel_revenue_rows(df: date, dt: date) -> list[dict]:
    from services.order_store import order_rows

    return await order_rows(
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


async def _total_guests(df: date, dt: date) -> float:
    """Всего гостей за период (гости — атрибут заказа, MAX на заказ в order_store)."""
    from services.order_store import order_rows

    rows = await order_rows(
        group_fields=[OLAP_FIELD_OPEN_DATE, OLAP_FIELD_ORDER_NUM],
        data_fields=[OLAP_FIELD_GUESTS],
        date_from=df.isoformat(),
        date_to=dt.isoformat(),
    )
    return sum(float(r.get("field1", {}).get("value", 0) or 0) for r in rows)


@router.get("")
async def get_pnl(
    period: str = Query("month", enum=["day", "week", "month"]),
    date_from: str | None = None,
    date_to: str | None = None,
):
    df, dt = period_range(period, date_from, date_to)
    is_custom = bool(date_from and date_to)

    days = await _load_days(df, dt, is_custom)
    revenue = sum(d["total_sum"] for d in days)
    checks = sum(d["check_count"] for d in days)
    food_cost_rub = sum(d["cost_sum"] for d in days)
    active_days = sum(1 for d in days if d["total_sum"] > 0) or 1

    guests = await _total_guests(df, dt)
    delivery_share = await _delivery_share(df, dt)
    delivery_rub = revenue * delivery_share
    hall_rub = revenue - delivery_rub

    # ручные затраты (месячные суммы) аллоцируем на дни периода
    months = _load_months(df, dt)
    manual = {f: 0.0 for f, _ in PNL_MANUAL_FIELDS}
    d = df
    while d <= dt:
        m = months.get((d.year, d.month))
        dim = calendar.monthrange(d.year, d.month)[1]
        if m:
            for f, _ in PNL_MANUAL_FIELDS:
                manual[f] += m[f] / dim
        d += timedelta(days=1)

    # ставки берём из месяца конца периода (или дефолты)
    rate_m = months.get((dt.year, dt.month)) or _default_month(dt.year, dt.month)
    tax_pct = rate_m["tax_pct"]
    aggregator_pct = rate_m["aggregator_pct"]
    work_hours = rate_m["work_hours"] or 12

    def pct(x: float) -> float:
        return (x / revenue * 100) if revenue else 0.0

    # ── COGS / себестоимость производства (структура Excel-модели) ──
    writeoffs = manual["writeoffs"]
    packaging = manual["packaging"]
    cogs = food_cost_rub + writeoffs + packaging
    # ФОТ — из графика смен (не ручной ввод): смены×ставка + оклады ÷ дней
    labor = labor_for_period(df, dt)
    labor_op = labor["operational"]
    labor_admin = labor["admin"]
    prime_cost = cogs + labor_op
    all_labor = labor_op + labor_admin
    production_cost = cogs + all_labor

    # ── OPEX ──
    tax = revenue * tax_pct / 100
    aggregator = delivery_rub * aggregator_pct / 100
    opex_manual = (
        manual["rent"]
        + manual["utilities"]
        + manual["marketing"]
        + manual["other_opex"]
        + manual["contingency"]
        + manual["cap_reserve"]
    )
    total_opex = opex_manual + tax + aggregator

    all_expenses = production_cost + total_opex
    ebitda = revenue - all_expenses
    ebitda_margin = pct(ebitda)

    # ── Маржинальный анализ: переменные растут с продажами, постоянные — фикс/мес ──
    # Численно variable + fixed == all_expenses (тот же набор строк, другой разрез).
    variable_total = food_cost_rub + writeoffs + packaging + tax + aggregator
    contribution_margin = revenue - variable_total  # маржинальная прибыль
    cm_ratio = (contribution_margin / revenue) if revenue else 0.0
    # постоянные за период = ручной фикс + ФОТ из графика (оба фикс/мес)
    fixed_alloc = sum(manual[f] for f in PNL_FIXED_MANUAL) + all_labor

    # ── Точка безубыточности: постоянные ПОЛНОГО месяца ÷ маржинальность ──
    dim_end = calendar.monthrange(dt.year, dt.month)[1]
    month_start = dt.replace(day=1)
    month_end = dt.replace(day=dim_end)
    labor_month = labor_for_period(month_start, month_end)
    fixed_month = sum(rate_m[f] for f in PNL_FIXED_MANUAL) + (
        labor_month["operational"] + labor_month["admin"]
    )
    breakeven_month = (fixed_month / cm_ratio) if cm_ratio > 0 else None
    breakeven_day = (breakeven_month / dim_end) if breakeven_month else None
    avg_rev_day = revenue / active_days

    # ── метрики загрузки ──
    avg_check = revenue / checks if checks else 0
    avg_check_guest = revenue / guests if guests else 0
    checks_per_day = checks / active_days
    checks_per_hour = checks_per_day / work_hours if work_hours else 0
    revenue_per_day = revenue / active_days
    revenue_per_hour = revenue_per_day / work_hours if work_hours else 0

    def money(key: str, label: str, rub: float, rated: bool = True) -> dict:
        p = round(pct(rub), 1)
        return {
            "key": key,
            "label": label,
            "kind": "money",
            "rub": round(rub, 0),
            "pct": p,
            "rating": _rate(key, p, rub) if rated else None,
        }

    def metric(key: str, label: str, value: float | None, unit: str) -> dict:
        return {
            "key": key,
            "label": label,
            "kind": "metric",
            "value": None if value is None else round(value, 0 if unit != "num" else 1),
            "unit": unit,
            "rating": None if value is None else _rate(key, value, value),
        }

    sales = [
        money("revenue", "Выручка", revenue, rated=False),
        money("revenue_hall", "— Зал", hall_rub, rated=False),
        money("revenue_delivery", "— Доставка (брутто)", delivery_rub, rated=False),
        metric("checks", "Чеков", checks, "num"),
        metric("avg_check", "Средний чек", avg_check, "rub"),
        metric("avg_check_guest", "Средний чек на гостя", avg_check_guest, "rub"),
        metric("checks_per_day", "Чеков / день", checks_per_day, "num"),
        metric("checks_per_hour", "Чеков / час", checks_per_hour, "num"),
        metric("revenue_per_day", "Выручка / день", revenue_per_day, "rub"),
        metric("revenue_per_hour", "Выручка / час", revenue_per_hour, "rub"),
    ]

    production = [
        money("food_cost", "Food cost", food_cost_rub),
        money("writeoffs", "Списания", writeoffs),
        money("packaging", "Упаковка", packaging),
        money("cogs", "COGS (себестоимость товара)", cogs),
        money("labor_op", "Операционный ФОТ", labor_op),
        money("labor_admin", "Административный ФОТ", labor_admin),
        money("prime_cost", "Prime cost (COGS + опер. ФОТ)", prime_cost),
        money("all_labor", "Весь ФОТ", all_labor),
        money("production_cost", "Себестоимость производства", production_cost),
    ]

    opex = [
        money("aggregator", "Комиссия агрегатора (доставка)", aggregator, rated=False),
        money("rent", "Аренда", manual["rent"]),
        money("utilities", "Коммуналка", manual["utilities"]),
        money("marketing", "Маркетинг", manual["marketing"]),
        money("other_opex", "Прочие (IT/ОФД/эквайринг/аморт.)", manual["other_opex"]),
        money("tax", f"Налог (УСН {tax_pct:g}%)", tax, rated=False),
        money("contingency", "Непредвиденные", manual["contingency"]),
        money("cap_reserve", "Кап-резерв", manual["cap_reserve"], rated=False),
        money("total_opex", "Итого OPEX", total_opex, rated=False),
    ]

    # маржинальный разрез + безубыточность (переменные/постоянные — другой взгляд на те же расходы)
    ebitda_line = {
        "key": "ebitda",
        "label": "EBITDA",
        "kind": "money",
        "rub": round(ebitda, 0),
        "pct": round(ebitda_margin, 1),
        "rating": _rate("ebitda_margin", ebitda_margin, ebitda_margin),
    }
    margin = [
        money(
            "variable_total", "Переменные затраты (растут с продажами)", variable_total, rated=False
        ),
        money("contribution_margin", "Маржинальная прибыль", contribution_margin, rated=False),
        money("fixed_alloc", "Постоянные затраты за период", fixed_alloc, rated=False),
        metric("breakeven_month", "Точка безубыточности, ₽/мес", breakeven_month, "rub"),
        metric("breakeven_day", "Точка безубыточности, ₽/сутки", breakeven_day, "rub"),
        metric("avg_rev_day", "Средняя выручка/сутки (факт)", avg_rev_day, "rub"),
    ]

    profit = [
        money("all_expenses", "Все расходы", all_expenses),
        ebitda_line,
    ]

    return {
        "period": "custom" if is_custom else period,
        "date_from": df.isoformat(),
        "date_to": dt.isoformat(),
        "active_days": active_days,
        "has_costs": bool(months),
        "revenue": round(revenue, 0),
        "ebitda": round(ebitda, 0),
        "ebitda_margin": round(ebitda_margin, 1),
        "ebitda_rating": _rate("ebitda_margin", ebitda_margin, ebitda_margin),
        "breakeven": {
            "cm_ratio": round(cm_ratio * 100, 1),
            "fixed_month": round(fixed_month, 0),
            "revenue_month": None if breakeven_month is None else round(breakeven_month, 0),
            "revenue_day": None if breakeven_day is None else round(breakeven_day, 0),
            "avg_rev_day": round(avg_rev_day, 0),
        },
        "sections": [
            {"key": "sales", "label": "Продажи / загрузка", "lines": sales},
            {"key": "production", "label": "Себестоимость производства", "lines": production},
            {"key": "opex", "label": "Операционные расходы", "lines": opex},
            {"key": "margin", "label": "Маржинальность и безубыточность", "lines": margin},
            {"key": "profit", "label": "Прибыль", "lines": profit},
        ],
    }
