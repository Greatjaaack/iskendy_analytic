"""Общие хелперы дат: одна реализация вместо 14 ручных циклов `while d <= dt`."""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils import daterange, months_in  # noqa: E402


def test_дни_включительно_с_обоих_концов():
    assert list(daterange(date(2026, 9, 29), date(2026, 10, 2))) == [
        date(2026, 9, 29),
        date(2026, 9, 30),
        date(2026, 10, 1),
        date(2026, 10, 2),
    ]


def test_один_день_и_пустой_период():
    assert list(daterange(date(2026, 9, 26), date(2026, 9, 26))) == [date(2026, 9, 26)]
    assert list(daterange(date(2026, 9, 27), date(2026, 9, 26))) == []


def test_месяцы_через_границу_года():
    assert months_in(date(2025, 11, 30), date(2026, 2, 1)) == [
        (2025, 11),
        (2025, 12),
        (2026, 1),
        (2026, 2),
    ]


def test_месяцы_одного_месяца_и_пустой_период():
    assert months_in(date(2026, 9, 1), date(2026, 9, 30)) == [(2026, 9)]
    assert months_in(date(2026, 10, 1), date(2026, 9, 30)) == []
