"""Мелкие общие хелперы, переиспользуемые роутерами/синком."""

import re
from datetime import date, timedelta

# Постфикс в названии продажи iiko, помечающий доставочную версию позиции:
# «Напиток_д» — это «Напиток», проданный в доставку (отдельная POS-позиция).
DELIVERY_SUFFIX = "_д"


def split_delivery(name: str) -> tuple[str, bool]:
    """('Напиток_д') → ('Напиток', True); ('Напиток') → ('Напиток', False).

    Срезает постфикс `_д` (доставка), чтобы доставочная позиция сопоставлялась с той
    же ТТК, что и обычная, и чтобы можно было пометить канал «доставка».
    """
    s = str(name or "").strip()
    if s.lower().endswith(DELIVERY_SUFFIX):
        return s[: -len(DELIVERY_SUFFIX)].rstrip(), True
    return s, False


def normalize_phone(raw: str) -> str:
    """Валидирует и нормализует российский номер → «+7XXXXXXXXXX».

    Принимает любой ввод с разделителями (пробелы, скобки, дефисы), а также формы
    `8XXXXXXXXXX`, `+7XXXXXXXXXX`, `XXXXXXXXXX`. Бросает ValueError на некорректном.
    """
    digits = re.sub(r"\D", "", str(raw or ""))
    if len(digits) == 11 and digits[0] in ("7", "8"):
        digits = digits[1:]
    if len(digits) != 10:
        raise ValueError("Некорректный номер: ожидается российский, 10 цифр (без кода +7/8)")
    return "+7" + digits


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
