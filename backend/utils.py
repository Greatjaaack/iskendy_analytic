"""Мелкие общие хелперы, переиспользуемые роутерами/синком."""

import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from config import settings
from constants import CATEGORY_DISPLAY, DELIVERY_CATEGORY, DELIVERY_NAME_MARKER


def display_category(name: str | None) -> str:
    """Отображаемое имя меню-категории (переименование на дашборде, см. CATEGORY_DISPLAY).

    Применяется на выходе разрезов и к подписям, и к ключам (чтобы drill-down и матч
    категорий между виджетами не ломались). Неизвестные имена возвращаются как есть.
    """
    return CATEGORY_DISPLAY.get(name or "", name or "")


def is_delivery(category: str | None, name: str | None) -> bool:
    """Позиция продана в доставку: меню-категория «Доставка» ИЛИ имя содержит `_д`.

    Единое бизнес-правило детекта доставки — используется во всех revenue/dishes-разрезах
    и при отсеве по галке «без доставки». Постфикс/префикс `_д` ищем как токен в любом месте
    имени (регистронезависимо), категорию — точным совпадением.
    """
    if category == DELIVERY_CATEGORY:
        return True
    return DELIVERY_NAME_MARKER in str(name or "").lower()


def today() -> date:
    """Сегодняшняя дата в часовом поясе ресторана (`settings.timezone`).

    Используем её вместо `date.today()`, который берёт TZ контейнера (в Docker — UTC),
    из-за чего «сегодня» перекатывалось бы не в местную полночь и текущий день мог быть
    неполным/смещённым. Погода и расписание синков опираются на тот же пояс.
    """
    return datetime.now(ZoneInfo(settings.timezone)).date()


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
    now = today()
    if period == "day":
        return now, now
    if period == "week":
        # «неделя» = с понедельника текущей недели по сегодня (а не последние 7 дней).
        # weekday(): Пн=0 … Вс=6 — отступаем до ближайшего понедельника.
        return now - timedelta(days=now.weekday()), now
    # «месяц» = с 1-го числа текущего месяца по сегодня (а не последние 30 дней)
    return now.replace(day=1), now


def prev_period_range(period: str, df: date, dt: date, is_custom: bool) -> tuple[date, date]:
    """Границы предыдущего сопоставимого периода (для KPI-дельт «к пр. периоду»).

    Пресет «месяц» (MTD) сравниваем с **тем же отрезком прошлого месяца** (1-е число
    прошлого месяца по тот же день месяца; если прошлый месяц короче — по его последний
    день), а не со скользящим окном — иначе MTD «1–22 июня» сравнивался бы с «10–31 мая».
    День/неделя/произвольный диапазон → окно той же длины вплотную перед текущим.
    """
    if period == "month" and not is_custom:
        prev_last = df - timedelta(days=1)  # последний день прошлого месяца
        prev_df = prev_last.replace(day=1)
        prev_dt = prev_df.replace(day=min(dt.day, prev_last.day))
        return prev_df, prev_dt
    if period == "week" and not is_custom:
        # «неделя» (Пн…сегодня) сравнивается с тем же отрезком прошлой недели (сдвиг 7 дней),
        # чтобы сопоставлять одинаковые дни недели, а не скользящее окно.
        return df - timedelta(days=7), dt - timedelta(days=7)
    span = (dt - df).days
    prev_dt = df - timedelta(days=1)
    prev_df = prev_dt - timedelta(days=span)
    return prev_df, prev_dt
