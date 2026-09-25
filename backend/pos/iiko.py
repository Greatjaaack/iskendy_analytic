"""Адаптер кассы iiko: внутренний API iikoweb → доменные типы `pos/base.py`.

Здесь и только здесь живёт знание о том, как iiko отдаёт данные: OLAP-строки со
склейкой групп в `field0`, метрики `get-data` по кодам, матрица часы×даты. Всё это
превращается в `PosOrder`/`PosDay`/`PosProduct`, и дальше по коду iiko не видно.

Транспорт (Playwright-логин, cookie-сессия, кэш) остался в `iiko_web_client.py` —
адаптер им пользуется, а не дублирует.
"""

import logging
from datetime import date as Date
from datetime import timedelta

from config import settings
from constants import (
    CHANNEL_DINEIN,
    DATA_SUMMARY_BY_HOURS,
    METRIC_AVG_SPEND,
    METRIC_COST,
    METRIC_DISCOUNT,
    METRIC_REFUNDS,
    METRIC_REV_GROSS,
    METRIC_TRN_ALL,
    OLAP_FIELD_CASHIER,
    OLAP_FIELD_CLOSE_TIME,
    OLAP_FIELD_COST,
    OLAP_FIELD_DISH_CATEGORY,
    OLAP_FIELD_DISH_NAME,
    OLAP_FIELD_DISH_TYPE,
    OLAP_FIELD_GUESTS,
    OLAP_FIELD_HOUR,
    OLAP_FIELD_NET,
    OLAP_FIELD_OPEN_DATE,
    OLAP_FIELD_OPEN_TIME,
    OLAP_FIELD_ORDER_NUM,
    OLAP_FIELD_PAYTYPES,
    OLAP_FIELD_QTY,
    OLAP_FIELD_SECTION,
    OLAP_FIELD_SESSION,
    OLAP_FIELD_SUM,
    OLAP_FIELD_TABLE,
    ORDER_STATUS_CATEGORY,
    ORDER_STATUS_CHANNELS,
)
from iiko_web_client import iiko_web
from pos.base import (
    PosDay,
    PosHour,
    PosItem,
    PosOpenOrder,
    PosOrder,
    PosPayment,
    PosProduct,
)
from services.olap_parse import split_field
from utils import today

logger = logging.getLogger(__name__)

# Позиционный OLAP-запрос: группы (имя блюда — последним, может содержать «, ») и данные.
_ITEM_GROUP = [
    OLAP_FIELD_OPEN_DATE,
    OLAP_FIELD_HOUR,
    OLAP_FIELD_ORDER_NUM,
    OLAP_FIELD_DISH_CATEGORY,
    OLAP_FIELD_DISH_TYPE,
    OLAP_FIELD_DISH_NAME,
]
_ITEM_DATA = [OLAP_FIELD_SUM, OLAP_FIELD_QTY, OLAP_FIELD_GUESTS, OLAP_FIELD_COST, OLAP_FIELD_NET]
# Заказ-уровневые атрибуты — отдельным запросом, чтобы сплит-оплата не дублировала позиции.
_ATTR_GROUP = [
    OLAP_FIELD_OPEN_DATE,
    OLAP_FIELD_ORDER_NUM,
    OLAP_FIELD_OPEN_TIME,
    OLAP_FIELD_CLOSE_TIME,
    OLAP_FIELD_SESSION,
    OLAP_FIELD_TABLE,
    OLAP_FIELD_PAYTYPES,
    OLAP_FIELD_SECTION,
    OLAP_FIELD_CASHIER,
]


def _f(row: dict, i: int) -> float:
    return float(row.get(f"field{i}", {}).get("value", 0) or 0)


def _parse_hour_matrix(block: dict) -> dict[int, float]:
    """`DATA_SUMMARY_BY_HOURS`: rows={"D11":0,…}, data=[[по датам],…] → {час: сумма}."""
    rows = block.get("rows", {}) if isinstance(block, dict) else {}
    data = block.get("data", []) if isinstance(block, dict) else []
    out: dict[int, float] = {}
    for key, ri in rows.items():
        try:
            hour = int(str(key).lstrip("D"))
        except ValueError:
            continue
        row = data[ri] if isinstance(ri, int) and ri < len(data) else []
        out[hour] = sum(v for v in row if v is not None)
    return out


