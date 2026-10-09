"""Регрессии аудита расчётов 09.10.2026.

- P&L, месяц: прошлый период сдвигается одним шагом, кратным неделе. Раньше 29–31 число
  уходили на 5 недель, остальные дни — на 4, и 24–26 число прошлого месяца считались
  в сравнении дважды, а 1–2 — ни разу.
- «Продажи по часам» по блюдам: модификаторы отсекаются по ТИПУ позиции, а не по имени.
  В феврале–июле «Айран» и «Кола» бывали и бесплатными модификаторами, и вместе с ними
  из разреза пропадали платные напитки (5–8 % выручки).
- Галка «без доставки» в ручках: заказ доставки отсекается целиком, с напитком комбо.
"""

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from conftest import ВЫРУЧКА_ВСЕГО, ПЕРИОД, ПЕРИОД_ДНИ, ЧЕКОВ_ВСЕГО  # noqa: E402

import models  # noqa: E402
from constants import ORDER_STATUS_CATEGORY, PRODUCT_TYPE_DISH, PRODUCT_TYPE_MODIFIER  # noqa: E402
from services.pnl_calc import _make_prev_mapper  # noqa: E402
from utils import daterange  # noqa: E402

# ─── P&L: прошлый период ─────────────────────────────────────────────────────


@pytest.mark.parametrize("last_day", [28, 29, 30, 31])
def test_pnl_прошлый_месяц_без_повторов_и_пропусков(last_day):
    df, dt = date(2026, 10, 1), date(2026, 10, last_day)
    mapper = _make_prev_mapper("month", df, dt, is_custom=False)
    prev = [mapper(d) for d in daterange(df, dt)]

    assert len(set(prev)) == len(prev)  # ни один день не считается дважды
    assert prev == list(daterange(prev[0], prev[-1]))  # отрезок без дыр
    assert all(p.weekday() == d.weekday() for p, d in zip(prev, daterange(df, dt)))
    assert prev[-1] < df  # не залезает в текущий месяц


def test_pnl_прошлый_месяц_до_28_числа_сдвиг_четыре_недели():
    mapper = _make_prev_mapper("month", date(2026, 10, 1), date(2026, 10, 9), is_custom=False)
    assert mapper(date(2026, 10, 1)) == date(2026, 9, 3)


