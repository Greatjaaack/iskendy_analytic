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


# ─── Второй проход аудита: с/с порции и P&L без данных ───────────────────────


def test_сс_порции_без_бесплатных_модификаторов(с_бесплатным_айраном, клиент):
    """С/с «Айрана» — 60 ₽ за 2 шт. в каждом заказе, то есть 30 ₽ за порцию. Бесплатный
    модификатор «Айран» (с/с 0) в делитель не идёт: иначе 180 ₽ / 7 шт. = 25,71 ₽."""
    body = клиент.get(f"/api/dishes?{ПЕРИОД}").json()
    айран = {d["name"]: d for d in body["data"]}["Айран"]
    assert айран["quantity"] == 2 * len(ПЕРИОД_ДНИ)
    assert айран["cost_sum"] == 30 * айран["quantity"]
    assert айран["cost_pct"] == 30.0  # 30 ₽ при цене 100 ₽


def _строки_pnl(body: dict) -> dict[str, dict]:
    return {line["key"]: line for s in body["sections"] for line in s["lines"]}


@pytest.fixture
def без_затрат(фикстурная_бд):
    with фикстурная_бд() as db:
        db.query(models.PnlMonth).delete()
        db.query(models.Shift).delete()
        db.commit()
    return фикстурная_бд


def test_pnl_без_затрат_нет_безубыточности_и_зелёного(без_затрат, клиент):
    body = клиент.get(f"/api/pnl?{ПЕРИОД}").json()
    assert body["breakeven"]["revenue_month"] is None  # было «0 ₽/мес»
    assert body["breakeven"]["revenue_day"] is None
    строки = _строки_pnl(body)
    assert строки["breakeven_month"]["value"] is None
    for key in ("rent", "utilities", "labor_op", "all_labor", "prime_cost", "cogs"):
        assert строки[key]["rating"] is None, key  # не введено — не «отлично»
    assert строки["food_cost"]["rating"] is not None  # с/с с кассы есть — оценка остаётся


def test_pnl_с_затратами_оценки_на_месте(клиент):
    body = клиент.get(f"/api/pnl?{ПЕРИОД}").json()
    строки = _строки_pnl(body)
    assert body["breakeven"]["revenue_month"] > 0
    for key in ("rent", "utilities", "labor_op", "prime_cost"):
        assert строки[key]["rating"] in ("green", "yellow", "red"), key


# ─── Гейт качества с/с: food cost и EBITDA не красим на мусорной с/с ─────────


def test_правдоподобная_сс_позиции():
    from utils import cost_plausible

    assert cost_plausible(180, 600)  # 30 %
    assert not cost_plausible(17.7, 590)  # «Балык» в iiko: 3 % цены
    assert not cost_plausible(0, 600)
    assert not cost_plausible(None, 600)
    assert not cost_plausible(50, 0)  # бесплатная позиция — с/с не оценить
    assert not cost_plausible(700, 600)  # дороже цены — ошибка ввода


@pytest.fixture
def мусорная_сс(фикстурная_бд):
    """С/с как у «Балыка» в iiko: 3 % цены у всех позиций."""
    with фикстурная_бд() as db:
        for item in db.query(models.OrderItem):
            item.cost = item.sum * 0.03
        db.commit()
    return фикстурная_бд


def test_pnl_с_мусорной_сс_не_оценивает_food_cost_и_ebitda(мусорная_сс, клиент):
    body = клиент.get(f"/api/pnl?{ПЕРИОД}").json()
    assert body["missing_inputs"] == ["food_cost"]
    assert body["food_cost_coverage"] == 0
    assert body["ebitda_rating"] is None
    assert body["net_rating"] is None
    assert body["breakeven"]["reliable"] is False
    строки = _строки_pnl(body)
    for key in ("food_cost", "cogs", "prime_cost", "ebitda", "net_profit"):
        assert строки[key]["rating"] is None, key
    assert строки["rent"]["rating"] is not None  # затраты введены — их оцениваем


