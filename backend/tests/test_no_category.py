"""Позиции без меню-категории — это продажи, а не мусор.

У точки без категории заведены напитки комбо «Айран_», «Кола_», «Кола б/с_»: за
сентябрь 2026 это ~2 150 штук, четверть всех позиций. «Состав чека» их выбрасывал —
доля напитков была занижена, а чеки из одного такого напитка пропадали (3 524 товарных
чека против 3 727 в KPI). В остальных разрезах они шли строкой без подписи.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from constants import NO_CATEGORY  # noqa: E402
from services.dish_cuts import build_check_composition  # noqa: E402
from utils import display_category  # noqa: E402

DAY = "2026-09-20"


def row(num: str, category: str, name: str, qty: float, total: float) -> dict:
    return {
        "field0": {"value": f"{DAY}, 13, {num}, {category}, {name}"},
        "field1": {"value": qty},
        "field2": {"value": total},
    }


def test_пустая_категория_подписана():
    assert display_category("") == NO_CATEGORY
    assert display_category(None) == NO_CATEGORY
    assert display_category("Меню") == "Допы и соусы"
    assert display_category("Дюрюмы") == "Дюрюмы"


def test_состав_чека_учитывает_позиции_без_категории():
    rows = [
        row("1", "Дюрюмы", "Балык", 1, 1180),
        row("1", "", "Айран_", 1, 380),
        row("2", "", "Кола_", 1, 190),  # чек из одного напитка комбо
        row("2", "Статус", "С собой", 1, 0),  # служебная строка — не товар
    ]
    res = build_check_composition(rows, mod_cats=set(), include_delivery=True)
    assert res["total"]["checks"] == 2
    shares = {cat: v["qty"] for cat, v in res["total"]["by"].items()}
    # чек 1: 50 % Дюрюмы / 50 % без категории; чек 2: 100 % без категории
    assert shares == {NO_CATEGORY: 75.0, "Дюрюмы": 25.0}
