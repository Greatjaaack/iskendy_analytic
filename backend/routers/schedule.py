"""Роутер «График и ФОТ»: сотрудники, ставки, смены → ФОТ для P&L.

Оплата за смену (`pay_type=shift`): стоимость периода = число смен × ставка.
Оклад (`pay_type=month`): аллоцируется по календарным дням месяца. ФОТ делится на
операционный/административный по `labor_group`. `labor_for_period` вызывается из
`pnl.py` — график заменяет ручной ввод ФОТ в P&L.
"""

import calendar
from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import delete, select

from models import Employee, SessionLocal, Shift

router = APIRouter(prefix="/api/schedule", tags=["schedule"])

LABOR_GROUPS = ("operational", "admin")
PAY_TYPES = ("shift", "month")


def _emp_dict(e: Employee) -> dict:
    return {
        "id": e.id,
        "name": e.name,
        "role": e.role or "",
        "labor_group": e.labor_group,
        "pay_type": e.pay_type,
        "rate": float(e.rate or 0),
        "active": bool(e.active),
    }


def labor_for_period(df: date, dt: date) -> dict[str, float]:
    """ФОТ за период по группам: {'operational': ₽, 'admin': ₽}.

    shift-сотрудники: число смен в [df, dt] × ставка. month-сотрудники (оклад):
    сумма по дням периода оклад ÷ календарных дней месяца.
    """
    out = {"operational": 0.0, "admin": 0.0}
    with SessionLocal() as db:
        # ВСЕ сотрудники (в т.ч. неактивные): смена — это факт, её отработали и оплатили,
        # поэтому сменный ФОТ считаем по всем, у кого есть смены в периоде. Иначе пометка
        # «неактивен» задним числом стирала бы их ФОТ из ПРОШЛЫХ периодов (EBITDA скакала
        # бы вверх). `active` ограничивает только окладников (см. ниже).
        emps = {e.id: e for e in db.execute(select(Employee)).scalars()}
        # shift: считаем смены в диапазоне
        rows = db.execute(
            select(Shift.employee_id).where(Shift.date >= df, Shift.date <= dt)
        ).scalars()
        shift_counts: dict[int, int] = {}
        for eid in rows:
            shift_counts[eid] = shift_counts.get(eid, 0) + 1
        for eid, cnt in shift_counts.items():
            e = emps.get(eid)
            if e and e.pay_type == "shift":
                out[e.labor_group if e.labor_group in out else "operational"] += cnt * float(
                    e.rate or 0
                )
        # month (оклад): только активные — уволенный окладник больше не начисляется
        month_emps = [e for e in emps.values() if e.pay_type == "month" and e.active]
        if month_emps:
            d = df
            while d <= dt:
                dim = calendar.monthrange(d.year, d.month)[1]
                for e in month_emps:
                    grp = e.labor_group if e.labor_group in out else "operational"
                    out[grp] += float(e.rate or 0) / dim
                d += timedelta(days=1)
    return {k: round(v, 2) for k, v in out.items()}


def labor_by_day(df: date, dt: date) -> dict[date, dict[str, float]]:
    """ФОТ по дням за период (для подневной матрицы P&L): {дата: {'operational':₽,'admin':₽}}.

    Та же логика, что `labor_for_period`, но без агрегации — нужна, чтобы посчитать
    P&L на каждый день диапазона (неделя/месяц), а не только суммарно.
    """
    out: dict[date, dict[str, float]] = {}
    d = df
    while d <= dt:
        out[d] = {"operational": 0.0, "admin": 0.0}
        d += timedelta(days=1)
    with SessionLocal() as db:
        # ВСЕ сотрудники (в т.ч. неактивные) — сменный ФОТ по факту смен (см.
        # labor_for_period); `active` ограничивает только окладников.
        emps = {e.id: e for e in db.execute(select(Employee)).scalars()}
        rows = db.execute(
            select(Shift.employee_id, Shift.date).where(Shift.date >= df, Shift.date <= dt)
        )
        for eid, sdate in rows:
            e = emps.get(eid)
            if e and e.pay_type == "shift" and sdate in out:
                grp = e.labor_group if e.labor_group in out[sdate] else "operational"
                out[sdate][grp] += float(e.rate or 0)
        month_emps = [e for e in emps.values() if e.pay_type == "month" and e.active]
        d = df
        while d <= dt:
            dim = calendar.monthrange(d.year, d.month)[1]
            for e in month_emps:
                grp = e.labor_group if e.labor_group in out[d] else "operational"
                out[d][grp] += float(e.rate or 0) / dim
            d += timedelta(days=1)
    return {k: {kk: round(vv, 2) for kk, vv in v.items()} for k, v in out.items()}


