"""Роутер «P&L дня» — управленческий отчёт о прибыли за период.

Собирает P&L по структуре финансовой модели ресторана (Google Sheet):
выручка/чеки/food-cost считаются автоматом из БД, постоянные затраты (аренда, ФОТ,
маркетинг…) вводятся помесячно (`PnlMonth`) и аллоцируются на день делением на
календарные дни месяца — поэтому отчёт честен для любого периода (день/неделя/
MTD/диапазона). Ставки-% (налог УСН, комиссия агрегатора, мотивация) применяются к
выручке. Каждая строка раскрашивается по бенчмаркам `PNL_BENCHMARKS`.

**Лесенка прибыли** (корректная трактовка EBITDA): EBITDA = выручка − себестоимость
производства (COGS + операционный ФОТ) − операционный OPEX (аренда/коммуналка/админ-ФОТ/
маркетинг/прочие/непредвиденные/химия/расходники/комиссия агрегатора) — то есть ДО
налога УСН и кап-резерва. Ниже: `EBITDA − Налог (УСН) − Кап-резерв = Чистая прибыль`
(`net_profit`/`net_margin`, бенчмарк `net_margin`). **Амортизация** отдельной строкой не
выделена — в исходной модели она зашита в «Прочие» (`other_opex`) и остаётся над EBITDA
(нет отдельной цифры, чтобы её вычесть; добавить строку «Амортизация ₽» в таблицу — и
можно будет разнести). Налог/кап-резерв — единственное, что отделено под EBITDA.

Переменные статьи (списания/упаковка/химия/расходники) вводятся ПО ДНЯМ
(`PnlDayCost`, редактор «Затраты по дням») — чтобы ловить дневные всплески; при
отсутствии дневной строки packaging/writeoffs откатываются к помесячному резерву
`PnlMonth`, а химия/расходники считаются нулём (`_day_var_costs`). Подневная матрица
на фронте рисует все статьи «дни × статьи» и подсвечивает всплеск (день заметно выше
своей же среднесуточной нормы).

Доставка считается брутто (полная выручка), а удержание агрегатора — отдельной
строкой расхода в OPEX (решение пользователя). Зал и доставка нигде не смешиваются —
выручка/чеки/ср.чек/загрузка считаются раздельно (`_channel_totals`/`_day_pnl`).
**Комиссия агрегатора** считается от ФАКТИЧЕСКОЙ выручки через агрегатора (платежи
«Яндекс Еда» из `order_payments`, `_aggregator_rev_by_day`) × ставку удержания — а не
от всей категории «доставка» (там бывает самовывоз/своя доставка). **Маркетинг**
учитывается в ИТОГЕ за период (EBITDA/OPEX/безубыточность), но НЕ разносится в
подневную матрицу (решение пользователя — лумповый месячный расход). Поэтому
подневная EBITDA (`_day_pnl`) на маркетинг НЕ уменьшается — её Факт в матрице выше
итоговой EBITDA ровно на сумму маркетинга (в матрице строка подписана «без марк.»).

**Административный ФОТ** (`labor_admin`, управляющий ~100 тыс/мес) — постоянный расход,
идёт ОТДЕЛЬНОЙ строкой OPEX (не из графика смен, чтобы не задваивать с операционным
`labor_op`). Импортируется из строки «Admin Labor ₽» таблицы в поле `labor_admin`, а
«Прочие» (`other_opex`) — только IT/ОФД/эквайринг/амортизация (раньше были слиты).
"""

import calendar
from datetime import date, timedelta

import httpx
from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select

from constants import (
    DAY_NAMES_RU,
    OLAP_FIELD_GUESTS,
    OLAP_FIELD_OPEN_DATE,
    OLAP_FIELD_ORDER_NUM,
    PNL_BENCHMARKS,
    PNL_DAY_COST_FIELDS,
    PNL_FIXED_MANUAL,
    PNL_MANUAL_FIELDS,
    PNL_RATE_FIELDS,
)
from models import PnlDayCost, PnlMonth, SessionLocal
from routers.revenue import _days_from_db, _days_live, _load_days
from routers.schedule import labor_by_day, labor_for_period
from services.delivery import delivery_buckets
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


