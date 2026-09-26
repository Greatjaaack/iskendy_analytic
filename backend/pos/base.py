"""Порт кассы: доменные типы продаж и сборка из них строк БД.

Здесь нет ни одного слова про iiko или Saby — только то, что нужно аналитике:
заказ с позициями и оплатами. Конкретная касса живёт в адаптерах (`pos/iiko.py`,
`pos/saby.py`) и обязана отдавать эти типы; всё, что ниже (сборка `order_items` /
`orders` / `order_payments`), считается одинаково для любой кассы.

Зачем так: касса меняется (iiko → Saby Presto), аналитика — нет. Раньше формат
OLAP-ответа iiko (`field0` со склейкой групп) протекал в планировщик и роутеры, и
переезд означал бы правку всего даунстрима. Теперь граница одна — этот модуль.
"""

from dataclasses import dataclass, field
from datetime import date as Date
from datetime import datetime
from typing import Protocol

from constants import (
    CHANNEL_DELIVERY,
    CHANNEL_DINEIN,
    ORDER_STATUS_CATEGORY,
    PRODUCT_TYPE_DISH,
    PRODUCT_TYPE_MODIFIER,
)
from services.daypart import hour_to_daypart
from utils import is_delivery

# ─── Доменные типы ───────────────────────────────────────────────────────────


@dataclass(slots=True)
class PosItem:
    """Позиция продажи так, как её видит аналитика."""

    name: str
    category: str = ""
    # нормализованный тип позиции: DISH / GOODS / MODIFIER (см. constants.PRODUCT_TYPE_*)
    dish_type: str = PRODUCT_TYPE_DISH
    qty: float = 0.0
    sum: float = 0.0  # выручка до скидки
    net: float = 0.0  # выручка после скидки
    cost: float = 0.0  # себестоимость позиции по данным кассы
    hour: int | None = None  # час продажи (у части касс — атрибут позиции, не заказа)


@dataclass(slots=True)
class PosPayment:
    """Оплата заказа. Сплит-чек даёт несколько оплат на один заказ."""

    pay_type: str
    amount: float


@dataclass(slots=True)
class PosOrder:
    """Заказ (чек) с позициями и оплатами.

    `channel` заполняет адаптер, если касса знает тип обслуживания (в iiko это
    модификатор категории «Статус»). Не знает — оставляет `None`, и канал выводится
    из самих позиций правилом доставки (`utils.is_delivery`).
    """

    number: str
    date: Date
    hour: int | None = None
    open_time: str | None = None  # ISO без таймзоны, в поясе точки
    close_time: str | None = None
    guests: float = 0.0
    channel: str | None = None
    cashier: str | None = None
    session_num: str | None = None
    table_num: str | None = None
    section: str | None = None
    items: list[PosItem] = field(default_factory=list)
    payments: list[PosPayment] = field(default_factory=list)


@dataclass(slots=True)
class PosProduct:
    """Продажи одной позиции номенклатуры за день (источник таблицы `dish_detail`)."""

    product_id: str
    name: str
    category: str = ""
    product_type: str = PRODUCT_TYPE_DISH
    quantity: float = 0.0
    revenue: float = 0.0
    cost_sum: float = 0.0


@dataclass(slots=True)
class PosDay:
    """Сводка дня (источник таблицы `revenue_daily`)."""

    date: Date
    revenue: float = 0.0
    checks: int = 0
    avg_check: float = 0.0
    discount_sum: float = 0.0
    refund_count: int = 0
    cost_sum: float = 0.0


@dataclass(slots=True)
class PosHour:
    """Выручка и чеки одного часа суток (суммарно за период)."""

    revenue: float = 0.0
    checks: int = 0


@dataclass(slots=True)
class PosOpenOrder:
    """Минимум для табло: номер заказа и время открытия."""

    number: str
    open_time: str


@dataclass(slots=True)
class ItemRow:
    """Плоская строка позиции. Имена полей совпадают с моделью `OrderItem`.

    Благодаря этому одна и та же агрегация (`services/order_store.py`) работает и
    над строками из БД, и над свежими строками из кассы.
    """

    date: Date
    hour: int | None
    order_num: str
    category: str
    dish_type: str
    name: str
    sum: float
    qty: float
    guests: float
    cost: float
    net: float


# ─── Контракт адаптера кассы ─────────────────────────────────────────────────


