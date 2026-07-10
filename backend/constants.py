"""
Константы предметной области iiko: коды метрик, типы данных, справочные маппинги.

Вынесено в один модуль, чтобы не плодить «магические» строки по коду и чтобы было
видно, какие именно метрики/разрезы мы используем. Подробности — в `IIKO_WEB_API.md`.
"""

# ─── Дни недели (индекс = date.weekday(): 0 = понедельник) ───────────────────
DAY_NAMES_EN = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]
DAY_NAMES_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

# Группы дней недели для слоя «План» (та же логика, что в WEEKDAY_GROUPS на фронте):
# Пн и Чт — особые, Вт-Ср — обычные, Пт-Вс — выходные. План задаётся дневной нормой
# на (дейпарт × группа) и масштабируется на число подходящих дней периода.
WEEKDAY_GROUPS = [
    {"key": "mon", "label": "Пн", "weekdays": [0]},
    {"key": "ordinary", "label": "Вт–Ср", "weekdays": [1, 2]},
    {"key": "thu", "label": "Чт", "weekdays": [3]},
    {"key": "weekend", "label": "Пт–Вс", "weekdays": [4, 5, 6]},
]
# weekday() (0=Пн) → ключ группы
WEEKDAY_TO_GROUP = {wd: g["key"] for g in WEEKDAY_GROUPS for wd in g["weekdays"]}


# ─── Дейпарты (операционные окна дня) ────────────────────────────────────────
# Границы взяты из исторического «свода» ресторана (ручной Excel-план): Завтрак /
# Ланч / Полдник / Ужин / Ночь. Каждый час суток попадает ровно в один дейпарт —
# почасовая выручка сворачивается в эти окна (см. `/api/revenue/by-daypart`).
DAYPARTS = [
    {"key": "breakfast", "label": "Завтрак", "range": "08–12", "hours": [8, 9, 10, 11]},
    {"key": "lunch", "label": "Ланч", "range": "12–16", "hours": [12, 13, 14, 15]},
    {"key": "afternoon", "label": "Полдник", "range": "16–18", "hours": [16, 17]},
    {"key": "dinner", "label": "Ужин", "range": "18–23", "hours": [18, 19, 20, 21, 22]},
    {
        "key": "night",
        "label": "Ночь",
        "range": "23–08",
        "hours": [23, 0, 1, 2, 3, 4, 5, 6, 7],
    },
]


# ─── Типы данных запроса POST /api/kpi/dashboard/get-data ────────────────────
# Определяют разрез ответа (ключ значения): итог / по дням / по блюдам / по часам.
DATA_TOTAL = "DATA_TOTAL"  # одно число за период
DATA_SUMMARY_BY_DATE = "DATA_SUMMARY_BY_DATE"  # разбивка по дням (ключ = дата)
DATA_DETAILS = "DATA_DETAILS"  # разбивка по блюдам (ключ = UUID) + decoration
DATA_SUMMARY_BY_HOURS = "DATA_SUMMARY_BY_HOURS"  # матрица часы×даты


# ─── Коды метрик iiko ────────────────────────────────────────────────────────
METRIC_REV_GROSS = "REV_GROSS"  # выручка
METRIC_TRN_ALL = "TRN_ALL"  # кол-во чеков/заказов
METRIC_AVG_SPEND = "AVERAGE_SPEND_GROSS"  # средний чек
METRIC_DISCOUNT = "ACC_CAT_DISCOUNT_AMT"  # скидки
METRIC_REFUNDS = "REFUND_TRN"  # возвраты
METRIC_COST = "PRODUCTS_USAGE_THEO_AMT"  # себестоимость (теоретич. расход продуктов по ТТК)
METRIC_FOODCOST_PCT = "PRODUCTS_COS_THEO_GROSS"  # food cost % (с/с к выручке)
METRIC_ITEM_QTY = "ITEM_SOLD_QTY"  # продано блюд, кол-во
METRIC_ITEM_AMT = "ITEM_SOLD_AMT"  # продано блюд, выручка

# Группы метрик под конкретные запросы клиента iiko
METRICS_REVENUE_DAILY = [
    METRIC_REV_GROSS,
    METRIC_TRN_ALL,
    METRIC_AVG_SPEND,
    METRIC_DISCOUNT,
    METRIC_REFUNDS,
    METRIC_COST,
]
METRICS_DISHES = [METRIC_ITEM_QTY, METRIC_ITEM_AMT, METRIC_COST]
METRICS_TOTALS = [
    METRIC_REV_GROSS,
    METRIC_TRN_ALL,
    METRIC_AVG_SPEND,
    METRIC_ITEM_QTY,
    METRIC_COST,
    METRIC_FOODCOST_PCT,
]
METRICS_HOURLY = [METRIC_REV_GROSS, METRIC_TRN_ALL]

