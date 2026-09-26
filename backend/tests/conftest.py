"""Общая обвязка тестов: фикстурная БД, отключённая сеть, клиент с сессией.

Два правила, ради которых файл существует.

**Первое: наружу не ходим.** Касса подменяется объектом, который падает при любом
обращении — так тест доказывает, что ручка читает БД, а не кассу (после этапа 3 это
обещание кода, и его легко нарушить обратно). Погода подменяется словарём: Open-Meteo
отвечал 503 прямо во время прогонов, и тест не должен от него зависеть.

**Второе: данные реалистичные, но минимальные.** Три дня, повторяющиеся номера заказов
(ловушка из этапа 1), «Статус» на уровне заказа, модификатор, сплит-оплата, ТТК с
привязкой. На таком наборе сходимость чисел между ручками проверяема руками.
"""

import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main  # noqa: E402
import models  # noqa: E402
import ratelimit  # noqa: E402
import scheduler  # noqa: E402
import storage  # noqa: E402
from config import settings  # noqa: E402
from constants import ORDER_STATUS_CATEGORY, PRODUCT_TYPE_DISH, PRODUCT_TYPE_MODIFIER  # noqa: E402
from routers import nomenclature as nom_router  # noqa: E402
from routers import plan as plan_router  # noqa: E402
from routers import pnl as pnl_router  # noqa: E402
from routers import revenue as rev_router  # noqa: E402
from routers import schedule as sched_router  # noqa: E402
from routers import suppliers as sup_router  # noqa: E402
from services import aggregator as aggregator_service  # noqa: E402
from services import ops_report as ops_report_service  # noqa: E402
from services import order_store  # noqa: E402
from services import revenue_source  # noqa: E402
from services import pnl_calc as pnl_calc_service  # noqa: E402
from services import schedule_labor as labor_service  # noqa: E402

PASSWORD = "test-pass"
INTERNAL_TOKEN = "test-internal"

# Шесть дней, внутри каждого — заказы с номерами 1 и 2 (номера повторяются между днями:
# именно на этом ломались разрезы по чекам до этапа 1). Шесть, а не три, потому что KPI
# считает дельты к прошлому сопоставимому периоду: для диапазона из трёх дней это три
# предыдущих дня, и они тоже должны лежать в БД — иначе ручка честно пойдёт в кассу.
DAYS = tuple(date(2026, 2, 23) + timedelta(days=i) for i in range(14))
# Запрашиваемый период — последние три дня. Остальные нужны прошлым периодам: KPI-дельты
# берут окно той же длины вплотную перед текущим, а P&L сдвигает период на целую неделю,
# чтобы сравнивать одинаковые дни недели. Если этих дней нет в БД, ручка честно идёт в
# кассу — и заглушка `КассаНедоступна` это поймает.
ПЕРИОД_ДНИ = DAYS[-3:]

# (категория, имя, тип позиции, кол-во, сумма, с/с) — состав одного заказа
ЗАКАЗ_1 = [
    ("Дюрюмы", "Балык", PRODUCT_TYPE_DISH, 1, 600.0, 180.0),
    ("Напитки", "Айран", PRODUCT_TYPE_DISH, 2, 200.0, 60.0),
    (ORDER_STATUS_CATEGORY, "С собой", PRODUCT_TYPE_MODIFIER, 1, 0.0, 0.0),
]
ЗАКАЗ_2 = [
    ("Дюрюмы", "Классик", PRODUCT_TYPE_DISH, 1, 500.0, 150.0),
    ("Допы и соусы", "Разрезать 1/2", PRODUCT_TYPE_MODIFIER, 1, 0.0, 0.0),
    (ORDER_STATUS_CATEGORY, "В зале", PRODUCT_TYPE_MODIFIER, 1, 0.0, 0.0),
]

# Ожидаемые итоги фикстуры — считаны руками, чтобы тест сверял числа, а не «что вышло».
ВЫРУЧКА_ЗА_ДЕНЬ = 1300.0  # 600 + 200 + 500
ЧЕКОВ_ЗА_ДЕНЬ = 2
СЕБЕСТОИМОСТЬ_ЗА_ДЕНЬ = 390.0  # 180 + 60 + 150
ВЫРУЧКА_ВСЕГО = ВЫРУЧКА_ЗА_ДЕНЬ * len(ПЕРИОД_ДНИ)
ЧЕКОВ_ВСЕГО = ЧЕКОВ_ЗА_ДЕНЬ * len(ПЕРИОД_ДНИ)
ПЕРИОД = f"date_from={ПЕРИОД_ДНИ[0].isoformat()}&date_to={ПЕРИОД_ДНИ[-1].isoformat()}"