class PosClient(Protocol):
    """Что аналитика спрашивает у кассы. Реализуют `IikoPos` и `SabyPos`.

    Всё read-only: в кассу мы не пишем никогда (правило проекта).
    """

    name: str

    async def orders(self, date_from: Date, date_to: Date) -> list[PosOrder]:
        """Заказы с позициями и оплатами за диапазон (включительно)."""

    async def products(self, day: Date) -> list[PosProduct]:
        """Продажи по позициям номенклатуры за день (с типом позиции и категорией)."""

    async def revenue_days(self, date_from: Date, date_to: Date) -> list[PosDay]:
        """Сводка по дням: выручка, чеки, средний чек, скидки, возвраты, с/с."""

    async def hourly(self, date_from: Date, date_to: Date) -> dict[int, PosHour]:
        """Выручка и чеки по часам суток, суммарно за период."""

    async def open_orders(self, day: Date, cache_ttl: int | None = None) -> list[PosOpenOrder]:
        """Заказы дня для табло — самый дешёвый запрос, какой умеет касса.

        `cache_ttl` — сколько держать ответ в кэше (`None` — общий TTL): пока за день
        нет ни одного заказа, ручка табло спрашивает кассу реже.
        """

    async def history_start(self) -> Date | None:
        """Первая дата с продажами (для бэкафилла). `None` — определить не удалось."""

    async def warm(self) -> None:
        """Прогреть сессию/токен, чтобы авторизация не случилась на запросе клиента."""


# ─── Сборка строк БД из заказов (общая для всех касс) ────────────────────────


def to_item_rows(orders: list[PosOrder]) -> list[ItemRow]:
    """Заказы → строки `order_items` (позиция = строка, как её вернула касса)."""
    rows: list[ItemRow] = []
    for o in orders:
        for it in o.items:
            rows.append(
                ItemRow(
                    date=o.date,
                    hour=it.hour if it.hour is not None else o.hour,
                    order_num=o.number,
                    category=it.category,
                    dish_type=it.dish_type,
                    name=it.name,
                    sum=it.sum,
                    qty=it.qty,
                    guests=o.guests,
                    cost=it.cost,
                    net=it.net,
                )
            )
    return rows


def _duration_min(open_t: str | None, close_t: str | None) -> float | None:
    """Длительность заказа в минутах по ISO-таймстампам открытия/закрытия."""
    if not open_t or not close_t:
        return None
    try:
        m = (datetime.fromisoformat(close_t) - datetime.fromisoformat(open_t)).total_seconds() / 60
    except ValueError:
        return None
    return round(m, 1) if m >= 0 else None


def to_order_rows(orders: list[PosOrder]) -> list[dict]:
    """Заказы → строки `orders` (обогащённая чек-сущность).

    Служебные позиции (категория «Статус» в iiko) в суммы заказа не попадают:
    это не товар, а отметка типа обслуживания. Канал берём от кассы, если она его
    знает, иначе выводим из позиций правилом доставки.
    """
    h2dp = hour_to_daypart()
    out = []
    for o in orders:
        total = cost = item_count = 0.0
        hour = o.hour
        delivery = False
        names: set[str] = set()
        for it in o.items:
            if it.category == ORDER_STATUS_CATEGORY:
                continue
            total += it.sum
            cost += it.cost
            item_count += it.qty
            names.add(it.name)
            if is_delivery(it.category, it.name):
                delivery = True
            if it.hour is not None:
                hour = it.hour if hour is None else min(hour, it.hour)
        channel = o.channel or (CHANNEL_DELIVERY if delivery else CHANNEL_DINEIN)
        pays = sorted({p.pay_type for p in o.payments if p.pay_type})
        out.append(
            {
                "date": o.date,
                "order_num": o.number,
                "hour": hour,
                "weekday": o.date.weekday(),
                "daypart": h2dp.get(hour) if hour is not None else None,
                "channel": channel,
                "is_delivery": delivery,
                "guests": o.guests,
                "total_sum": total,
                "cost_sum": cost,
                "item_count": item_count,
                "dish_count": len(names),
                "pay_type": ", ".join(pays) or None,
                "table_num": o.table_num,
                "section": o.section,
                "cashier": o.cashier,
                "session_num": o.session_num,
                "open_time": o.open_time,
                "close_time": o.close_time,
                "duration_min": _duration_min(o.open_time, o.close_time),
            }
        )
    return out