def _load_day_costs(df: date, dt: date) -> dict[str, dict]:
    """PnlDayCost-строки периода как {ISO-дата: {статья: ₽}}."""
    with SessionLocal() as db:
        rows = db.execute(
            select(PnlDayCost).where(
                PnlDayCost.date >= df.isoformat(), PnlDayCost.date <= dt.isoformat()
            )
        ).scalars()
        return {
            r.date: {
                "writeoffs": float(r.writeoffs or 0),
                "packaging": float(r.packaging or 0),
                "chemicals": float(r.chemicals or 0),
                "supplies": float(r.supplies or 0),
            }
            for r in rows
        }


def _aggregator_rev_by_day(df: date, dt: date) -> dict[str, float]:
    """Выручка через агрегатора по дням из `order_payments` (группа «Агрегатор»).

    База для комиссии агрегатора — то, что реально оплачено через агрегатора («Яндекс
    Еда»), а не вся категория «доставка» (там бывает и самовывоз/своя доставка).
    """
    from constants import PAYMENT_AGGREGATOR
    from models import OrderPayment
    from utils import payment_group

    out: dict[str, float] = {}
    with SessionLocal() as db:
        rows = db.execute(
            select(OrderPayment.date, OrderPayment.pay_type, OrderPayment.amount).where(
                OrderPayment.date >= df, OrderPayment.date <= dt
            )
        ).all()
    for d, pt, amt in rows:
        if payment_group(pt) == PAYMENT_AGGREGATOR:
            key = d.isoformat()
            out[key] = out.get(key, 0.0) + float(amt or 0)
    return out


def _payments_start() -> date | None:
    """Самая ранняя дата в `order_payments` (начало данных об оплатах). None — таблица
    пуста. Периоды раньше этой даты не имеют базы для комиссии агрегатора (#5)."""
    from models import OrderPayment

    with SessionLocal() as db:
        return db.execute(select(func.min(OrderPayment.date))).scalar()


def _day_var_costs(d: date, day_costs: dict, months: dict) -> dict:
    """Переменные статьи за день (списания/упаковка/химия/расходники).

    Если за день есть строка `PnlDayCost` — берём ВСЕ 4 оттуда (включая явные 0);
    иначе packaging/writeoffs откатываются к помесячной аллокации `PnlMonth` (÷ дней),
    а химия/расходники (нет помесячного поля) считаются нулём.
    """
    row = day_costs.get(d.isoformat())
    if row is not None:
        return {k: row[k] for k in ("writeoffs", "packaging", "chemicals", "supplies")}
    m = months.get((d.year, d.month)) or _default_month(d.year, d.month)
    dim = calendar.monthrange(d.year, d.month)[1]
    return {
        "writeoffs": m["writeoffs"] / dim,
        "packaging": m["packaging"] / dim,
        "chemicals": 0.0,
        "supplies": 0.0,
    }


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


@router.post("/import-sheet")
def import_sheet():
    """Импорт помесячных затрат из Google-таблицы P&L (публичный xlsx-экспорт).

    Заполняет `PnlMonth` (аренда/коммуналка/маркетинг/прочие+админ-ФОТ/непредвиденные/
    кап-резерв/упаковка + ставки налог/агрегатор). ФОТ и дневные статьи не трогает.
    """
    from services.pnl_sheet import import_pnl_sheet

    try:
        return import_pnl_sheet()
    except httpx.HTTPError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Не удалось прочитать таблицу: {e}")


@router.get("/day-costs")
def get_day_costs(date_from: str = Query(...), date_to: str = Query(...)):
    """Дневные переменные затраты за период — для редактора «Затраты по дням».

    Дни без своей строки предзаполняются помесячным резервом (packaging/writeoffs
    ÷ дней месяца) как черновик; `has_row` показывает, введён ли день вручную.
    """
    df = date.fromisoformat(date_from)
    dt = date.fromisoformat(date_to)
    stored = _load_day_costs(df, dt)
    months = _load_months(df, dt)
    days = []
    d = df
    while d <= dt:
        iso = d.isoformat()
        row = stored.get(iso)
        vals = row if row is not None else _day_var_costs(d, {}, months)
        days.append(
            {
                "date": iso,
                "day_of_week": DAY_NAMES_RU[d.weekday()],
                "has_row": row is not None,
                **{k: round(vals[k], 0) for k, _ in PNL_DAY_COST_FIELDS},
            }
        )
        d += timedelta(days=1)
    return {
        "date_from": df.isoformat(),
        "date_to": dt.isoformat(),
        "fields": [{"key": k, "label": lbl} for k, lbl in PNL_DAY_COST_FIELDS],
        "days": days,
    }


