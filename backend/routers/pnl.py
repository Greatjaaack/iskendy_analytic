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

from datetime import date
from datetime import date as Date
from datetime import timedelta

import httpx
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select

from constants import (
    DAY_NAMES_RU,
    PNL_DAY_COST_FIELDS,
    PNL_MANUAL_FIELDS,
    PNL_RATE_FIELDS,
)
from models import PnlDayCost, PnlMonth, SessionLocal
from services.pnl_calc import (
    build_pnl,
    day_var_costs,
    default_month,
    load_day_costs,
    load_months,
    row_to_dict,
)
from utils import period_range

router = APIRouter(prefix="/api/pnl", tags=["pnl"])


@router.get("/costs")
def get_costs(year: int = Query(...), month: int = Query(..., ge=1, le=12)):
    """Ручные затраты за один месяц — для редактора (значения по умолчанию, если нет)."""
    with SessionLocal() as db:
        row = db.execute(
            select(PnlMonth).where(PnlMonth.year == year, PnlMonth.month == month)
        ).scalar_one_or_none()
    values = row_to_dict(row) if row else default_month(year, month)
    return {
        "values": values,
        "manual_fields": [{"key": k, "label": lbl} for k, lbl in PNL_MANUAL_FIELDS],
        "rate_fields": [{"key": k, "label": lbl} for k, lbl in PNL_RATE_FIELDS],
    }


class CostsIn(BaseModel):
    """Затраты месяца: год, месяц и ₽-поля из `PNL_MANUAL_FIELDS` + ставки.

    Раньше было `payload: dict` и `int(payload.get("year"))` — запрос без года отвечал
    500 вместо 422, а отрицательная аренда сохранялась молча.
    """

    model_config = {"extra": "ignore"}

    year: int = Field(ge=2020, le=2100)
    month: int = Field(ge=1, le=12)
    tax_pct: float = Field(default=6, ge=0, le=100)
    aggregator_pct: float = Field(default=0, ge=0, le=100)
    motivation_pct: float = Field(default=15, ge=0, le=100)
    work_hours: int = Field(default=12, ge=1, le=24)
    amounts: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _collect_amounts(cls, data):
        """₽-поля приходят плоско (`rent`, `utilities`, …) — собираем их в один словарь."""
        if not isinstance(data, dict):
            return data
        known = {k for k, _ in PNL_MANUAL_FIELDS}
        data = dict(data)
        data["amounts"] = {
            k: float(v or 0) for k, v in data.items() if k in known and v is not None
        }
        return data


@router.put("/costs")
def save_costs(body: CostsIn):
    """Сохранить затраты месяца."""
    year, month = body.year, body.month
    with SessionLocal() as db:
        row = db.execute(
            select(PnlMonth).where(PnlMonth.year == year, PnlMonth.month == month)
        ).scalar_one_or_none()
        if row is None:
            row = PnlMonth(year=year, month=month)
            db.add(row)
        for f, _ in PNL_MANUAL_FIELDS:
            setattr(row, f, max(0.0, body.amounts.get(f, 0.0)))
        row.tax_pct = body.tax_pct
        row.aggregator_pct = body.aggregator_pct
        row.motivation_pct = body.motivation_pct
        row.work_hours = body.work_hours
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
    stored = load_day_costs(df, dt)
    months = load_months(df, dt)
    days = []
    d = df
    while d <= dt:
        iso = d.isoformat()
        row = stored.get(iso)
        vals = row if row is not None else day_var_costs(d, {}, months)
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


class DayCostIn(BaseModel):
    """Дневные переменные затраты одного дня (списания/упаковка/химия/расходники)."""

    model_config = {"extra": "ignore"}

    date: Date
    amounts: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _collect_amounts(cls, data):
        if not isinstance(data, dict):
            return data
        known = {k for k, _ in PNL_DAY_COST_FIELDS}
        data = dict(data)
        data["amounts"] = {
            k: float(v or 0) for k, v in data.items() if k in known and v is not None
        }
        return data


class DayCostsIn(BaseModel):
    days: list[DayCostIn] = Field(default_factory=list, max_length=400)


@router.put("/day-costs")
def save_day_costs(body: DayCostsIn):
    """Сохранить дневные затраты (по одному дню на строку)."""
    with SessionLocal() as db:
        for r in body.days:
            iso = r.date.isoformat()
            existing = db.get(PnlDayCost, iso)
            if existing is None:
                existing = PnlDayCost(date=iso)
                db.add(existing)
            for k, _ in PNL_DAY_COST_FIELDS:
                setattr(existing, k, max(0.0, r.amounts.get(k, 0.0)))
        db.commit()
    return {"ok": True}


@router.get("")
async def get_pnl(
    period: str = Query("month", enum=["day", "week", "month"]),
    date_from: str | None = None,
    date_to: str | None = None,
    include_delivery: bool = True,
):
    """P&L за период: выручка и food cost из БД, постоянные затраты — из `PnlMonth`.

    Расчёт — `services/pnl_calc.build_pnl`; здесь только разбор периода.
    """
    df, dt = period_range(period, date_from, date_to)
    is_custom = bool(date_from and date_to)
    return await build_pnl(period, df, dt, is_custom, include_delivery)
