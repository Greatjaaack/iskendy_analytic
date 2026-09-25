"""Адаптер кассы Saby (СБИС) Presto: публичный REST API → доменные типы `pos/base.py`.

Документация того, чем мы пользуемся, — в `SABY_API.md` (там же список белых пятен,
которые закрываются только на живом чеке).

Главное отличие от iiko: **у Saby нет агрегатов**. Нет ни аналога `get-data` с
метриками, ни OLAP-движка — есть только «дай продажи за период» со всеми позициями
и оплатами. Поэтому выручка по дням, часы и продажи по номенклатуре считаются здесь
же из заказов (хелперы `aggregate_*` в `pos/base.py`), а не запрашиваются у кассы.
Для нашего дашборда это не потеря: он и так читает всё из своей БД.

Второе отличие: в продаже НЕТ категории номенклатуры — только `Nomenclature` (id).
Категорию даёт отдельный каталог (`/retail/v2/nomenclature/list`), который кэшируется
в памяти и обновляется не чаще `saby_menu_ttl_seconds`.

В кассу ничего не пишем: используются только GET-методы чтения плюс POST авторизации.
"""

import asyncio
import logging
import time
from datetime import date as Date
from datetime import datetime

import httpx

from cache import cached_or_call
from config import settings
from constants import (
    ORDER_STATUS_CATEGORY,
    ORDER_STATUS_CHANNELS,
    PAYMENT_CARD,
    PAYMENT_CASH,
    PRODUCT_TYPE_DISH,
    PRODUCT_TYPE_GOODS,
    PRODUCT_TYPE_MODIFIER,
)
from pos.base import (
    PosDay,
    PosHour,
    PosItem,
    PosOpenOrder,
    PosOrder,
    PosPayment,
    PosProduct,
    aggregate_days,
    aggregate_hours,
    aggregate_products,
)

logger = logging.getLogger(__name__)

# Корневые папки каталога Presto → тип позиции. «Блюда» — то, что продаётся гостю;
# продукты/полуфабрикаты/товары в чеке фастфуда встречаются как товар (вода, соус).
_ROOT_PRODUCT_TYPE = {
    "Блюда": PRODUCT_TYPE_DISH,
    "Товары": PRODUCT_TYPE_GOODS,
    "Продукты": PRODUCT_TYPE_GOODS,
    "Полуфабрикаты": PRODUCT_TYPE_GOODS,
}

# Названия способов оплаты. Важно, чтобы они матчились правилами
# `constants.PAYMENT_GROUP_RULES` («наличн» → Наличные, «карт» → Карта).
_PAY_CASH = PAYMENT_CASH
_PAY_CARD = PAYMENT_CARD
_PAY_CERTIFICATE = "Сертификат"
_PAY_SALARY = "Под зарплату"


def _iso(value: str | None) -> str | None:
    """`YYYY-MM-DD hh:mm:ss` от Saby → ISO `YYYY-MM-DDThh:mm:ss` (как в БД)."""
    if not value:
        return None
    return str(value).strip().replace(" ", "T")


def _dt(value: str | None) -> datetime | None:
    iso = _iso(value)
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso)
    except ValueError:
        return None


