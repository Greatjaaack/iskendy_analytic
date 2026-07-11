"""Аккумуляторы и финализаторы ежедневного ОП-отчёта и слоя плана.

«Движок» `get_ops_report`: накопитель метрик окна (выручка/с-с/чеки/гости),
свёртка в показатели (food cost % = iiko-кост позиций `ProductCostBase` ÷ вся
выручка окна; coverage — доля выручки с известной с-с, < 100% там, где доставочные
позиции без коста) и расчёт плана на период из дневных норм. Вынесено из revenue.py.
"""


def blank_bucket() -> dict:
    return {
        "revenue": 0.0,
        "cost": 0.0,
        "rev_with_cost": 0.0,  # выручка с известной с-с (знаменатель кост%; = вся выручка)
        "orders": set(),
        "guests": {},  # OrderNum → гостей (берём раз на заказ)
    }


def finalize(b: dict) -> dict:
    """Свёртка накопителя в метрики: выручка/чеки/гости/ср.чек/кост%/покрытие."""
    rev = round(b["revenue"], 2)
    checks = len(b["orders"])
    guests = int(sum(b["guests"].values()))
    cost = round(b["cost"], 2)
    rwc = b["rev_with_cost"]
    return {
        "revenue": rev,
        "checks": checks,
        "guests": guests,
        "avg_check": round(rev / checks, 2) if checks else 0,
        "cost": cost,
        # food cost % — от ВСЕЙ выручки окна (честный знаменатель, сходится с P&L);
        # coverage = доля выручки с известной iiko-с/с (< 100% там, где доставочные
        # позиции без ProductCostBase) — сигнал надёжности процента
        "food_cost_pct": round(cost / rev * 100, 1) if rev else None,
        "coverage": round(rwc / rev * 100, 1) if rev else 0,
    }


def finalize_cat(cb: dict, base_revenue: float) -> dict:
    """Свёртка накопителя группы категорий: выручка/кост%/покрытие/доля в выручке."""
    rev = round(cb["revenue"], 2)
    cost = round(cb["cost"], 2)
    rwc = cb["rev_with_cost"]
    return {
        "revenue": rev,
        "cost": cost,
        "food_cost_pct": round(cost / rev * 100, 1) if rev else None,
        "coverage": round(rwc / rev * 100, 1) if rev else 0,
        "revenue_share": round(rev / base_revenue * 100, 1) if base_revenue else 0,
    }


def period_plan(
    plan_rows: dict, dp_key: str, group_day_count: dict[str, int], total_days: int
) -> dict:
    """План на период для дейпарта: дневная норма × число подходящих дней группы.

    Выручка/гости — сумма норм по дням периода; средний чек — день-взвешенное среднее
    нормы (он не суммируется). Так `% к плану` корректен для любого периода.
    """
    rev = guests = 0.0
    avg_weighted = 0.0
    for grp, n in group_day_count.items():
        r = plan_rows.get((dp_key, grp))
        if not r:
            continue
        rev += (r.revenue or 0) * n
        guests += (r.guests or 0) * n
        avg_weighted += (r.avg_check or 0) * n
    return {
        "revenue": round(rev, 2),
        "guests": round(guests, 1),
        "avg_check": round(avg_weighted / total_days, 2) if total_days else 0,
    }


def plan_pct(fact: dict, plan: dict) -> dict:
    """{метрика: % выполнения плана} (None, если плана нет)."""
    return {
        m: (round(fact[m] / plan[m] * 100, 1) if plan.get(m) else None)
        for m in ("revenue", "avg_check", "guests")
    }