@router.get("/employees")
def list_employees():
    with SessionLocal() as db:
        emps = db.execute(select(Employee).order_by(Employee.id)).scalars().all()
        return [_emp_dict(e) for e in emps]


@router.post("/employees")
def create_employee(payload: dict):
    with SessionLocal() as db:
        e = Employee(
            name=(payload.get("name") or "").strip() or "Без имени",
            role=(payload.get("role") or "").strip(),
            labor_group=(
                payload.get("labor_group")
                if payload.get("labor_group") in LABOR_GROUPS
                else "operational"
            ),
            pay_type=payload.get("pay_type") if payload.get("pay_type") in PAY_TYPES else "shift",
            rate=float(payload.get("rate", 0) or 0),
            active=bool(payload.get("active", True)),
        )
        db.add(e)
        db.commit()
        return _emp_dict(e)


@router.put("/employees/{emp_id}")
def update_employee(emp_id: int, payload: dict):
    with SessionLocal() as db:
        e = db.get(Employee, emp_id)
        if not e:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Сотрудник не найден")
        if "name" in payload:
            e.name = (payload.get("name") or "").strip() or e.name
        if "role" in payload:
            e.role = (payload.get("role") or "").strip()
        if payload.get("labor_group") in LABOR_GROUPS:
            e.labor_group = payload["labor_group"]
        if payload.get("pay_type") in PAY_TYPES:
            e.pay_type = payload["pay_type"]
        if "rate" in payload:
            e.rate = float(payload.get("rate", 0) or 0)
        if "active" in payload:
            e.active = bool(payload["active"])
        db.commit()
        return _emp_dict(e)


@router.delete("/employees/{emp_id}")
def delete_employee(emp_id: int):
    with SessionLocal() as db:
        e = db.get(Employee, emp_id)
        if not e:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Сотрудник не найден")
        db.execute(delete(Shift).where(Shift.employee_id == emp_id))
        db.delete(e)
        db.commit()
        return {"ok": True}


@router.get("/shifts")
def get_shifts(year: int = Query(...), month: int = Query(..., ge=1, le=12)):
    """Смены за месяц: список {employee_id, date}. Для сетки графика."""
    df = date(year, month, 1)
    dt = date(year, month, calendar.monthrange(year, month)[1])
    with SessionLocal() as db:
        rows = db.execute(select(Shift).where(Shift.date >= df, Shift.date <= dt)).scalars()
        return [{"employee_id": s.employee_id, "date": s.date.isoformat()} for s in rows]


@router.post("/shifts/toggle")
def toggle_shift(payload: dict):
    """Переключить смену сотрудника в дне (есть → удалить, нет → создать)."""
    emp_id = int(payload.get("employee_id"))
    d = date.fromisoformat(payload["date"])
    with SessionLocal() as db:
        existing = db.execute(
            select(Shift).where(Shift.employee_id == emp_id, Shift.date == d)
        ).scalar_one_or_none()
        if existing:
            db.delete(existing)
            db.commit()
            return {"on": False}
        db.add(Shift(employee_id=emp_id, date=d))
        db.commit()
        return {"on": True}


@router.get("/labor")
def labor_summary(year: int = Query(...), month: int = Query(..., ge=1, le=12)):
    """Сводка ФОТ за месяц (для страницы графика): операционный/админ/итого + смены.

    `total` — это ФОТ, который уходит в P&L (только операционный). Административный
    ФОТ в P&L не идёт — он уже учтён как постоянные расходы (ручное поле в «Затраты»),
    поэтому в `total` не суммируется (решение пользователя, во избежание задвоения).
    """
    df = date(year, month, 1)
    dt = date(year, month, calendar.monthrange(year, month)[1])
    labor = labor_for_period(df, dt)
    return {
        "year": year,
        "month": month,
        "operational": labor["operational"],
        "admin": labor["admin"],
        "total": round(labor["operational"], 2),
    }