def test_pnl_с_полными_данными_оценивает_всё(клиент):
    body = клиент.get(f"/api/pnl?{ПЕРИОД}").json()
    assert body["missing_inputs"] == []
    assert body["food_cost_coverage"] == 100
    assert body["breakeven"]["reliable"] is True
    assert body["ebitda_rating"] in ("green", "yellow", "red")
    assert _строки_pnl(body)["food_cost"]["rating"] in ("green", "yellow", "red")


def test_pnl_без_затрат_и_смен_перечисляет_пропуски(без_затрат, клиент):
    body = клиент.get(f"/api/pnl?{ПЕРИОД}").json()
    assert body["missing_inputs"] == ["fixed_costs", "labor"]
    assert body["ebitda_rating"] is None


def test_оп_отчёт_с_мусорной_сс_не_оценивает_food_cost(мусорная_сс, клиент):
    body = клиент.get(f"/api/revenue/ops-report?{ПЕРИОД}").json()
    итог = body["totals"]["total"]
    assert итог["food_cost_pct"] == 3.0  # процент считается как есть…
    assert итог["coverage"] == 0
    assert итог["cost_ok"] is False  # …но красить его нельзя
    for группа in body["category_totals"].values():
        assert группа["cost_ok"] is False


def test_оп_отчёт_с_правдоподобной_сс_оценивает(клиент):
    итог = клиент.get(f"/api/revenue/ops-report?{ПЕРИОД}").json()["totals"]["total"]
    assert итог["coverage"] == 100
    assert итог["cost_ok"] is True


# ─── P&L по дням: экономика всего дня, сумма дней = итог периода ─────────────


@pytest.fixture
def маркетинг_и_выходной(фикстурная_бд):
    """Маркетинг 31 000 ₽ в марте (1 000 ₽ в день) и закрытый средний день периода."""
    выходной = ПЕРИОД_ДНИ[1]
    with фикстурная_бд() as db:
        db.query(models.PnlMonth).filter_by(year=2026, month=3).update({"marketing": 31000})
        for модель in (models.OrderItem, models.Order, models.OrderPayment, models.DishDetail):
            db.query(модель).filter(модель.date == выходной).delete()
        db.query(models.RevenueDaily).filter(models.RevenueDaily.date == выходной).delete()
        db.commit()
    return выходной


def test_pnl_по_дням_сходится_с_итогом(маркетинг_и_выходной, клиент):
    body = клиент.get(f"/api/pnl?{ПЕРИОД}").json()
    дни = body["daily"]
    assert [d["date"] for d in дни] == [d.isoformat() for d in ПЕРИОД_ДНИ]  # и выходной тоже
    assert all(d["marketing"] == 1000 for d in дни)  # маркетинг — доля месяца на день
    # каждый день округлён до рубля — допуск по рублю на день
    assert abs(sum(d["ebitda"] for d in дни) - body["ebitda"]) <= len(дни)
    assert abs(sum(d["net_profit"] for d in дни) - body["net_profit"]) <= len(дни)


def test_pnl_закрытый_день_несёт_затраты(маркетинг_и_выходной, клиент):
    дни = {d["date"]: d for d in клиент.get(f"/api/pnl?{ПЕРИОД}").json()["daily"]}
    выходной = дни[маркетинг_и_выходной.isoformat()]
    assert выходной["revenue"] == 0 and выходной["checks"] == 0
    # аренда 90 000 + коммуналка 15 000 + маркетинг 31 000 за 31 день + смена повара 3 000
    assert выходной["ebitda"] == -round((90000 + 15000 + 31000) / 31 + 3000)


def test_pnl_режим_день(клиент):
    день = ПЕРИОД_ДНИ[-1]
    body = клиент.get(f"/api/pnl?date_from={день}&date_to={день}").json()
    assert len(body["daily"]) == 1
    d = body["daily"][0]
    assert d["revenue"] == body["revenue"]
    assert d["ebitda"] == body["ebitda"]
    # сравнение — тот же день недели неделей раньше
    assert d["prev"]["date"] == (день - timedelta(days=7)).isoformat()
    assert body["prev_summary"]["ebitda"] == d["prev"]["ebitda"]
