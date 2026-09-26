"""Роутер «График и ФОТ»: сотрудники, ставки, смены → ФОТ для P&L.

Оплата за смену (`pay_type=shift`): стоимость периода = число смен × ставка.
Оклад (`pay_type=month`): аллоцируется по календарным дням месяца. ФОТ делится на
операционный/административный по `labor_group`. `labor_for_period` вызывается из
`pnl.py` — график заменяет ручной ввод ФОТ в P&L.
"""

import calendar
from datetime import date
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from models import Employee, SessionLocal, Shift

# LABOR_GROUPS/PAY_TYPES реэкспортируются осознанно: на них смотрит тест, который
# сверяет `Literal` в схемах со справочниками (иначе списки тихо разъедутся).
from services.schedule_labor import (  # noqa: F401
    LABOR_GROUPS,
    PAY_TYPES,
    labor_for_period,
)

router = APIRouter(prefix="/api/schedule", tags=["schedule"])


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


@router.get("/employees")
def list_employees():
    with SessionLocal() as db:
        emps = db.execute(select(Employee).order_by(Employee.id)).scalars().all()
        return [_emp_dict(e) for e in emps]


class EmployeeIn(BaseModel):
    """Сотрудник: что можно прислать. Кривой ввод теперь 422, а не 500 в глубине кода."""

    name: str = Field(default="", max_length=120)
    role: str = Field(default="", max_length=120)
    # список обязан совпадать с LABOR_GROUPS ниже — это проверяет тест
    labor_group: Literal["operational", "admin"] = "operational"
    # список обязан совпадать с PAY_TYPES ниже — это проверяет тест
    pay_type: Literal["shift", "month"] = "shift"
    rate: float = Field(default=0, ge=0, le=1_000_000)
    active: bool = True


class EmployeePatch(BaseModel):
    """То же, но все поля необязательны: правим только присланное."""

    name: str | None = Field(default=None, max_length=120)
    role: str | None = Field(default=None, max_length=120)
    labor_group: Literal["operational", "admin"] | None = None
    pay_type: Literal["shift", "month"] | None = None
    rate: float | None = Field(default=None, ge=0, le=1_000_000)
    active: bool | None = None


@router.post("/employees")
def create_employee(body: EmployeeIn):
    with SessionLocal() as db:
        e = Employee(
            name=body.name.strip() or "Без имени",
            role=body.role.strip(),
            labor_group=body.labor_group,
            pay_type=body.pay_type,
            rate=body.rate,
            active=body.active,
        )
        db.add(e)
        db.commit()
        return _emp_dict(e)


@router.put("/employees/{emp_id}")
def update_employee(emp_id: int, body: EmployeePatch):
    with SessionLocal() as db:
        e = db.get(Employee, emp_id)
        if not e:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Сотрудник не найден")
        if body.name is not None:
            e.name = body.name.strip() or e.name
        if body.role is not None:
            e.role = body.role.strip()
        if body.labor_group is not None:
            e.labor_group = body.labor_group
        if body.pay_type is not None:
            e.pay_type = body.pay_type
        if body.rate is not None:
            e.rate = body.rate
        if body.active is not None:
            e.active = body.active
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


class ShiftToggleIn(BaseModel):
    """Смена: сотрудник и день. Раньше отсутствие поля давало 500."""

    employee_id: int = Field(ge=1)
    date: date


@router.post("/shifts/toggle")
def toggle_shift(body: ShiftToggleIn):
    """Переключить смену сотрудника в дне (есть → удалить, нет → создать)."""
    emp_id, d = body.employee_id, body.date
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
