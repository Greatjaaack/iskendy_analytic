"""Разбор склейки `field0` из ответа OLAP.

OLAP возвращает group-поля строки склеенными через «, » в `field0.value`. Все
поля кроме последнего (OrderNum/час/категория) запятых не содержат, а вот имя
блюда — может, поэтому хвост всегда склеиваем обратно. Раньше эта логика
дублировалась как `_split4`/`_split5`/`_split` в revenue/plan/dishes.
"""


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