class КассаНедоступна:
    """Заглушка кассы: любое обращение — ошибка теста.

    Смысл не в изоляции от сети (её дала бы и пустая заглушка), а в утверждении: ручки
    дашборда за период внутри сохранённой истории обязаны отвечать ИЗ БД. Полезла в кассу —
    значит регрессия этапа 3.
    """

    name = "тест: кассы нет"

    def __getattr__(self, item):
        async def упасть(*_a, **_kw):
            raise AssertionError(
                f"ручка полезла в кассу ({item}) — за период внутри истории так нельзя"
            )

        return упасть


def _наполнить(Session) -> None:
    """Заполнить фикстурную БД: продажи, оплаты, номенклатура, ТТК, план, ФОТ, поставщик."""
    with Session() as db:
        поставщик = models.Supplier(name="Тестовый поставщик")
        db.add(поставщик)
        db.flush()
        ингредиент = models.Ingredient(name="Лаваш", unit="шт")
        db.add(ингредиент)
        db.flush()
        db.add(
            models.SupplierPrice(
                supplier_id=поставщик.id,
                ingredient_id=ингредиент.id,
                brand="Тест",
                pack_size=1,
                pack_unit="шт",
                pack_price=25.0,
                unit_price=25.0,
                source="тест",
            )
        )

        ттк = models.Ttk(
            name="Балык",
            name_norm="балык",
            category="Дюрюмы",
            is_semi=False,
            yield_qty=350,
            yield_unit="г",
            cost_total=180.0,
            cost_full=180.0,
            sale_price=600.0,
        )
        db.add(ттк)
        db.flush()
        db.add(models.DishMapping(sale_name="Балык", sale_name_norm="балык", ttk_id=ттк.id))

        for день in DAYS:
            позиции_дня = 0.0
            for номер, состав in (("1", ЗАКАЗ_1), ("2", ЗАКАЗ_2)):
                час = 13 if номер == "1" else 19
                сумма_заказа = sum(s for _c, _n, _t, _q, s, _cost in состав)
                стоимость = sum(c for _c, _n, _t, _q, _s, c in состав)
                позиции_дня += сумма_заказа
                for категория, имя, тип, кол, сумма, себ in состав:
                    db.add(
                        models.OrderItem(
                            date=день,
                            hour=час,
                            order_num=номер,
                            category=категория,
                            name=имя,
                            dish_type=тип,
                            qty=кол,
                            sum=сумма,
                            net=сумма,
                            cost=себ,
                            guests=1,
                        )
                    )
                db.add(
                    models.Order(
                        date=день,
                        order_num=номер,
                        hour=час,
                        weekday=день.weekday(),
                        daypart="lunch" if час < 16 else "dinner",
                        channel="с собой" if номер == "1" else "в зале",
                        is_delivery=False,
                        guests=1,
                        total_sum=сумма_заказа,
                        cost_sum=стоимость,
                        item_count=sum(q for _c, _n, _t, q, _s, _cost in состав),
                        dish_count=len(состав) - 1,
                        pay_type="Наличные" if номер == "1" else "Терминал",
                        open_time=f"{день.isoformat()}T{час:02d}:05:00",
                        close_time=f"{день.isoformat()}T{час:02d}:12:00",
                        duration_min=7.0,
                    )
                )
                # сплит-оплата у первого заказа: половина наличными, половина картой
                if номер == "1":
                    db.add(
                        models.OrderPayment(
                            date=день, order_num=номер, pay_type="Наличные", amount=400.0
                        )
                    )
                    db.add(
                        models.OrderPayment(
                            date=день, order_num=номер, pay_type="Терминал", amount=400.0
                        )
                    )
                else:
                    db.add(
                        models.OrderPayment(
                            date=день, order_num=номер, pay_type="Терминал", amount=500.0
                        )
                    )

            db.add(
                models.RevenueDaily(
                    date=день,
                    day_of_week=день.strftime("%A"),
                    total_sum=позиции_дня,
                    check_count=ЧЕКОВ_ЗА_ДЕНЬ,
                    avg_check=позиции_дня / ЧЕКОВ_ЗА_ДЕНЬ,
                    discount_sum=0,
                    refund_count=0,
                    cost_sum=СЕБЕСТОИМОСТЬ_ЗА_ДЕНЬ,
                )
            )
            # справочник блюд дня: нужен фильтру модификаторов в dishes-разрезах
            for категория, имя, тип, кол, сумма, себ in ЗАКАЗ_1 + ЗАКАЗ_2:
                db.add(
                    models.DishDetail(
                        date=день,
                        dish_id=f"{категория}|{имя}",
                        dish_name=имя,
                        category=категория,
                        product_type=тип,
                        quantity=кол,
                        revenue=сумма,
                        cost_sum=себ,
                    )
                )

        db.add(
            models.DaypartPlan(
                daypart_key="lunch", weekday_group="ordinary", revenue=1000, avg_check=500, guests=2
            )
        )
        # затраты за оба месяца фикстуры: P&L аллоцирует их на дни, и у прошлого периода
        # (неделей раньше) месяц может быть другим
        for месяц in (2, 3):
            db.add(
                models.PnlMonth(
                    year=2026,
                    month=месяц,
                    rent=90000,
                    utilities=15000,
                    tax_pct=6,
                    work_hours=12,
                )
            )
        сотрудник = models.Employee(
            name="Тестовый повар",
            role="повар",
            labor_group="operational",
            pay_type="shift",
            rate=3000,
            active=True,
        )
        db.add(сотрудник)
        db.flush()
        for день in DAYS:
            db.add(models.Shift(employee_id=сотрудник.id, date=день))
        db.add(models.SyncLog(sync_type="orders", status="ok", created_at=datetime(2026, 3, 4, 12)))
        db.commit()


