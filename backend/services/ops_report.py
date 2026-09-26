"""Сборка ежедневного операционного отчёта: дни (столбцы) × дейпарты (строки).

Аналог исторического Excel-свода «Ежедневный ОП». По каждой клетке — выручка, чеки,
гости, средний чек и food cost %; справа «Факт за период», «Среднее на активный день» и
доля дейпарта; ниже — food cost по группам категорий (Еда / Напитки / Алкоголь). Если
задан план (`daypart_plan`), добавляются колонки «План» и «% плана».

⚠️ **Ключ заказа — пара (дата, номер).** Номер уникален только внутри дня, а корзины дней
сворачиваются в «Факт за период» объединением множеств. По одному номеру отчёт показывал
237 чеков вместо 3 310 и средний чек 14 312 ₽ вместо 1 025 ₽ — при верной выручке, поэтому
ошибку не замечали больше года (найдена смоук-тестом 26.09.2026).

Вынесено из `routers/revenue.py` (этап 7а аудита): 230 строк расчёта в роутере мешали
читать остальные разрезы, а тестировать их можно было только через HTTP.
"""

from datetime import date

from sqlalchemy import select

from constants import (
    CATEGORY_GROUP_ORDER,
    DAY_NAMES_RU,
    DAYPARTS,
    ORDER_STATUS_CATEGORY,
    WEEKDAY_TO_GROUP,
)
from models import DaypartPlan, SessionLocal
from services.daypart import category_group, hour_to_daypart
from services.olap_parse import split_field_5
from services.ops_aggregation import (
    blank_bucket,
    finalize,
    finalize_cat,
    period_plan,
    plan_pct,
)
from utils import daterange, is_delivery