class IikoPos:
    """Реализация `PosClient` поверх iikoweb (OLAP SALES + KPI get-data)."""

    name = "iiko"

    async def orders(self, date_from: Date, date_to: Date) -> list[PosOrder]:
        """Заказы за диапазон: два OLAP-запроса (позиции + атрибуты заказа) → `PosOrder`."""
        df, dt = date_from.isoformat(), date_to.isoformat()
        # Терпение синка намеренно больше, чем у ручки табло: его никто не ждёт на
        # линии, а его результат — та БД, из которой табло отвечает мгновенно.
        terpenie = settings.sync_poll_attempts
        item_rows = await iiko_web.olap_sales(
            group_fields=_ITEM_GROUP,
            data_fields=_ITEM_DATA,
            date_from=df,
            date_to=dt,
            poll_attempts=terpenie,
        )
        attr_rows = await iiko_web.olap_sales(
            group_fields=_ATTR_GROUP,
            data_fields=[OLAP_FIELD_SUM],
            date_from=df,
            date_to=dt,
            poll_attempts=terpenie,
        )
        return self._build(item_rows, attr_rows)

    # ---------- Разбор OLAP ----------

    def _build(self, item_rows: list[dict], attr_rows: list[dict]) -> list[PosOrder]:
        """Строки двух OLAP-запросов → заказы с позициями и оплатами."""
        attrs = self._parse_attrs(attr_rows)
        pays = self._parse_payments(attr_rows)
        orders: dict[tuple, PosOrder] = {}

        for r in item_rows:
            ds, hs, num, category, dish_type, name = split_field(
                r.get("field0", {}).get("value", ""), 6
            )
            if not ds:
                continue
            try:
                day = Date.fromisoformat(ds)
            except ValueError:
                continue
            try:
                hour: int | None = int(hs)
            except (ValueError, TypeError):
                hour = None

            key = (day, num)
            order = orders.get(key)
            if order is None:
                a = attrs.get(key, {})
                order = orders[key] = PosOrder(
                    number=num,
                    date=day,
                    open_time=a.get("open_time"),
                    close_time=a.get("close_time"),
                    session_num=a.get("session_num"),
                    table_num=a.get("table_num"),
                    section=a.get("section"),
                    cashier=a.get("cashier"),
                    payments=[PosPayment(p, s) for p, s in pays.get(key, {}).items()],
                )
            order.items.append(
                PosItem(
                    name=name,
                    category=category,
                    dish_type=dish_type,
                    qty=_f(r, 2),
                    sum=_f(r, 1),
                    net=_f(r, 5),
                    cost=_f(r, 4),
                    hour=hour,
                )
            )
            order.guests = max(order.guests, _f(r, 3))
            if hour is not None:
                order.hour = hour if order.hour is None else min(order.hour, hour)
            # Тип обслуживания у этой точки ведётся модификатором категории «Статус»
            # на уровне заказа — других источников канала в iiko нет (OrderType пуст).
            if category == ORDER_STATUS_CATEGORY:
                channel = ORDER_STATUS_CHANNELS.get((name or "").strip().lower())
                if channel:
                    order.channel = channel

        # Заказ без «Статуса» — «в зале»: так было до вынесения адаптера.
        for order in orders.values():
            if order.channel is None:
                order.channel = CHANNEL_DINEIN
        return list(orders.values())

    def _parse_attrs(self, rows: list[dict]) -> dict[tuple, dict]:
        """Заказ-атрибуты (время/смена/стол/зал/кассир) → {(дата, номер): {…}}."""
        out: dict[tuple, dict] = {}
        for r in rows:
            ds, num, open_t, close_t, session, table, _pay, section, cashier = split_field(
                r.get("field0", {}).get("value", ""), 9
            )
            try:
                day = Date.fromisoformat(ds)
            except ValueError:
                continue
            a = out.get((day, num))
            if a is None:
                a = out[(day, num)] = {
                    "open_time": open_t or None,
                    "close_time": close_t or None,
                    "session_num": session or None,
                    "table_num": table or None,
                    "section": section or None,
                    "cashier": cashier or None,
                }
            if open_t and (a["open_time"] is None or open_t < a["open_time"]):
                a["open_time"] = open_t
            if close_t and (a["close_time"] is None or close_t > a["close_time"]):
                a["close_time"] = close_t
        return out

    def _parse_payments(self, rows: list[dict]) -> dict[tuple, dict[str, float]]:
        """Оплаты заказа: {(дата, номер): {способ: сумма}}.

        Сплит-оплата даёт несколько строк на заказ, и OLAP делит сумму по способам
        корректно (проверено: Σ по (заказ, способ) = выручке заказа).
        """
        out: dict[tuple, dict[str, float]] = {}
        for r in rows:
            ds, num, _ot, _ct, _se, _tb, pay, _sc, _ca = split_field(
                r.get("field0", {}).get("value", ""), 9
            )
            if not pay:
                continue
            try:
                day = Date.fromisoformat(ds)
            except ValueError:
                continue
            bucket = out.setdefault((day, num), {})
            bucket[pay] = bucket.get(pay, 0.0) + _f(r, 1)
        return out

    # ---------- Агрегаты, которые iiko умеет сам ----------

    async def products(self, day: Date) -> list[PosProduct]:
        """Продажи по номенклатуре за день (`get-data DATA_DETAILS` + decoration)."""
        rows = await iiko_web.dishes_detail(day.isoformat(), day.isoformat())
        return [
            PosProduct(
                product_id=r["dish_id"],
                name=r["dish_name"],
                category=r["category"],
                product_type=r["product_type"],
                quantity=r["quantity"],
                revenue=r["revenue"],
                cost_sum=r["cost_sum"],
            )
            for r in rows
        ]

    async def revenue_days(self, date_from: Date, date_to: Date) -> list[PosDay]:
        """Сводка по дням метриками KPI (`DATA_SUMMARY_BY_DATE`)."""
        data = await iiko_web.revenue_by_day(date_from.isoformat(), date_to.isoformat())
        return self._parse_days(data)

    def _parse_days(self, data: dict) -> list[PosDay]:
        def g(code: str, key: str) -> float:
            block = data.get(code, {})
            return float((block.get(key) if isinstance(block, dict) else 0) or 0)

        keys: set[str] = set()
        for block in data.values():
            if isinstance(block, dict):
                keys.update(block.keys())

        days = []
        for ds in sorted(keys):
            try:
                day = Date.fromisoformat(ds)
            except ValueError:
                continue
            days.append(
                PosDay(
                    date=day,
                    revenue=g(METRIC_REV_GROSS, ds),
                    checks=int(g(METRIC_TRN_ALL, ds)),
                    avg_check=g(METRIC_AVG_SPEND, ds),
                    discount_sum=g(METRIC_DISCOUNT, ds),
                    refund_count=int(g(METRIC_REFUNDS, ds)),
                    cost_sum=g(METRIC_COST, ds),
                )
            )
        return days

    async def hourly(self, date_from: Date, date_to: Date) -> dict[int, PosHour]:
        """Выручка/чеки по часам суток за период (`DATA_SUMMARY_BY_HOURS`)."""
        raw = await iiko_web.get_metrics(
            [METRIC_REV_GROSS, METRIC_TRN_ALL],
            date_from.isoformat(),
            date_to.isoformat(),
            data_type=DATA_SUMMARY_BY_HOURS,
        )
        rev = _parse_hour_matrix(raw.get(METRIC_REV_GROSS, {}))
        trn = _parse_hour_matrix(raw.get(METRIC_TRN_ALL, {}))
        return {
            h: PosHour(revenue=round(rev.get(h, 0) or 0, 2), checks=int(trn.get(h, 0) or 0))
            for h in sorted(set(rev) | set(trn))
        }

    async def open_orders(self, day: Date) -> list[PosOpenOrder]:
        """Заказы дня для табло: OLAP `[OrderNum, OpenTime]` — самый дешёвый разрез.

        TTL кэша задаёт вызывающий: пока за сегодня заказов нет, табло опрашивает
        кассу реже (см. `settings.idle_poll_seconds` в ручке `/api/orders/today`).
        """
        rows = await iiko_web.olap_sales(
            group_fields=[OLAP_FIELD_ORDER_NUM, OLAP_FIELD_OPEN_TIME],
            data_fields=[OLAP_FIELD_SUM],
            date_from=day.isoformat(),
            date_to=day.isoformat(),
            cache_ttl=self._open_orders_ttl,
        )
        out = []
        for r in rows:
            num, open_t = split_field(r.get("field0", {}).get("value", ""), 2)
            if not num or not open_t:
                continue
            out.append(PosOpenOrder(number=num.strip(), open_time=open_t.strip()))
        return out

    # TTL живого чтения заказов табло: ставится ручкой перед вызовом (None — общий кэш).
    _open_orders_ttl: int | None = None

    def with_open_orders_ttl(self, ttl: int | None) -> "IikoPos":
        """Вернуть клиент с заданным TTL кэша для `open_orders` (не мутируя общий)."""
        clone = IikoPos()
        clone._open_orders_ttl = ttl
        return clone

    async def history_start(self) -> Date | None:
        """Probe первой даты с продажами по метрике выручки за ~10 лет назад."""
        date_to = today()
        probe_from = date_to - timedelta(days=3650)
        data = await iiko_web.revenue_by_day(probe_from.isoformat(), date_to.isoformat())
        keys: set[str] = set()
        for block in data.values():
            if isinstance(block, dict):
                keys.update(block.keys())
        if not keys:
            return None
        return min(Date.fromisoformat(k) for k in keys)

    async def warm(self) -> None:
        """Освежить cookie-сессию iikoweb (TTL ~20 мин), чтобы не логиниться на запросе."""
        await iiko_web._ensure_session()
