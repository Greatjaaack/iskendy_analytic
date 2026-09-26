"""Расчёт ФОТ по графику смен: за период, по дням и число операционных смен.

ФОТ считается по ФАКТУ выходов из графика (`shifts`), а не по штатному расписанию:
сменная ставка умножается на число смен, месячный оклад делится на календарные дни
месяца и умножается на попавшие в период дни. Операционный ФОТ уходит в P&L как
себестоимость производства, административный — как постоянные расходы, и они не
складываются, чтобы не задвоить (решение владельца).

Вынесено из `routers/schedule.py` (этап 7а аудита): расчёт нужен и странице графика, и
P&L, а сервис не должен зависеть от роутера.
"""

import calendar
from datetime import date

from sqlalchemy import select

from models import Employee, SessionLocal, Shift
from utils import daterange

LABOR_GROUPS = ("operational", "admin")
PAY_TYPES = ("shift", "month")


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
            for d in daterange(df, dt):
                dim = calendar.monthrange(d.year, d.month)[1]
                for e in month_emps:
                    grp = e.labor_group if e.labor_group in out else "operational"
                    out[grp] += float(e.rate or 0) / dim
    return {k: round(v, 2) for k, v in out.items()}


def labor_by_day(df: date, dt: date) -> dict[date, dict[str, float]]:
    """ФОТ по дням за период (для подневной матрицы P&L): {дата: {'operational':₽,'admin':₽}}.

    Та же логика, что `labor_for_period`, но без агрегации — нужна, чтобы посчитать
    P&L на каждый день диапазона (неделя/месяц), а не только суммарно.
    """
    out: dict[date, dict[str, float]] = {}
    for d in daterange(df, dt):
        out[d] = {"operational": 0.0, "admin": 0.0}
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
        for d in daterange(df, dt):
            dim = calendar.monthrange(d.year, d.month)[1]
            for e in month_emps:
                grp = e.labor_group if e.labor_group in out[d] else "operational"
                out[d][grp] += float(e.rate or 0) / dim
    return {k: {kk: round(vv, 2) for kk, vv in v.items()} for k, v in out.items()}


def operational_shifts(df: date, dt: date) -> int:
    """Число ОПЕРАЦИОННЫХ смен (человеко-дней) в периоде — для производительности труда.

    Считает выходы сотрудников с оплатой «за смену» и группой operational (кухня/касса).
    Каждая смена ≈ рабочий день одного человека; человеко-часы = смены × часов в смене.
    Окладники (управляющий) сюда не входят — производительность меряем по операционке.
    """
    with SessionLocal() as db:
        emps = {e.id: e for e in db.execute(select(Employee)).scalars()}
        rows = db.execute(
            select(Shift.employee_id).where(Shift.date >= df, Shift.date <= dt)
        ).scalars()
        n = 0
        for eid in rows:
            e = emps.get(eid)
            if e and e.pay_type == "shift" and (e.labor_group or "operational") == "operational":
                n += 1
        return n