async def build_ops_report(rows: list[dict], df: date, dt: date, include_delivery: bool) -> dict:
    """Собрать отчёт из строк разреза `[дата, час, заказ, категория, имя]`.

    Строки приходят готовыми: запрос к источнику делает роутер, а здесь — только расчёт.
    Функция остаётся `async`, потому что план на период читается из БД.
    """
    h2dp = hour_to_daypart()
    # накопитель: (дата, ключ дейпарта) → bucket
    agg: dict[tuple[str, str], dict] = {}
    # food cost по группам категорий (Еда/Напитки/Алкоголь) на дейпарт — нижний блок свода
    cat_agg: dict[tuple[str, str], dict] = (
        {}
    )  # (ключ дейпарта, группа) → {revenue,cost,rev_with_cost}

    for r in rows:
        ds, hs, ordernum, category, name = split_field_5(r.get("field0", {}).get("value", ""))
        if not name or category == ORDER_STATUS_CATEGORY:
            continue
        if not include_delivery and is_delivery(category, name):
            continue
        try:
            hour = int(hs)
        except ValueError:
            continue
        dp = h2dp.get(hour)
        if dp is None:
            continue
        rev = float(r.get("field1", {}).get("value", 0) or 0)
        guests = float(r.get("field3", {}).get("value", 0) or 0)
        cost = float(r.get("field4", {}).get("value", 0) or 0)
        key = (ds, dp)
        b = agg.get(key)
        if b is None:
            b = agg[key] = blank_bucket()
        b["revenue"] += rev
        # Ключ заказа — ПАРА (дата, номер): номер уникален только внутри дня, а корзины
        # дней сворачиваются в «Факт за период» объединением множеств. По одному номеру
        # 20 дней давали 237 «чеков» вместо 3 310 и средний чек 14 312 ₽ вместо 1 025 ₽
        # (выручка при этом была верной, поэтому ошибку никто не замечал).
        b["orders"].add((ds, ordernum))
        b["guests"].setdefault((ds, ordernum), guests)
        # группа категории для food cost (дейпарт × Еда/Напитки/Алкоголь)
        ck = (dp, category_group(category))
        cb = cat_agg.get(ck)
        if cb is None:
            cb = cat_agg[ck] = {"revenue": 0.0, "cost": 0.0, "rev_with_cost": 0.0}
        cb["revenue"] += rev
        # food cost % считаем от ВСЕЙ выручки окна (честный P&L-знаменатель, сходится
        # с P&L). rev_with_cost копит только прокостованную выручку (cost>0) → coverage
        # показывает дыру: у доставочных дублей («…доставка»/«_д») iiko не ставит
        # ProductCostBase, поэтому на окнах с доставкой coverage < 100%.
        b["cost"] += cost
        cb["cost"] += cost
        if cost > 0:
            b["rev_with_cost"] += rev
            cb["rev_with_cost"] += rev

    # столбцы — все календарные дни периода
    days = []
    for d in daterange(df, dt):
        days.append(
            {
                "date": d.isoformat(),
                "dom": d.day,
                "weekday": DAY_NAMES_RU[d.weekday()],
            }
        )
    day_keys = [x["date"] for x in days]

    # число дней каждой группы дня недели в периоде — для масштабирования плана
    group_day_count: dict[str, int] = {}
    for x in days:
        grp = WEEKDAY_TO_GROUP.get(date.fromisoformat(x["date"]).weekday())
        if grp:
            group_day_count[grp] = group_day_count.get(grp, 0) + 1
    total_days = len(days)
    with SessionLocal() as db:
        plan_rows = {
            (r.daypart_key, r.weekday_group): r for r in db.execute(select(DaypartPlan)).scalars()
        }
    has_plan = any((r.revenue or 0) for r in plan_rows.values())

    grand_revenue = sum(b["revenue"] for b in agg.values()) or 0.0

    dayparts = []
    for dp in DAYPARTS:
        cells = {}
        tot = blank_bucket()
        active = 0
        for dk in day_keys:
            b = agg.get((dk, dp["key"]))
            if b is None:
                continue
            cells[dk] = finalize(b)
            if b["revenue"] > 0 or b["orders"]:
                active += 1
            # копим в total
            tot["revenue"] += b["revenue"]
            tot["cost"] += b["cost"]
            tot["rev_with_cost"] += b["rev_with_cost"]
            tot["orders"] |= b["orders"]
            tot["guests"].update(b["guests"])
        total = finalize(tot)
        # Среднее — на активный день (как в Excel «Среднее»)
        avg_per_day = {
            "revenue": round(total["revenue"] / active, 2) if active else 0,
            "checks": round(total["checks"] / active, 1) if active else 0,
            "guests": round(total["guests"] / active, 1) if active else 0,
            "avg_check": total["avg_check"],
        }
        # food cost по группам категорий внутри дейпарта (Еда/Напитки/Алкоголь)
        cats = {}
        for grp in CATEGORY_GROUP_ORDER:
            cb = cat_agg.get((dp["key"], grp))
            if cb and cb["revenue"] > 0:
                cats[grp] = finalize_cat(cb, total["revenue"])
        dp_plan = period_plan(plan_rows, dp["key"], group_day_count, total_days)
        dayparts.append(
            {
                "key": dp["key"],
                "label": dp["label"],
                "range": dp["range"],
                "cells": cells,
                "total": total,
                "avg_per_day": avg_per_day,
                "active_days": active,
                "revenue_share": (
                    round(total["revenue"] / grand_revenue * 100, 1) if grand_revenue else 0
                ),
                "categories": cats,
                "plan": dp_plan,
                "plan_pct": plan_pct(total, dp_plan),
            }
        )

    # строка Итого — сумма по всем дейпартам в каждый день
    tot_cells = {}
    grand = blank_bucket()
    active_total = 0
    for dk in day_keys:
        acc = blank_bucket()
        has = False
        for dp in DAYPARTS:
            b = agg.get((dk, dp["key"]))
            if b is None:
                continue
            has = True
            acc["revenue"] += b["revenue"]
            acc["cost"] += b["cost"]
            acc["rev_with_cost"] += b["rev_with_cost"]
            acc["orders"] |= b["orders"]
            acc["guests"].update(b["guests"])
        if has:
            tot_cells[dk] = finalize(acc)
            active_total += 1
            grand["revenue"] += acc["revenue"]
            grand["cost"] += acc["cost"]
            grand["rev_with_cost"] += acc["rev_with_cost"]
            grand["orders"] |= acc["orders"]
            grand["guests"].update(acc["guests"])
    grand_total = finalize(grand)
    # план на период по всей точке = сумма планов дейпартов
    grand_plan = {m: round(sum(dp["plan"][m] for dp in dayparts), 2) for m in ("revenue", "guests")}
    grand_plan["avg_check"] = (
        round(grand_plan["revenue"] / grand_plan["guests"], 2) if grand_plan["guests"] else 0
    )
    totals = {
        "cells": tot_cells,
        "total": grand_total,
        "avg_per_day": {
            "revenue": round(grand_total["revenue"] / active_total, 2) if active_total else 0,
            "checks": round(grand_total["checks"] / active_total, 1) if active_total else 0,
            "guests": round(grand_total["guests"] / active_total, 1) if active_total else 0,
            "avg_check": grand_total["avg_check"],
        },
        "plan": grand_plan,
        "plan_pct": plan_pct(grand_total, grand_plan),
    }

    # сводный блок food cost по группам категорий (нижний блок Excel-свода «ОП»)
    cat_total_acc: dict[str, dict] = {}
    for (_dpk, grp), cb in cat_agg.items():
        a = cat_total_acc.setdefault(grp, {"revenue": 0.0, "cost": 0.0, "rev_with_cost": 0.0})
        a["revenue"] += cb["revenue"]
        a["cost"] += cb["cost"]
        a["rev_with_cost"] += cb["rev_with_cost"]
    cat_grand_rev = sum(a["revenue"] for a in cat_total_acc.values()) or 0.0
    category_groups = [
        g for g in CATEGORY_GROUP_ORDER if cat_total_acc.get(g, {}).get("revenue", 0)
    ]
    category_totals = {g: finalize_cat(cat_total_acc[g], cat_grand_rev) for g in category_groups}

    return {
        "days": days,
        "dayparts": dayparts,
        "totals": totals,
        "category_groups": category_groups,
        "category_totals": category_totals,
        "has_plan": has_plan,
    }
