"""Операционные окна дня (дейпарты) и группировка категорий для food cost.

Свёртка часа в дейпарт (`DAYPARTS` из `constants`) и отнесение меню-категории
к группе (Еда/Напитки/Алкоголь) раньше дублировались в `revenue` и `plan`.
"""

from constants import (
    ALCOHOL_CATEGORIES,
    CATEGORY_GROUP_ALCOHOL,
    CATEGORY_GROUP_DRINK,
    CATEGORY_GROUP_FOOD,
    DAYPARTS,
    DRINK_CATEGORIES,
)


def hour_to_daypart() -> dict[int, str]:
    """{час → ключ дейпарта} из `DAYPARTS` (для свёртки часов в окна дня)."""
    out: dict[int, str] = {}
    for dp in DAYPARTS:
        for h in dp["hours"]:
            out[h] = dp["key"]
    return out


def category_group(category: str) -> str:
    """Меню-категория iiko → группа для food cost (Еда / Напитки / Алкоголь)."""
    if category in DRINK_CATEGORIES:
        return CATEGORY_GROUP_DRINK
    if category in ALCOHOL_CATEGORIES:
        return CATEGORY_GROUP_ALCOHOL
    return CATEGORY_GROUP_FOOD