# Человекочитаемые названия метрик (для UI/отладки)
METRIC_LABELS = {
    METRIC_REV_GROSS: "Выручка",
    METRIC_TRN_ALL: "Чеки",
    METRIC_AVG_SPEND: "Средний чек",
    METRIC_DISCOUNT: "Скидки",
    METRIC_REFUNDS: "Возвраты",
    METRIC_COST: "Себестоимость",
    METRIC_FOODCOST_PCT: "Food cost %",
    METRIC_ITEM_QTY: "Продано, кол-во",
    METRIC_ITEM_AMT: "Продано, выручка",
}


# ─── Типы номенклатуры iiko (productType) ────────────────────────────────────
PRODUCT_TYPE_DISH = "DISH"  # блюдо
PRODUCT_TYPE_GOODS = "GOODS"  # товар/ингредиент
PRODUCT_TYPE_MODIFIER = "MODIFIER"  # модификатор (в т.ч. тип обслуживания)

# Категория-маркер типа обслуживания заказа: модификаторы «Доставка» / «В зале» / «С собой».
# В «Продажах блюд» эти строки — не блюда; используются для распределения чеков по типу.
ORDER_STATUS_CATEGORY = "Статус"

# Нетоварные категории — не считаются позициями чека (служебные строки заказа).
NON_PRODUCT_CATEGORIES = {ORDER_STATUS_CATEGORY, "модификаторы"}

# Меню-категория доставки: ВСЁ, что лежит в ней, продано в доставку (бизнес-правило).
# Используется в разрезе блюдо×канал и для бейджа «доставка».
DELIVERY_CATEGORY = "Доставка"

# Маркер доставки в имени позиции: блюда с `_д` (напр. «Дюрюм_д») продаются в доставку,
# даже если лежат не в категории «Доставка». Дополняет DELIVERY_CATEGORY (см. utils.is_delivery).
DELIVERY_NAME_MARKER = "_д"

# Отображаемые имена меню-категорий iiko: переименование «как видит гость на дашборде»,
# не трогая саму iiko (мы туда не пишем). Применяется ЕДИНО на выходе всех разрезов
# (см. utils.display_category) — и в подписях, и в ключах, чтобы drill-down не ломался.
# «Меню» — дефолтная корзина iiko с допами/соусами (Фри, Дип, Кетчуп…), название невнятное.
CATEGORY_DISPLAY = {
    "Меню": "Допы и соусы",
}

# Группы категорий для food cost % по типу продукта (нижний блок Excel-свода «ОП»):
# Еда / Напитки / Алкоголь. У точки алкоголя нет, но маппинг держим на будущее.
# Любая продуктовая меню-категория, не попавшая в напитки/алкоголь, считается «Едой».
DRINK_CATEGORIES = {"Напитки"}
ALCOHOL_CATEGORIES: set[str] = set()
CATEGORY_GROUP_FOOD = "Еда"
CATEGORY_GROUP_DRINK = "Напитки"
CATEGORY_GROUP_ALCOHOL = "Алкоголь"
# Порядок отображения групп в отчёте
CATEGORY_GROUP_ORDER = [CATEGORY_GROUP_FOOD, CATEGORY_GROUP_DRINK, CATEGORY_GROUP_ALCOHOL]


# ─── OLAP-движок iiko (асинхронные отчёты SALES) ─────────────────────────────
# Поток: POST /api/olap/init (тело=запрос) → GET /api/olap/fetch-status/{hash}
# (поллинг до SUCCESS) → POST /api/olap/fetch/{hash}/{view} (тело=запрос) → result.
OLAP_TYPE_SALES = "SALES"
OLAP_VIEW_SIMPLE = "simple"
OLAP_STATUS_SUCCESS = "SUCCESS"
OLAP_STATUS_ERROR = "ERROR"