def test_pnl_каждый_месяц_года_без_повторов():
    for month in range(1, 13):
        df = date(2026, month, 1)
        dt = (df.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        mapper = _make_prev_mapper("month", df, dt, is_custom=False)
        prev = [mapper(d) for d in daterange(df, dt)]
        assert len(set(prev)) == len(prev), df


# ─── Добавки к фикстурной БД ─────────────────────────────────────────────────

ДЕНЬ = ПЕРИОД_ДНИ[-1]
# заказ доставки: единственный «Статус» — «Доставка», дюрюм без маркера `_д`, напиток комбо
ДОСТАВКА = [
    ("Дюрюмы", "Балык", PRODUCT_TYPE_DISH, 1, 600.0),
    ("Напитки", "Айран", PRODUCT_TYPE_DISH, 1, 100.0),
    (ORDER_STATUS_CATEGORY, "Доставка", PRODUCT_TYPE_MODIFIER, 1, 0.0),
]
ВЫРУЧКА_ДОСТАВКИ = 700.0


def _добавить_заказ(Session, номер: str, состав, оплата: str | None = None) -> None:
    with Session() as db:
        for категория, имя, тип, кол, сумма in состав:
            db.add(
                models.OrderItem(
                    date=ДЕНЬ,
                    hour=20,
                    order_num=номер,
                    category=категория,
                    name=имя,
                    dish_type=тип,
                    qty=кол,
                    sum=сумма,
                    net=сумма,
                    cost=0,
                    guests=1,
                )
            )
            db.add(
                models.DishDetail(
                    date=ДЕНЬ,
                    # одна позиция номенклатуры — один id, как в conftest; модификатор
                    # с тем же именем — другая позиция
                    dish_id=f"{категория}|{имя}" + ("|mod" if тип == PRODUCT_TYPE_MODIFIER else ""),
                    dish_name=имя,
                    category=категория,
                    product_type=тип,
                    quantity=кол,
                    revenue=сумма,
                    cost_sum=0,
                )
            )
        выручка = sum(s for c, _n, _t, _q, s in состав if c != ORDER_STATUS_CATEGORY)
        if оплата:
            db.add(models.OrderPayment(date=ДЕНЬ, order_num=номер, pay_type=оплата, amount=выручка))
        день = db.get(models.RevenueDaily, ДЕНЬ)
        день.total_sum += выручка
        день.check_count += 1
        db.commit()


@pytest.fixture
def с_доставкой(фикстурная_бд):
    _добавить_заказ(фикстурная_бд, "3", ДОСТАВКА, оплата="Яндекс Еда")
    return фикстурная_бд


@pytest.fixture
def с_бесплатным_айраном(фикстурная_бд):
    # «Айран» бесплатным модификатором к дюрюму — как в феврале–июле 2026
    _добавить_заказ(
        фикстурная_бд,
        "3",
        [
            ("Дюрюмы", "Классик", PRODUCT_TYPE_DISH, 1, 500.0),
            ("Напитки", "Айран", PRODUCT_TYPE_MODIFIER, 1, 0.0),
            (ORDER_STATUS_CATEGORY, "В зале", PRODUCT_TYPE_MODIFIER, 1, 0.0),
        ],
    )
    return фикстурная_бд


# ─── Продажи по часам: модификаторы по типу ──────────────────────────────────


def _по_часам(клиент, group: str) -> dict[int, dict]:
    body = клиент.get(f"/api/dishes/hourly-breakdown?{ПЕРИОД}&group={group}").json()
    return {h["hour"]: h for h in body["data"]}


def test_по_часам_платный_айран_не_пропадает(с_бесплатным_айраном, клиент):
    блюда = _по_часам(клиент, "dish")
    айран = {it["name"]: it for it in блюда[13]["items"]}["Айран"]
    assert айран["revenue"] == 200 * len(ПЕРИОД_ДНИ)
    assert айран["quantity"] == 2 * len(ПЕРИОД_ДНИ)  # бесплатный модификатор не считается

    категории = _по_часам(клиент, "category")
    for час in категории:  # блюда в сумме дают категории, час в час
        assert блюда[час]["revenue"] == категории[час]["revenue"]
        assert блюда[час]["quantity"] == категории[час]["quantity"]


def test_по_часам_без_доставки_отсекает_заказ_целиком(с_доставкой, клиент):
    с = _по_часам(клиент, "category")
    без = клиент.get(
        f"/api/dishes/hourly-breakdown?{ПЕРИОД}&group=category&include_delivery=false"
    ).json()
    без = {h["hour"]: h for h in без["data"]}
    assert с[20]["revenue"] == ВЫРУЧКА_ДОСТАВКИ
    assert 20 not in без  # и дюрюм, и напиток комбо ушли вместе с заказом
    assert без[13]["revenue"] == с[13]["revenue"]


# ─── Галка «без доставки» в ручках ───────────────────────────────────────────


def test_kpi_без_доставки_вычитает_весь_заказ(с_доставкой, клиент):
    с = клиент.get(f"/api/revenue?{ПЕРИОД}").json()["summary"]
    без = клиент.get(f"/api/revenue?{ПЕРИОД}&include_delivery=false").json()["summary"]
    assert с["gross_revenue"] == ВЫРУЧКА_ВСЕГО + ВЫРУЧКА_ДОСТАВКИ
    assert без["total_revenue"] == ВЫРУЧКА_ВСЕГО
    assert без["total_checks"] == ЧЕКОВ_ВСЕГО
    assert без["avg_check"] == round(ВЫРУЧКА_ВСЕГО / ЧЕКОВ_ВСЕГО, 2)


def test_таблица_блюд_без_доставки(с_доставкой, клиент):
    def блюда(qs: str) -> dict[str, dict]:
        body = клиент.get(f"/api/dishes?{ПЕРИОД}{qs}").json()
        return {d["name"]: d for d in body["data"]}

    с, без = блюда(""), блюда("&include_delivery=false")
    assert с["Балык"]["revenue"] - без["Балык"]["revenue"] == 600
    assert с["Айран"]["revenue"] - без["Айран"]["revenue"] == 100  # напиток комбо доставки
    assert без["Айран"]["quantity"] == 2 * len(ПЕРИОД_ДНИ)
    assert sum(d["revenue"] for d in без.values()) == ВЫРУЧКА_ВСЕГО


def test_оплаты_без_доставки(с_доставкой, клиент):
    с = клиент.get(f"/api/revenue/by-payment?{ПЕРИОД}").json()
    без = клиент.get(f"/api/revenue/by-payment?{ПЕРИОД}&include_delivery=false").json()
    assert "Агрегатор" in с["groups"]
    assert "Агрегатор" not in без["groups"]
    assert без["total_amount"] == ВЫРУЧКА_ВСЕГО
    assert без["total_checks"] == ЧЕКОВ_ВСЕГО


def test_каналы_сходятся_с_kpi_без_доставки(с_доставкой, клиент):
    чеки = клиент.get(f"/api/dishes/check-distribution?{ПЕРИОД}&include_delivery=false").json()
    assert чеки["total"] == ЧЕКОВ_ВСЕГО
    дни = клиент.get(f"/api/revenue/by-channel?{ПЕРИОД}&include_delivery=false").json()
    assert sum(d["total"] for d in дни["data"]) == ВЫРУЧКА_ВСЕГО
