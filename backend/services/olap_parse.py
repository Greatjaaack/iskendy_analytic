"""Разбор склейки `field0` из ответа OLAP и группировки «по заказам».

OLAP возвращает group-поля строки склеенными через «, » в `field0.value`. Все
поля кроме последнего (OrderNum/час/категория) запятых не содержат, а вот имя
блюда — может, поэтому хвост всегда склеиваем обратно. Раньше эта логика
дублировалась как `_split4`/`_split5`/`_split` в revenue/plan/dishes.
"""

from constants import (
    OLAP_FIELD_DISH_CATEGORY,
    OLAP_FIELD_DISH_NAME,
    OLAP_FIELD_OPEN_DATE,
    OLAP_FIELD_ORDER_NUM,
)


def split_field(value: str, n: int) -> tuple[str, ...]:
    """`field0` → ровно `n` частей; последняя склеивает хвост (может содержать «, »).

    При нехватке частей возвращает кортеж из `n` пустых строк (как делали
    прежние `_split*`).
    """
    parts = str(value).split(", ")
    if len(parts) < n:
        return ("",) * n
    return (*parts[: n - 1], ", ".join(parts[n - 1 :]))


def split_field_3(value: str) -> tuple[str, str, str]:
    """field0 «OrderNum, Категория, Имя» → 3 части (имя может содержать «, »)."""
    a, b, c = split_field(value, 3)
    return a, b, c


def split_field_4(value: str) -> tuple[str, str, str, str]:
    """field0 «bucket/дата, OrderNum/час, Категория, Имя/Категория» → 4 части."""
    a, b, c, d = split_field(value, 4)
    return a, b, c, d


def split_field_5(value: str) -> tuple[str, str, str, str, str]:
    """field0 «дата, час, OrderNum, Категория, Имя» → 5 частей."""
    a, b, c, d, e = split_field(value, 5)
    return a, b, c, d, e


# ─── Разрезы «по заказам»: дата в группировке ОБЯЗАТЕЛЬНА ────────────────────
# Номер заказа у кассы уникален только внутри дня (в iiko нумерация начинается
# заново каждое утро). Группировка по одному `OrderNum` за период длиннее суток
# склеивает разные заказы с одинаковым номером в один: на реальных данных за
# 01–20.09.2026 из 3 310 чеков получалось 237 «чеков» по 39,7 позиции вместо 2,5.
# От этого врали состав чека, наполненность, сочетаемость и разрез по каналам.
# Поэтому ключ заказа — пара (дата, номер), и собирают его только эти хелперы.
ORDER_KEY_SEP = "|"


def order_group_fields(bucket: str | None = None) -> list[str]:
    """Поля группировки для разреза по заказам: `[дата, (bucket), номер, категория, имя]`.

    `bucket` — дополнительная корзина разреза (час/дата). Дата не дублируется, если
    корзина и есть дата. Имя блюда идёт последним: оно может содержать «, ».
    """
    fields = [OLAP_FIELD_OPEN_DATE]
    if bucket and bucket != OLAP_FIELD_OPEN_DATE:
        fields.append(bucket)
    fields += [OLAP_FIELD_ORDER_NUM, OLAP_FIELD_DISH_CATEGORY, OLAP_FIELD_DISH_NAME]
    return fields


def split_order_row(value: str, bucket: str | None = None) -> tuple[str, str, str, str]:
    """Строка разреза по заказам → `(ключ заказа, корзина, категория, имя)`.

    Ключ заказа — `«дата|номер»`: уникален во времени, в отличие от номера. Корзина —
    значение `bucket`-поля (час), либо дата, если корзины нет или корзина — дата.
    Пустой ключ (битая строка) → все четыре пустые строки, как в `split_field`.
    """
    with_bucket = bool(bucket) and bucket != OLAP_FIELD_OPEN_DATE
    parts = split_field(value, 5 if with_bucket else 4)
    if with_bucket:
        day, bucket_value, num, category, name = parts
    else:
        day, num, category, name = parts
        bucket_value = day
    if not day or not num:
        return "", "", "", ""
    return f"{day}{ORDER_KEY_SEP}{num}", bucket_value, category, name


def order_key_date(order_key: str) -> str:
    """Дата из ключа заказа `«дата|номер»` (пустая строка, если ключ битый)."""
    return order_key.split(ORDER_KEY_SEP, 1)[0] if ORDER_KEY_SEP in order_key else ""