@pytest.fixture
def фикстурная_бд(tmp_path, monkeypatch):
    """Временная БД с данными за три дня; подменяется во всех модулях, где она читается."""
    engine = create_engine(
        f"sqlite:///{tmp_path / 'smoke.db'}", connect_args={"check_same_thread": False}
    )
    event.listen(engine, "connect", models._sqlite_pragmas)
    models.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    _наполнить(Session)

    for модуль in (
        main,
        scheduler,
        order_store,
        revenue_source,
        ops_report_service,
        pnl_calc_service,
        labor_service,
        aggregator_service,
        rev_router,
        pnl_router,
        plan_router,
        sched_router,
        sup_router,
        nom_router,
    ):
        monkeypatch.setattr(модуль, "SessionLocal", Session, raising=False)

    файлы = tmp_path / "files"
    файлы.mkdir()
    monkeypatch.setattr(storage, "FILES_DIR", str(файлы))
    return Session


@pytest.fixture
def без_сети(monkeypatch):
    """Касса падает при обращении, погода приходит из словаря — сеть не нужна."""
    import pos

    касса = КассаНедоступна()
    monkeypatch.setattr(pos, "_client", касса, raising=False)
    monkeypatch.setattr(pos, "get_pos", lambda: касса)
    for модуль in (scheduler, order_store, revenue_source, rev_router, main):
        monkeypatch.setattr(модуль, "get_pos", lambda: касса, raising=False)

    async def погода(date_from, date_to):
        return {
            d.isoformat(): {"temp_max": 7.5, "weather_code": 3, "label": "облачно"} for d in DAYS
        }

    monkeypatch.setattr(rev_router, "get_weather", погода)
    return касса


@pytest.fixture
def клиент(фикстурная_бд, без_сети, monkeypatch):
    """Клиент с валидной сессией дашборда."""
    monkeypatch.setattr(settings, "auth_password", PASSWORD)
    monkeypatch.setattr(settings, "auth_username", "admin")
    monkeypatch.setattr(settings, "internal_token", INTERNAL_TOKEN)
    monkeypatch.setattr(settings, "cache_ttl_seconds", 0)  # кэш не должен прятать регрессии
    ratelimit.reset()
    c = TestClient(main.app)
    токен = c.post("/api/auth/login", json={"username": "admin", "password": PASSWORD}).json()[
        "token"
    ]
    c.headers.update({"Authorization": f"Bearer {токен}"})
    return c