def to_payment_rows(orders: list[PosOrder]) -> list[dict]:
    """Заказы → строки `order_payments` (одна строка на способ оплаты в заказе)."""
    agg: dict[tuple, float] = {}
    for o in orders:
        for p in o.payments:
            if not p.pay_type:
                continue
            key = (o.date, o.number, p.pay_type)
            agg[key] = agg.get(key, 0.0) + p.amount
    return [
        {"date": d, "order_num": n, "pay_type": p, "amount": round(a, 2)}
        for (d, n, p), a in agg.items()
    ]


def aggregate_days(orders: list[PosOrder]) -> list[PosDay]:
    """Сводка по дням из заказов — для касс без готовых агрегатов (Saby).

    Считаем то же, что iiko отдаёт метриками: выручка (без служебных позиций),
    число чеков, средний чек, скидка (разница брутто и нетто), с/с позиций.
    """
    by_day: dict[Date, PosDay] = {}
    for o in orders:
        day = by_day.get(o.date)
        if day is None:
            day = by_day[o.date] = PosDay(date=o.date)
        gross = net = cost = 0.0
        for it in o.items:
            if it.category == ORDER_STATUS_CATEGORY:
                continue
            gross += it.sum
            net += it.net
            cost += it.cost
        day.revenue += gross
        day.discount_sum += max(0.0, gross - net)
        day.cost_sum += cost
        day.checks += 1
    for day in by_day.values():
        day.revenue = round(day.revenue, 2)
        day.discount_sum = round(day.discount_sum, 2)
        day.cost_sum = round(day.cost_sum, 2)
        day.avg_check = round(day.revenue / day.checks, 2) if day.checks else 0.0
    return sorted(by_day.values(), key=lambda d: d.date)


def _close_hour(close_t: str | None) -> int | None:
    """Час закрытия заказа из ISO-таймстампа; `None`, если времени нет или оно битое."""
    if not close_t:
        return None
    try:
        return datetime.fromisoformat(close_t).hour
    except ValueError:
        return None


def aggregate_hours(orders: list[PosOrder]) -> dict[int, PosHour]:
    """Выручка/чеки по часам суток из заказов — для касс без почасовых агрегатов.

    Час — по ЗАКРЫТИЮ заказа, как в `revenue_source.hours_from_db` и в почасовом отчёте
    iiko: иначе живой разрез (период старше истории) и разрез из БД для одних и тех же
    заказов расходились бы на чеки, открытые в конце часа и закрытые в следующем.
    Нет времени закрытия — берём час открытия.
    """
    out: dict[int, PosHour] = {}
    for o in orders:
        hour = o.hour
        gross = 0.0
        for it in o.items:
            if it.category == ORDER_STATUS_CATEGORY:
                continue
            gross += it.sum
            if it.hour is not None:
                hour = it.hour if hour is None else min(hour, it.hour)
        closed = _close_hour(o.close_time)
        if closed is not None:
            hour = closed
        if hour is None:
            continue
        bucket = out.get(hour)
        if bucket is None:
            bucket = out[hour] = PosHour()
        bucket.revenue = round(bucket.revenue + gross, 2)
        bucket.checks += 1
    return out


def aggregate_products(orders: list[PosOrder]) -> list[PosProduct]:
    """Продажи по номенклатуре из заказов — для касс без отчёта по блюдам.

    Ключ — `(имя, категория)`: у касс, где позиция продажи не несёт id номенклатуры,
    это единственная устойчивая пара. Модификаторы помечаются типом MODIFIER, чтобы
    фильтр «только блюда» в дашборде работал так же, как на iiko.
    """
    agg: dict[tuple[str, str], PosProduct] = {}
    for o in orders:
        for it in o.items:
            if it.category == ORDER_STATUS_CATEGORY:
                continue
            key = (it.name, it.category)
            p = agg.get(key)
            if p is None:
                p = agg[key] = PosProduct(
                    product_id=f"{it.category}|{it.name}",
                    name=it.name,
                    category=it.category,
                    product_type=it.dish_type or PRODUCT_TYPE_DISH,
                )
            if it.dish_type == PRODUCT_TYPE_MODIFIER:
                p.product_type = PRODUCT_TYPE_MODIFIER
            p.quantity += it.qty
            p.revenue += it.sum
            p.cost_sum += it.cost
    out = list(agg.values())
    for p in out:
        p.quantity = round(p.quantity, 3)
        p.revenue = round(p.revenue, 2)
        p.cost_sum = round(p.cost_sum, 2)
    out.sort(key=lambda p: p.revenue, reverse=True)
    return out
