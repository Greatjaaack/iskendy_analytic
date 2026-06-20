"""Мелкие общие хелперы, переиспользуемые роутерами/синком."""

import re
from datetime import date, timedelta


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


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_email(raw: str) -> str:
    """Валидирует email (мягко). Пусто → ''. Бросает ValueError на явно неверном."""
    v = str(raw or "").strip()
    if v and not _EMAIL_RE.match(v):
        raise ValueError("Некорректный email")
    return v


def classify_channel(order_type: str) -> str:
    """Эвристика канала по значению OrderType (только для диагностики `/order-types`).

    В реальном разрезе канал берётся из категории «Доставка» и модификатора «Статус»
    заказа, а не отсюда — у этой точки OrderType почти всегда пуст.
    """
    t = str(order_type or "").lower()
    if "достав" in t or "курьер" in t or "delivery" in t:
        return "доставка"
    if "вынос" in t or "собой" in t or "самовывоз" in t or "pickup" in t or "take" in t:
        return "с собой"
    return "в зале"


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
    # «месяц» = с 1-го числа текущего месяца по сегодня (а не последние 30 дней)
    return today.replace(day=1), today