@router.put("/day-costs")
def save_day_costs(payload: dict):
    """Сохранить дневные затраты. payload: {days: [{date, writeoffs, ...}, ...]}."""
    rows = payload.get("days") or []
    with SessionLocal() as db:
        for r in rows:
            iso = str(r.get("date") or "")
            if not iso:
                continue
            existing = db.get(PnlDayCost, iso)
            if existing is None:
                existing = PnlDayCost(date=iso)
                db.add(existing)
            for k, _ in PNL_DAY_COST_FIELDS:
                setattr(existing, k, float(r.get(k, 0) or 0))
        db.commit()
    return {"ok": True}


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


def _channel_totals(days: list[dict], del_buckets: dict[str, dict]) -> dict[str, dict]:
    """Разбивает дни на зал/доставку по выручке и чекам — без смешения (#5).

    `del_buckets` — {дата: {"revenue", "checks"}} доставки (`services.delivery`,
    единое правило `is_delivery`); зал = остаток. Никогда не считаем зал+доставку
    смешанной суммой — только раздельно, затем при необходимости складываем сами.
    """
    hall_rev = hall_checks = 0.0
    del_rev = del_checks = 0.0
    for d in days:
        dd = del_buckets.get(d["date"], {"revenue": 0.0, "checks": 0})
        del_rev += dd["revenue"]
        del_checks += dd["checks"]
        hall_rev += max(0.0, d["total_sum"] - dd["revenue"])
        hall_checks += max(0, d["check_count"] - dd["checks"])
    return {
        "hall": {"revenue": hall_rev, "checks": int(hall_checks)},
        "delivery": {"revenue": del_rev, "checks": int(del_checks)},
    }