def _num(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _as_list(block) -> list:
    """Saby на пустой выборке отдаёт `{}` вместо `[]` — нормализуем (проверено живьём)."""
    if isinstance(block, list):
        return block
    if isinstance(block, dict):
        return list(block.values())
    return []


class SabyPos:
    """Реализация `PosClient` поверх Saby Retail/Presto API."""

    name = "saby"

    def __init__(self) -> None:
        self._token: str = ""
        self._token_at: float = 0.0
        self._lock = asyncio.Lock()
        self._menu: dict[int, tuple[str, str]] = {}  # id → (категория, тип позиции)
        self._menu_at: float = 0.0

    # ---------- Авторизация ----------

    async def _login(self) -> None:
        """Сервисная авторизация приложения: ключи из `.env` → токен доступа.

        TTL токена Saby не документирует, поэтому держим его не дольше
        `saby_token_ttl_seconds` и перезапрашиваем при 401 (см. `_get`).
        """
        if not (
            settings.saby_app_client_id and settings.saby_app_secret and settings.saby_secret_key
        ):
            raise RuntimeError("SABY_APP_CLIENT_ID / SABY_APP_SECRET / SABY_SECRET_KEY не заданы")
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(
                settings.saby_auth_url,
                json={
                    "app_client_id": settings.saby_app_client_id,
                    "app_secret": settings.saby_app_secret,
                    "secret_key": settings.saby_secret_key,
                },
            )
            r.raise_for_status()
            token = (r.json() or {}).get("token")
        if not token:
            raise RuntimeError("Saby: авторизация не вернула token")
        self._token, self._token_at = token, time.monotonic()
        logger.info("Saby: сервисный токен получен")

    async def _ensure_token(self) -> str:
        fresh = (
            self._token and (time.monotonic() - self._token_at) < settings.saby_token_ttl_seconds
        )
        if fresh:
            return self._token
        async with self._lock:
            fresh = (
                self._token
                and (time.monotonic() - self._token_at) < settings.saby_token_ttl_seconds
            )
            if not fresh:
                await self._login()
        return self._token

    async def _get(self, path: str, params: dict, _retry: bool = True) -> dict:
        """GET к API Saby с сервисным токеном; при 401 перелогин и один повтор."""
        token = await self._ensure_token()
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.get(
                f"{settings.saby_api_url.rstrip('/')}{path}",
                params=params,
                headers={"X-SBISAccessToken": token},
            )
            if r.status_code in (401, 403) and _retry:
                self._token, self._token_at = "", 0.0
                return await self._get(path, params, _retry=False)
            r.raise_for_status()
            return r.json() or {}

    # ---------- Каталог номенклатуры (категории и тип позиции) ----------

    async def _ensure_menu(self) -> dict[int, tuple[str, str]]:
        """Каталог `id → (категория, тип позиции)`; обновляется не чаще TTL.

        Категория — имя папки, в которой лежит позиция (у Presto вложенность до трёх
        уровней, напр. «Блюда/Дюрюмы/Дюрюм Балык» → категория «Дюрюмы»). Тип позиции
        выводится из КОРНЕВОЙ папки: то, что лежит в «Блюда», — блюдо.
        """
        if self._menu and (time.monotonic() - self._menu_at) < settings.saby_menu_ttl_seconds:
            return self._menu

        items: list[dict] = []
        page = 0
        while True:
            resp = await self._get(
                "/retail/v2/nomenclature/list",
                {"pointId": settings.saby_point_id, "pageSize": 1000, "page": page},
            )
            items += _as_list(resp.get("nomenclatures"))
            if not (resp.get("outcome") or {}).get("hasMore"):
                break
            page += 1
            if page > 50:  # страховка от бесконечной пагинации
                logger.warning("Saby: каталог оборван на 50-й странице")
                break

        by_id = {i.get("id"): i for i in items if i.get("id") is not None}

        def root_name(item: dict, depth: int = 0) -> str:
            parent = by_id.get(item.get("hierarchicalParent"))
            if parent is None or depth > 5:
                return str(item.get("name") or "")
            return root_name(parent, depth + 1)

        menu: dict[int, tuple[str, str]] = {}
        for item in items:
            if item.get("isParent"):
                continue
            parent = by_id.get(item.get("hierarchicalParent")) or {}
            category = str(parent.get("name") or "")
            product_type = _ROOT_PRODUCT_TYPE.get(root_name(item), PRODUCT_TYPE_DISH)
            menu[item["id"]] = (category, product_type)

        self._menu, self._menu_at = menu, time.monotonic()
        logger.info("Saby: каталог обновлён — %d позиций", len(menu))
        return menu

    # ---------- Продажи ----------

    async def _fetch_sales(self, date_from: Date, date_to: Date) -> list[dict]:
        """Все продажи за диапазон (пагинация по 100). Удалённые отбрасываем."""
        key = f"saby:sales:{date_from}:{date_to}"

        async def _load() -> list[dict]:
            out: list[dict] = []
            page = 0
            while True:
                resp = await self._get(
                    "/retail/order/list",
                    {
                        "pointId": settings.saby_point_id,
                        "fromDateTime": f"{date_from.isoformat()} 00:00:00",
                        "toDateTime": f"{date_to.isoformat()} 23:59:59",
                        "page": page,
                        "pageSize": 100,
                        "needDiscountInfo": "true",
                    },
                )
                out += [s for s in _as_list(resp.get("orders")) if not s.get("Deleted")]
                if not (resp.get("outcome") or {}).get("hasMore"):
                    break
                page += 1
                if page > 500:  # ~50 000 чеков за один запрос — дальше явно цикл
                    logger.warning("Saby: выборка продаж оборвана на 500-й странице")
                    break
            return out

        return await cached_or_call(key, _load)

    async def orders(self, date_from: Date, date_to: Date) -> list[PosOrder]:
        """Продажи за диапазон → `PosOrder`. Возвраты не заказы, их здесь нет."""
        sales = await self._fetch_sales(date_from, date_to)
        menu = await self._ensure_menu()
        return [self._to_order(s, menu) for s in sales if not s.get("Return")]

    def _to_order(self, sale: dict, menu: dict[int, tuple[str, str]]) -> PosOrder:
        opened = _dt(sale.get("OpenedWTZ")) or _dt(sale.get("DateWTZ"))
        closed = _dt(sale.get("ClosedWTZ"))
        day = (opened or closed or datetime.min).date()
        items: list[PosItem] = []
        for pos in _as_list(sale.get("SaleNomenclatures")):
            self._collect_items(pos, menu, items)
        # Кассир: в продаже есть только идентификатор (`Teller`); имя не отдаётся,
        # поэтому показываем id — в дашборде это разрез «по кассиру», не табличка ФИО.
        teller = sale.get("Teller")
        return PosOrder(
            number=str(sale.get("Number") or sale.get("Sale") or "").strip(),
            date=day,
            hour=opened.hour if opened else None,
            open_time=_iso(sale.get("OpenedWTZ")) or _iso(sale.get("DateWTZ")),
            close_time=_iso(sale.get("ClosedWTZ")),
            # Числа гостей в API продаж Saby нет. Ставим 1 гостя на чек, а не 0: у этой
            # точки кассир гостей не вводит и iiko отдаёт ровно 1:1 к чекам (проверено
            # на боевой базе, август 2026) — значит единица сохраняет текущие цифры
            # «Гостей» в ОП-отчёте и плане, а ноль обнулил бы их на ровном месте.
            guests=1.0,
            channel=self._channel(items),
            cashier=str(sale.get("SellerName") or (teller and f"#{teller}") or "") or None,
            session_num=str(sale.get("ShiftNumber") or sale.get("Shift") or "") or None,
            items=items,
            payments=self._to_payments(sale),
        )

    def _channel(self, items: list[PosItem]) -> str | None:
        """Канал обслуживания по служебной позиции категории «Статус», если она есть.

        В API продаж Saby признака «в зале / с собой» НЕТ (см. `SABY_API.md`). Но точка
        и в iiko помечает канал не системным полем, а служебным модификатором категории
        «Статус» — и ту же схему можно повторить в меню Presto: папка «Статус» с тремя
        позициями по 0 ₽ («В зале», «С собой», «Доставка»). Тогда канал приезжает в
        позициях продажи и разрез по каналам переживает переезд без потерь.

        Нет такой позиции — `None`, и канал выведется из правила доставки по товарам.
        """
        for it in items:
            if it.category != ORDER_STATUS_CATEGORY:
                continue
            channel = ORDER_STATUS_CHANNELS.get((it.name or "").strip().lower())
            if channel:
                return channel
        return None

    def _collect_items(
        self, pos: dict, menu: dict[int, tuple[str, str]], out: list[PosItem], depth: int = 0
    ) -> None:
        """Позиция продажи (и её дочерние: модификаторы, состав комплекта) → `PosItem`."""
        category, product_type = menu.get(pos.get("Nomenclature"), ("", PRODUCT_TYPE_DISH))
        if pos.get("IsModifier"):
            product_type = PRODUCT_TYPE_MODIFIER
        net = _num(pos.get("TotalPrice"))
        discount = _num(pos.get("TotalDiscount"))
        out.append(
            PosItem(
                name=str(pos.get("Name") or pos.get("ShortName") or "").strip(),
                category=category,
                dish_type=product_type,
                qty=_num(pos.get("Quantity")),
                # брутто = сумма в чеке + скидка: в iiko выручка считалась ДО скидки
                # (`DishSumInt`), и разрезы дашборда ждут ту же базу.
                sum=round(net + discount, 2),
                net=net,
                # плановая с/с — аналог `ProductCostBase` в iiko (расчёт по ТТК кассы);
                # фактическая (`TotalCost`) появляется после проведения складских
                # документов, поэтому она резервная.
                cost=_num(pos.get("PlannedCost")) or _num(pos.get("TotalCost")),
            )
        )
        if depth < 3:
            for child in _as_list(pos.get("Positions")):
                self._collect_items(child, menu, out, depth + 1)

    def _to_payments(self, sale: dict) -> list[PosPayment]:
        """Чеки продажи → оплаты по способам (нал / карта / сертификат / зарплата)."""
        agg: dict[str, float] = {}

        def add(pay_type: str, amount: float) -> None:
            if amount:
                agg[pay_type] = round(agg.get(pay_type, 0.0) + amount, 2)

        for pay in _as_list(sale.get("Payments")):
            bank_type = str(pay.get("BankType") or "").strip()
            add(_PAY_CASH, _num(pay.get("CashSum")) or _num(pay.get("PayCash")))
            add(
                f"{_PAY_CARD} ({bank_type})" if bank_type else _PAY_CARD,
                _num(pay.get("BankSum")) or _num(pay.get("PayBank")),
            )
            add(
                _PAY_CERTIFICATE,
                _num(pay.get("CertificateSum")) or _num(pay.get("PayCertificate")),
            )
            add(_PAY_SALARY, _num(pay.get("PaySalary")) or _num(pay.get("SalarySum")))
        return [PosPayment(pay_type=p, amount=a) for p, a in agg.items()]

    # ---------- Агрегаты: считаем сами, касса их не умеет ----------

    async def products(self, day: Date) -> list[PosProduct]:
        return aggregate_products(await self.orders(day, day))

    async def revenue_days(self, date_from: Date, date_to: Date) -> list[PosDay]:
        """Сводка по дням из заказов + число возвратов (продажи с `Return = true`)."""
        sales = await self._fetch_sales(date_from, date_to)
        menu = await self._ensure_menu()
        orders = [self._to_order(s, menu) for s in sales if not s.get("Return")]
        days = aggregate_days(orders)

        refunds: dict[Date, int] = {}
        for sale in sales:
            if not sale.get("Return"):
                continue
            moment = _dt(sale.get("OpenedWTZ")) or _dt(sale.get("DateWTZ"))
            if moment:
                refunds[moment.date()] = refunds.get(moment.date(), 0) + 1
        for day in days:
            day.refund_count = refunds.get(day.date, 0)
        return days

    async def hourly(self, date_from: Date, date_to: Date) -> dict[int, PosHour]:
        return aggregate_hours(await self.orders(date_from, date_to))

    async def open_orders(self, day: Date) -> list[PosOpenOrder]:
        """Заказы дня для табло. Дешевле, чем полная выборка, Saby не умеет."""
        sales = await self._fetch_sales(day, day)
        out = []
        for sale in sales:
            if sale.get("Return"):
                continue
            number = str(sale.get("Number") or "").strip()
            open_time = _iso(sale.get("OpenedWTZ")) or _iso(sale.get("DateWTZ"))
            if number and open_time:
                out.append(PosOpenOrder(number=number, open_time=open_time))
        return out

    async def history_start(self) -> Date | None:
        """Начало истории. Probe по продажам Saby не поддерживает — берём из настройки.

        Дата подключения кассы известна человеку, а перебирать годы запросами по 100
        чеков ради одной даты незачем: `HISTORY_START_DATE` в `.env` решает это точно.
        """
        return settings.history_start_date

    async def warm(self) -> None:
        """Обновить токен и каталог заранее, чтобы синк не тратил на это время."""
        await self._ensure_token()
        await self._ensure_menu()
