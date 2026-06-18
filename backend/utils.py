"""Мелкие общие хелперы, переиспользуемые роутерами/синком."""

import re
from datetime import date, timedelta


def normalize_name(s: str) -> str:
    """Нормализация имени для сопоставления (lower, ё→е, схлоп пробелов).

    Версия без среза префикса «п/ф» — для блюд/привязок. В импортёре ТТК
    используется своя расширенная нормализация (`ttk_matrix._norm`).
    """
    return re.sub(r"\s+", " ", str(s or "").strip().lower().replace("ё", "е"))


def period_range(period: str, date_from: str | None, date_to: str | None) -> tuple[date, date]:
    """Границы периода. Произвольный диапазон (date_from/date_to) приоритетнее period."""
    if date_from and date_to:
        return date.fromisoformat(date_from), date.fromisoformat(date_to)
    today = date.today()
    if period == "day":
        return today, today
    if period == "week":
        return today - timedelta(days=6), today
    return today - timedelta(days=29), today