# Поля OLAP SALES
OLAP_FIELD_HOUR = "HourOpen"  # час открытия (группировка)
OLAP_FIELD_DISH_CATEGORY = "DishCategory"
OLAP_FIELD_DISH_NAME = "DishName"
OLAP_FIELD_DISH_TYPE = "DishType"  # DISH / MODIFIER / GOODS (тип позиции, в самом OLAP)
OLAP_FIELD_SUM = "DishSumInt"  # сумма без скидки (выручка)
OLAP_FIELD_QTY = "DishAmountInt"  # количество
OLAP_FIELD_GUESTS = "GuestNum"  # число гостей (атрибут заказа, повторяется по строкам)
OLAP_FIELD_COST = "ProductCostBase.ProductCost"  # себестоимость iiko по позиции
OLAP_FIELD_NET = "DishDiscountSumInt"  # выручка после скидки (= брутто, скидок нет)
OLAP_FILTER_DATE = "OpenDate.Typed"  # поле фильтра по дате
OLAP_FIELD_OPEN_DATE = "OpenDate.Typed"  # дата заказа (группировка, ISO YYYY-MM-DD)
# Заказ-уровневые атрибуты (для таблицы orders): время, касса, зал/стол, оплата
OLAP_FIELD_OPEN_TIME = "OpenTime"  # ISO-таймстамп открытия заказа
OLAP_FIELD_CLOSE_TIME = "CloseTime"  # ISO-таймстамп закрытия заказа
OLAP_FIELD_CASHIER = "Cashier"  # кассир
OLAP_FIELD_SESSION = "SessionNum"  # номер кассовой смены
OLAP_FIELD_SECTION = "RestaurantSection"  # зал/секция
OLAP_FIELD_TABLE = "TableNum"  # номер стола
OLAP_FIELD_PAYTYPES = "PayTypes"  # способ оплаты (нал/карта/агрегатор; может быть сплит)

# Тип обслуживания заказа (доставка / с собой / в зале) для разреза блюдо×канал (#4).
# ⚠️ Имя поля подобрано по стандарту iiko OLAP SALES — ПРОВЕРИТЬ на живом API через
# GET /api/dishes/order-types; при ошибке OLAP заменить на верное (напр. "ServiceType").
OLAP_FIELD_ORDER_TYPE = "OrderType"

# Каналы обслуживания — наши канон-значения (в т.ч. для постфикса _д = доставка).
CHANNEL_DELIVERY = "доставка"
CHANNEL_TAKEAWAY = "с собой"
CHANNEL_DINEIN = "в зале"

# Тип обслуживания у этой точки ведётся НЕ через OrderType (он пуст), а модификатором
# категории «Статус» на уровне заказа. Маппинг значений модификатора → наши каналы.
ORDER_STATUS_CHANNELS = {
    "в зале": CHANNEL_DINEIN,
    "с собой": CHANNEL_TAKEAWAY,
    "доставка": CHANNEL_DELIVERY,
}

# Группировка способов оплаты (`order_payments.pay_type`) в укрупнённые группы для
# виджета структуры выручки. Сопоставление по подстроке (регистронезависимо), чтобы
# пережить вариации названий терминалов/агрегаторов. Неизвестное → «Прочее».
PAYMENT_CARD = "Карта"
PAYMENT_CASH = "Наличные"
PAYMENT_AGGREGATOR = "Агрегатор"
PAYMENT_OTHER = "Прочее"
# (подстрока в pay_type, lower) → группа; первое совпадение выигрывает
PAYMENT_GROUP_RULES = (
    ("терминал", PAYMENT_CARD),
    ("карт", PAYMENT_CARD),
    ("наличн", PAYMENT_CASH),
    ("яндекс", PAYMENT_AGGREGATOR),
    ("деливери", PAYMENT_AGGREGATOR),
    ("delivery", PAYMENT_AGGREGATOR),
    ("достав", PAYMENT_AGGREGATOR),
)
# Порядок групп в выдаче/легенде
PAYMENT_GROUP_ORDER = (PAYMENT_CARD, PAYMENT_CASH, PAYMENT_AGGREGATOR, PAYMENT_OTHER)

# Поле-идентификатор заказа в OLAP SALES (для связи блюд заказа с его «Статусом»).
OLAP_FIELD_ORDER_NUM = "OrderNum"