def _make_prev_mapper(period: str, df: date, dt: date, is_custom: bool):
    """Функция date → сопоставимая дата предыдущего периода, ВСЕГДА того же дня недели
    (главное правило пользователя: пн сравниваем с пн, чт — с чт, сб — с сб).

    День/неделя → сдвиг на 7 дней (прошлая неделя, тот же день недели). Месяц (MTD) →
    сдвиг на 4 недели с коррекцией ещё на неделю назад, если попали в текущий месяц
    (конец длинных месяцев) — так гарантированно остаёмся в прошлом месяце и день
    недели не съезжает. Произвольный диапазон → сдвиг, кратный 7 дням, не короче
    периода (не пересекается с текущим).
    """
    if period == "month" and not is_custom:
        month_start = df.replace(day=1)

        def mapper(d: date) -> date:
            p = d - timedelta(days=28)
            if p >= month_start:
                p -= timedelta(days=7)
            return p

        return mapper
    if not is_custom:  # day / week — ровно неделя назад
        return lambda d: d - timedelta(days=7)
    span = (dt - df).days + 1
    shift = 7 * ((span + 6) // 7)
    return lambda d: d - timedelta(days=shift)


def _day_pnl(
    d_str: str,
    day_data: dict,
    del_bucket: dict,
    months: dict,
    labor_day: dict,
    day_costs: dict,
    agg_rev: float,
) -> dict:
    """P&L-метрики одного дня по ВСЕМ статьям (для подневной матрицы и сравнения).

    Зал/доставка считаются раздельно (#5); ФОТ — только операционный (#4, админ ФОТ
    сюда не входит — он в постоянных расходах). Переменные статьи (списания/упаковка/
    химия/расходники) берутся по дню из `PnlDayCost` (или помесячный резерв), остальные
    постоянные — из `PnlMonth` ÷ дней месяца. Каждая статья — отдельным ключом-₽,
    чтобы фронт-матрица рисовала строки и считала долю от выручки дня.

    **Маркетинг исключён из подневного разреза** (решение пользователя — это лумповый
    месячный расход, не операционный расход дня). **Комиссия агрегатора** считается от
    ФАКТИЧЕСКОЙ выручки через агрегатора (`agg_rev` — платежи «Яндекс Еда» за день из
    `order_payments`), а не от всей категории «доставка».
    """
    d = date.fromisoformat(d_str)
    revenue = float(day_data["total_sum"])
    cost_sum = float(day_data["cost_sum"])
    checks = int(day_data["check_count"])
    del_rev = float(del_bucket.get("revenue", 0.0))
    del_checks = int(del_bucket.get("checks", 0))
    revenue_hall = max(0.0, revenue - del_rev)
    checks_hall = max(0, checks - del_checks)

    m = months.get((d.year, d.month)) or _default_month(d.year, d.month)
    dim = calendar.monthrange(d.year, d.month)[1]
    var = _day_var_costs(d, day_costs, months)
    writeoffs, packaging = var["writeoffs"], var["packaging"]
    chemicals, supplies = var["chemicals"], var["supplies"]
    food_cost = cost_sum
    cogs = food_cost + writeoffs + packaging
    labor_op = labor_day.get(d, {}).get("operational", 0.0)
    rent = m["rent"] / dim
    utilities = m["utilities"] / dim
    marketing = m["marketing"] / dim  # возвращаем для справки, в дневной расход НЕ входит
    admin_fot = m["labor_admin"] / dim
    other_opex = m["other_opex"] / dim
    contingency = m["contingency"] / dim
    cap_reserve = m["cap_reserve"] / dim
    tax = revenue * m["tax_pct"] / 100
    aggregator = agg_rev * m["aggregator_pct"] / 100
    # операционный OPEX дня (над EBITDA) — БЕЗ налога, кап-резерва и маркетинга
    opex = (
        chemicals + supplies + rent + utilities + admin_fot + other_opex + contingency + aggregator
    )
    ebitda = revenue - cogs - labor_op - opex  # EBITDA до налога/кап-резерва (и без марк.)
    net_profit = ebitda - tax - cap_reserve  # чистая прибыль дня (без марк.)
    total_expenses = cogs + labor_op + opex + tax + cap_reserve  # без маркетинга

    return {
        "date": d_str,
        "day_of_week": DAY_NAMES_RU[d.weekday()],
        "revenue": round(revenue, 0),
        "revenue_hall": round(revenue_hall, 0),
        "revenue_delivery": round(del_rev, 0),
        "checks": checks,
        "checks_hall": checks_hall,
        "checks_delivery": del_checks,
        "agg_revenue": round(agg_rev, 0),
        "food_cost": round(food_cost, 0),
        "writeoffs": round(writeoffs, 0),
        "packaging": round(packaging, 0),
        "chemicals": round(chemicals, 0),
        "supplies": round(supplies, 0),
        "cogs": round(cogs, 0),
        "labor": round(labor_op, 0),
        "rent": round(rent, 0),
        "utilities": round(utilities, 0),
        "marketing": round(marketing, 0),
        "admin_fot": round(admin_fot, 0),
        "other_opex": round(other_opex, 0),
        "contingency": round(contingency, 0),
        "cap_reserve": round(cap_reserve, 0),
        "tax": round(tax, 0),
        "aggregator": round(aggregator, 0),
        "total_expenses": round(total_expenses, 0),
        "ebitda": round(ebitda, 0),
        "net_profit": round(net_profit, 0),
        "ebitda_margin": round(ebitda / revenue * 100, 1) if revenue else 0.0,
        "food_cost_pct": round(cost_sum / revenue * 100, 1) if revenue else 0.0,
    }


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
    del_buckets = await delivery_buckets(df, dt, OLAP_FIELD_OPEN_DATE)
    channels = _channel_totals(days, del_buckets)
    hall_rub, delivery_rub = channels["hall"]["revenue"], channels["delivery"]["revenue"]
    checks_hall, checks_delivery = channels["hall"]["checks"], channels["delivery"]["checks"]

    # выручка через агрегатора (платежи «Яндекс Еда») — база комиссии агрегатора
    agg_by_day = _aggregator_rev_by_day(df, dt)

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

    # переменные статьи (списания/упаковка/химия/расходники) — по дням из PnlDayCost
    # (или помесячный резерв), суммируем за период — единый источник для сумм и матрицы
    day_costs = _load_day_costs(df, dt)
    var_sum = {k: 0.0 for k, _ in PNL_DAY_COST_FIELDS}
    d = df
    while d <= dt:
        vc = _day_var_costs(d, day_costs, months)
        for k in var_sum:
            var_sum[k] += vc[k]
        d += timedelta(days=1)

    # #5: если период раньше данных об оплатах — базы агрегатора нет (order_payments
    # только в пределах сохранённой истории). Тогда оцениваем базу по выручке доставки.
    pay_start = _payments_start()
    agg_estimated = pay_start is None or dt < pay_start
    if agg_estimated:
        agg_by_day = {
            dd["date"]: float(del_buckets.get(dd["date"], {}).get("revenue", 0.0)) for dd in days
        }
    agg_rev_total = sum(agg_by_day.values())

    # ставки берём из месяца конца периода (или дефолты) — для подписей
    rate_m = months.get((dt.year, dt.month)) or _default_month(dt.year, dt.month)
    tax_pct = rate_m["tax_pct"]
    work_hours = rate_m["work_hours"] or 12

    # #4: налог и комиссию агрегатора итога считаем СУММОЙ ПО ДНЯМ (те же помесячные
    # ставки, что и в матрице) — чтобы диапазон через 2 месяца с разными ставками сходился
    tax = 0.0
    aggregator = 0.0
    for dd in days:
        dm = date.fromisoformat(dd["date"])
        mm = months.get((dm.year, dm.month)) or _default_month(dm.year, dm.month)
        tax += float(dd["total_sum"]) * mm["tax_pct"] / 100
        aggregator += agg_by_day.get(dd["date"], 0.0) * mm["aggregator_pct"] / 100
    # эффективная ставка агрегатора за период — для честной подписи (при одном месяце = ставке)
    aggregator_pct = (
        (aggregator / agg_rev_total * 100) if agg_rev_total else rate_m["aggregator_pct"]
    )

    def pct(x: float) -> float:
        return (x / revenue * 100) if revenue else 0.0

    # ── COGS / себестоимость производства (структура Excel-модели) ──
    writeoffs = var_sum["writeoffs"]
    packaging = var_sum["packaging"]
    chemicals = var_sum["chemicals"]
    supplies = var_sum["supplies"]
    cogs = food_cost_rub + writeoffs + packaging
    # ФОТ: операционный — из графика смен (смены×ставка + оклады ÷ дней); админ-ФОТ —
    # из PnlMonth (`manual["labor_admin"]`), он же отдельной строкой OPEX (не задваиваем).
    labor = labor_for_period(df, dt)
    labor_op = labor["operational"]
    labor_admin_rub = manual["labor_admin"]
    # Аналитические показатели модели (только для отображения, НЕ для арифметики EBITDA):
    #   Prime cost               = COGS + операционный ФОТ
    #   Себестоимость производства = COGS + ВЕСЬ ФОТ (операционный + админ) = «All Labor»
    # Различаются ровно на админ-ФОТ (у них разные бенчмарки: 48–53 % против 60–65 %).
    prime_cost = cogs + labor_op
    production_cost = cogs + labor_op + labor_admin_rub

    # ── OPEX ── (tax/aggregator посчитаны выше суммой по дням — #4)
    # маркетинг учитывается в ИТОГЕ за период (EBITDA/безубыточность), но НЕ в подневной
    # матрице (решение пользователя — лумповый месячный расход не размазываем по дням).
    # ОПЕРАЦИОННЫЙ OPEX — всё, что НАД EBITDA: налог УСН и кап-резерв сюда НЕ входят,
    # они вычитаются ниже, в лесенке EBITDA → Чистая прибыль (см. `profit`).
    opex_manual = (
        manual["rent"]
        + manual["utilities"]
        + manual["labor_admin"]
        + manual["marketing"]
        + manual["other_opex"]
        + manual["contingency"]
    )
    # химия/расходники — переменные дневные статьи, идут в OPEX сверх постоянных ручных
    day_var_opex = chemicals + supplies
    # операционный OPEX (над EBITDA): постоянные ручные + дневные + комиссия агрегатора
    total_opex = opex_manual + day_var_opex + aggregator
    cap_reserve_rub = manual["cap_reserve"]

    # ── Лесенка прибыли ──
    # EBITDA = выручка − (COGS + операционный ФОТ) − операционный OPEX (ДО налога УСН,
    # кап-резерва). Берём именно COGS+операц.ФОТ, а НЕ production_cost: админ-ФОТ уже сидит
    # в total_opex (`manual["labor_admin"]`), иначе он задвоился бы. production_cost —
    # аналитический показатель для отображения, в арифметике не участвует.
    # Амортизация не выделена отдельной строкой — в модели она зашита в «Прочие»
    # (other_opex) и остаётся над EBITDA (нет исходной цифры, чтобы вычесть).
    ebitda = revenue - (cogs + labor_op) - total_opex
    ebitda_margin = pct(ebitda)
    # Чистая прибыль = EBITDA − налог УСН − кап-резерв
    net_profit = ebitda - tax - cap_reserve_rub
    net_margin = pct(net_profit)

    # ── Маржинальный анализ: переменные растут с продажами, постоянные — фикс/мес ──
    variable_total = food_cost_rub + writeoffs + packaging + chemicals + supplies + tax + aggregator
    contribution_margin = revenue - variable_total
    cm_ratio = (contribution_margin / revenue) if revenue else 0.0
    # постоянные затраты за период (маркетинг входит — учитывается в итоге, не в днях)
    fixed_alloc = sum(manual[f] for f in PNL_FIXED_MANUAL) + labor_op

    # ── Точка безубыточности: постоянные ПОЛНОГО месяца ÷ маржинальность ──
    dim_end = calendar.monthrange(dt.year, dt.month)[1]
    month_start = dt.replace(day=1)
    month_end = dt.replace(day=dim_end)
    labor_month = labor_for_period(month_start, month_end)
    fixed_month = sum(rate_m[f] for f in PNL_FIXED_MANUAL) + labor_month["operational"]
    breakeven_month = (fixed_month / cm_ratio) if cm_ratio > 0 else None
    # #4: порог/сутки — на РАБОЧИЙ день, не календарный (иначе несопоставим с фактической
    # средней выручкой на активный день — точка работает не каждый календарный день).
    # Ожидаемое число рабочих дней месяца оцениваем по доле активных дней в периоде:
    # так и порог, и факт (`avg_rev_day`) считаются на один и тот же операционный день.
    period_days = (dt - df).days + 1
    op_days_month = dim_end * (active_days / period_days) if period_days else dim_end
    breakeven_day = breakeven_month / op_days_month if (breakeven_month and op_days_month) else None
    avg_rev_day = revenue / active_days

    # ── метрики загрузки — зал и доставка раздельно, нигде не смешиваем (#5) ──
    avg_check = revenue / checks if checks else 0
    avg_check_hall = hall_rub / checks_hall if checks_hall else 0
    avg_check_delivery = delivery_rub / checks_delivery if checks_delivery else 0
    avg_check_guest = revenue / guests if guests else 0
    checks_per_day = checks / active_days
    checks_per_day_hall = checks_hall / active_days
    checks_per_day_delivery = checks_delivery / active_days
    checks_per_hour = checks_per_day / work_hours if work_hours else 0
    checks_per_hour_hall = checks_per_day_hall / work_hours if work_hours else 0
    checks_per_hour_delivery = checks_per_day_delivery / work_hours if work_hours else 0
    revenue_per_day = revenue / active_days
    revenue_per_day_hall = hall_rub / active_days
    revenue_per_day_delivery = delivery_rub / active_days
    revenue_per_hour = revenue_per_day / work_hours if work_hours else 0
    revenue_per_hour_hall = revenue_per_day_hall / work_hours if work_hours else 0
    revenue_per_hour_delivery = revenue_per_day_delivery / work_hours if work_hours else 0

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
        money("agg_revenue", "— Через агрегатора (оплаты)", agg_rev_total, rated=False),
        metric("checks", "Чеков", checks, "num"),
        metric("checks_hall", "— Зал", checks_hall, "num"),
        metric("checks_delivery", "— Доставка", checks_delivery, "num"),
        metric("avg_check", "Средний чек", avg_check, "rub"),
        metric("avg_check_hall", "— Зал", avg_check_hall, "rub"),
        metric("avg_check_delivery", "— Доставка", avg_check_delivery, "rub"),
        metric("avg_check_guest", "Средний чек на гостя", avg_check_guest, "rub"),
        metric("checks_per_day", "Чеков / день", checks_per_day, "num"),
        metric("checks_per_day_hall", "— Зал", checks_per_day_hall, "num"),
        metric("checks_per_day_delivery", "— Доставка", checks_per_day_delivery, "num"),
        metric("checks_per_hour", "Чеков / час", checks_per_hour, "num"),
        metric("checks_per_hour_hall", "— Зал", checks_per_hour_hall, "num"),
        metric("checks_per_hour_delivery", "— Доставка", checks_per_hour_delivery, "num"),
        metric("revenue_per_day", "Выручка / день", revenue_per_day, "rub"),
        metric("revenue_per_day_hall", "— Зал", revenue_per_day_hall, "rub"),
        metric("revenue_per_day_delivery", "— Доставка", revenue_per_day_delivery, "rub"),
        metric("revenue_per_hour", "Выручка / час", revenue_per_hour, "rub"),
        metric("revenue_per_hour_hall", "— Зал", revenue_per_hour_hall, "rub"),
        metric("revenue_per_hour_delivery", "— Доставка", revenue_per_hour_delivery, "rub"),
    ]

    production = [
        money("food_cost", "Food cost", food_cost_rub),
        money("writeoffs", "Списания", writeoffs),
        money("packaging", "Упаковка", packaging),
        money("cogs", "COGS (себестоимость товара)", cogs),
        money("labor_op", "ФОТ (операционный)", labor_op),
        money("prime_cost", "Prime cost (COGS + операц. ФОТ)", prime_cost),
        money("labor_admin", "— в т.ч. админ. ФОТ (в OPEX)", labor_admin_rub, rated=False),
        money("production_cost", "Себестоимость производства (COGS + весь ФОТ)", production_cost),
    ]

    agg_base_note = " · оценка от доставки" if agg_estimated else ""
    opex = [
        money(
            "aggregator",
            (
                f"Комиссия агрегатора ({round(aggregator_pct, 1):g}% от "
                f"{agg_rev_total:,.0f} ₽{agg_base_note})"
            ).replace(",", " "),
            aggregator,
            rated=False,
        ),
        money("chemicals", "Химия / моющие", chemicals),
        money("supplies", "Расходники (салфетки/перчатки)", supplies),
        money("rent", "Аренда", manual["rent"]),
        money("utilities", "Коммуналка", manual["utilities"]),
        money("labor_admin", "Админ. ФОТ (управляющий)", manual["labor_admin"]),
        money("marketing", "Маркетинг", manual["marketing"]),
        money("other_opex", "Прочие (IT/ОФД/эквайринг/аморт.)", manual["other_opex"]),
        money("contingency", "Непредвиденные", manual["contingency"]),
        money("total_opex", "Итого OPEX (операционные)", total_opex, rated=False),
    ]

    ebitda_line = {
        "key": "ebitda",
        "label": "EBITDA (до налога и кап-резерва)",
        "kind": "money",
        "rub": round(ebitda, 0),
        "pct": round(ebitda_margin, 1),
        "rating": _rate("ebitda_margin", ebitda_margin, ebitda_margin),
    }
    net_profit_line = {
        "key": "net_profit",
        "label": "Чистая прибыль",
        "kind": "money",
        "rub": round(net_profit, 0),
        "pct": round(net_margin, 1),
        "rating": _rate("net_margin", net_margin, net_margin),
    }
    margin = [
        money(
            "variable_total", "Переменные затраты (растут с продажами)", variable_total, rated=False
        ),
        money("contribution_margin", "Маржинальная прибыль", contribution_margin, rated=False),
        money("fixed_alloc", "Постоянные затраты за период", fixed_alloc, rated=False),
        metric("breakeven_month", "Точка безубыточности, ₽/мес", breakeven_month, "rub"),
        metric("breakeven_day", "Точка безубыточности, ₽/раб. день", breakeven_day, "rub"),
        metric("avg_rev_day", "Средняя выручка/раб. день (факт)", avg_rev_day, "rub"),
    ]

    profit = [
        ebitda_line,
        money("tax", f"− Налог (УСН {tax_pct:g}%)", tax, rated=False),
        money("cap_reserve", "− Кап-резерв", cap_reserve_rub, rated=False),
        net_profit_line,
    ]

    # ── Подневная матрица + сравнение с пред. периодом день-в-день (#1, #4) ──
    # Правило сравнения: тот же тип дня недели (пн↔пн, чт↔чт, сб↔сб), см. _make_prev_mapper.
    labor_day = labor_by_day(df, dt)
    daily = [
        _day_pnl(
            d["date"],
            d,
            del_buckets.get(d["date"], {}),
            months,
            labor_day,
            day_costs,
            agg_by_day.get(d["date"], 0.0),
        )
        for d in days
    ]

    mapper = _make_prev_mapper(period, df, dt, is_custom)
    prev_map = {d["date"]: mapper(date.fromisoformat(d["date"])) for d in days}
    prev_dates_sorted = sorted(prev_map.values())
    prev_summary = None
    if prev_dates_sorted:
        prange_from, prange_to = prev_dates_sorted[0], prev_dates_sorted[-1]
        prev_days_raw = _days_from_db(prange_from, prange_to)
        if not prev_days_raw:
            prev_days_raw = await _days_live(prange_from, prange_to)
        prev_by_date = {r["date"]: r for r in prev_days_raw}
        prev_del_buckets = await delivery_buckets(prange_from, prange_to, OLAP_FIELD_OPEN_DATE)
        prev_months = _load_months(prange_from, prange_to)
        prev_labor_day = labor_by_day(prange_from, prange_to)
        prev_day_costs = _load_day_costs(prange_from, prange_to)
        prev_agg_by_day = _aggregator_rev_by_day(prange_from, prange_to)
        if pay_start is None or prange_to < pay_start:  # #5: та же оценка для пред. периода
            prev_agg_by_day = {
                r["date"]: float(prev_del_buckets.get(r["date"], {}).get("revenue", 0.0))
                for r in prev_days_raw
            }

        prev_rows = []
        prev_marketing = 0.0  # маркетинг прош. периода — в дневной EBITDA его нет, а в
        # KPI-дельте сравниваем с ИТОГОВОЙ (с маркетингом), поэтому вычтем отдельно
        for day in daily:
            pd_date = prev_map[day["date"]]
            row = prev_by_date.get(pd_date.isoformat())
            if row:
                p = _day_pnl(
                    row["date"],
                    row,
                    prev_del_buckets.get(row["date"], {}),
                    prev_months,
                    prev_labor_day,
                    prev_day_costs,
                    prev_agg_by_day.get(row["date"], 0.0),
                )
                pm = prev_months.get((pd_date.year, pd_date.month)) or _default_month(
                    pd_date.year, pd_date.month
                )
                prev_marketing += (
                    pm["marketing"] / calendar.monthrange(pd_date.year, pd_date.month)[1]
                )
                day["prev"] = p
                prev_rows.append(p)
            else:
                day["prev"] = None

        if prev_rows:
            prev_revenue = sum(p["revenue"] for p in prev_rows)
            # с маркетингом — сопоставимо с итоговой EBITDA текущего периода (хедер)
            prev_ebitda = sum(p["ebitda"] for p in prev_rows) - prev_marketing
            # чистая прибыль прош. периода = EBITDA(с марк.) − налог − кап-резерв
            prev_net = (
                prev_ebitda
                - sum(p["tax"] for p in prev_rows)
                - sum(p["cap_reserve"] for p in prev_rows)
            )
            prev_summary = {
                "date_from": prange_from.isoformat(),
                "date_to": prange_to.isoformat(),
                "revenue": prev_revenue,
                "revenue_hall": sum(p["revenue_hall"] for p in prev_rows),
                "revenue_delivery": sum(p["revenue_delivery"] for p in prev_rows),
                "checks": sum(p["checks"] for p in prev_rows),
                "ebitda": round(prev_ebitda, 0),
                "ebitda_margin": (
                    round(prev_ebitda / prev_revenue * 100, 1) if prev_revenue else 0.0
                ),
                "net_profit": round(prev_net, 0),
                "net_margin": (round(prev_net / prev_revenue * 100, 1) if prev_revenue else 0.0),
            }
    else:
        for day in daily:
            day["prev"] = None

    return {
        "period": "custom" if is_custom else period,
        "date_from": df.isoformat(),
        "date_to": dt.isoformat(),
        "active_days": active_days,
        "has_costs": bool(months) or bool(day_costs),
        "aggregator_estimated": agg_estimated,
        "revenue": round(revenue, 0),
        "ebitda": round(ebitda, 0),
        "ebitda_margin": round(ebitda_margin, 1),
        "ebitda_rating": _rate("ebitda_margin", ebitda_margin, ebitda_margin),
        "net_profit": round(net_profit, 0),
        "net_margin": round(net_margin, 1),
        "net_rating": _rate("net_margin", net_margin, net_margin),
        "breakeven": {
            "cm_ratio": round(cm_ratio * 100, 1),
            "fixed_month": round(fixed_month, 0),
            "revenue_month": None if breakeven_month is None else round(breakeven_month, 0),
            "revenue_day": None if breakeven_day is None else round(breakeven_day, 0),
            "avg_rev_day": round(avg_rev_day, 0),
        },
        "prev_summary": prev_summary,
        "daily": daily,
        "sections": [
            {"key": "sales", "label": "Продажи / загрузка", "lines": sales},
            {"key": "production", "label": "Себестоимость производства", "lines": production},
            {"key": "opex", "label": "Операционные расходы", "lines": opex},
            {"key": "margin", "label": "Маржинальность и безубыточность", "lines": margin},
            {"key": "profit", "label": "Прибыль", "lines": profit},
        ],
    }