# ── P&L дня ────────────────────────────────────────────────────────────────
# Бенчмарки строк P&L из финансовой модели ресторана (Google Sheet). Для каждой
# строки: dir — «low» (меньше = лучше) или «high» (больше = лучше), good/warn —
# границы зелёного/жёлтого (иначе красный), unit — «pct» (доля выручки) или «rub».
# Раскраска: dir=low → ≤good зелёный, ≤warn жёлтый, иначе красный; dir=high наоборот.
PNL_DIR_LOW = "low"
PNL_DIR_HIGH = "high"
PNL_BENCHMARKS = {
    "avg_check": {"dir": PNL_DIR_HIGH, "good": 600, "warn": 500, "unit": "rub"},
    "checks_per_day": {"dir": PNL_DIR_HIGH, "good": 110, "warn": 90, "unit": "num"},
    "checks_per_hour": {"dir": PNL_DIR_HIGH, "good": 10, "warn": 7, "unit": "num"},
    "writeoffs": {"dir": PNL_DIR_LOW, "good": 3, "warn": 5, "unit": "pct"},
    "food_cost": {"dir": PNL_DIR_LOW, "good": 27, "warn": 32, "unit": "pct"},
    "packaging": {"dir": PNL_DIR_LOW, "good": 2, "warn": 3, "unit": "pct"},
    "chemicals": {"dir": PNL_DIR_LOW, "good": 1, "warn": 2, "unit": "pct"},
    "supplies": {"dir": PNL_DIR_LOW, "good": 1, "warn": 2, "unit": "pct"},
    "cogs": {"dir": PNL_DIR_LOW, "good": 27, "warn": 32, "unit": "pct"},
    "labor_op": {"dir": PNL_DIR_LOW, "good": 23, "warn": 27, "unit": "pct"},
    "labor_admin": {"dir": PNL_DIR_LOW, "good": 6, "warn": 7, "unit": "pct"},
    # весь ФОТ (операц. + админ) % от выручки — метрика «All Labor» из модели
    "all_labor": {"dir": PNL_DIR_LOW, "good": 24, "warn": 29, "unit": "pct"},
    "prime_cost": {"dir": PNL_DIR_LOW, "good": 48, "warn": 53, "unit": "pct"},
    "production_cost": {"dir": PNL_DIR_LOW, "good": 60, "warn": 65, "unit": "pct"},
    "rent": {"dir": PNL_DIR_LOW, "good": 8, "warn": 12, "unit": "pct"},
    "utilities": {"dir": PNL_DIR_LOW, "good": 4, "warn": 6, "unit": "pct"},
    "marketing": {"dir": PNL_DIR_LOW, "good": 5, "warn": 7, "unit": "pct"},
    "other_opex": {"dir": PNL_DIR_LOW, "good": 6, "warn": 8, "unit": "pct"},
    "contingency": {"dir": PNL_DIR_LOW, "good": 2, "warn": 3, "unit": "pct"},
    "all_expenses": {"dir": PNL_DIR_LOW, "good": 80, "warn": 90, "unit": "pct"},
    "ebitda_margin": {"dir": PNL_DIR_HIGH, "good": 18, "warn": 10, "unit": "pct"},
    # чистая маржа (после налога УСН и кап-резерва) — ниже EBITDA-порога: типичная
    # чистая рентабельность общепита 5–10 %
    "net_margin": {"dir": PNL_DIR_HIGH, "good": 10, "warn": 5, "unit": "pct"},
}

# Ручные ₽-поля PnlMonth (месячная сумма, аллоцируется на день) и их подписи.
# Операционный ФОТ здесь НЕТ — он из графика смен (`routers/schedule.py`).
# АДМИН-ФОТ (`labor_admin`) — постоянный расход, вводится/импортируется отдельной
# строкой (управляющий), отделён от «Прочие».
PNL_MANUAL_FIELDS = [
    ("rent", "Аренда"),
    ("utilities", "Коммуналка"),
    ("marketing", "Маркетинг"),
    ("labor_admin", "Админ. ФОТ (управляющий)"),
    ("other_opex", "Прочие (IT/ОФД/эквайринг/аморт.)"),
    ("packaging", "Упаковка"),
    ("writeoffs", "Списания"),
    ("contingency", "Непредвиденные"),
    ("cap_reserve", "Кап-резерв"),
]
# Классификация затрат для маржинального анализа (contribution margin + безубыточность).
# Переменные растут с продажами (food cost/упаковка/списания + авто налог и агрегатор),
# постоянные — фикс на месяц (аренда + ФОТ из графика/…), уже оплачены независимо от
# дневных продаж. ФОТ добавляется к постоянным отдельно (из графика, не из PnlMonth).
# Дневные переменные статьи (вводятся по дням в `PnlDayCost`, а не помесячно).
# packaging/writeoffs имеют помесячный резерв в `PnlMonth` (если за день нет строки),
# chemicals/supplies — чисто дневные (помесячного поля нет, при отсутствии дня = 0).
PNL_DAY_COST_FIELDS = [
    ("writeoffs", "Списания"),
    ("packaging", "Упаковка"),
    ("chemicals", "Химия / моющие"),
    ("supplies", "Расходники (салфетки/перчатки)"),
]

PNL_VARIABLE_MANUAL = ["packaging", "writeoffs"]
PNL_FIXED_MANUAL = [
    "rent",
    "utilities",
    "marketing",
    "labor_admin",
    "other_opex",
    "contingency",
    "cap_reserve",
]

# Ставки-% и конфиг PnlMonth (не аллоцируются, применяются к выручке / берутся как есть).
PNL_RATE_FIELDS = [
    ("tax_pct", "Налог (УСН), %"),
    ("aggregator_pct", "Удержание агрегатора, %"),
    ("work_hours", "Рабочих часов в день"),
]
