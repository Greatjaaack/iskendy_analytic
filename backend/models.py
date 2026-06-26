"""Модели БД (SQLAlchemy, SQLite).

Две группы таблиц: продажи из iiko (`revenue_daily`, `dish_sales`, `sync_log`) и
учёт костов (`suppliers`, `supplier_files`, `ingredients`, `supplier_prices`, `ttk`,
`ttk_ingredients`, `dish_mappings`). Миграций нет — при смене схемы пересоздаём БД.
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    create_engine,
    inspect,
    text,
)
from sqlalchemy.orm import DeclarativeBase, relationship, sessionmaker

from config import settings

engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)


class Base(DeclarativeBase):
    pass


class RevenueDaily(Base):
    __tablename__ = "revenue_daily"

    date = Column(Date, primary_key=True)
    day_of_week = Column(String)
    total_sum = Column(Float, default=0)  # REV_GROSS
    discount_sum = Column(Float, default=0)  # ACC_CAT_DISCOUNT_AMT
    refund_count = Column(Integer, default=0)  # REFUND_TRN
    cost_sum = Column(Float, default=0)  # PRODUCTS_USAGE_THEO_AMT (себестоимость)
    check_count = Column(Integer, default=0)  # TRN_ALL
    avg_check = Column(Float, default=0)  # AVERAGE_SPEND_GROSS
    updated_at = Column(DateTime, default=datetime.utcnow)


class DishSale(Base):
    __tablename__ = "dish_sales"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date_from = Column(Date)
    date_to = Column(Date)
    dish_id = Column(String)
    dish_name = Column(String)
    group_id = Column(String)
    group_name = Column(String)
    quantity = Column(Float, default=0)
    revenue = Column(Float, default=0)
    cost_sum = Column(Float, default=0)
    updated_at = Column(DateTime, default=datetime.utcnow)


class OrderItem(Base):
    """Заказ-уровень (одна строка = позиция заказа за день) — источник всех
    OLAP-разрезов из БД. Заполняется по дню из olap_sales; служит для пересчёта
    состава/сочетаемости/наполненности чека, почасовых разрезов, ОП-отчёта и т.д.
    без живого запроса. `guests` — атрибут заказа (повторяется в строках заказа).
    """

    __tablename__ = "order_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, index=True)
    hour = Column(Integer)
    order_num = Column(String)
    category = Column(String)
    name = Column(String)
    dish_type = Column(String)  # DISH / MODIFIER / GOODS (из OLAP)
    qty = Column(Float, default=0)  # DishAmountInt
    sum = Column(Float, default=0)  # DishSumInt (выручка без скидки)
    net = Column(Float, default=0)  # DishDiscountSumInt (после скидки)
    cost = Column(Float, default=0)  # ProductCostBase.ProductCost (с/с iiko)
    guests = Column(Float, default=0)  # GuestNum (на заказ)


class DishDetail(Base):
    """Per-day выгрузка блюд (get-data DATA_DETAILS) — источник таблицы «Продажи
    блюд» и набора модификаторов (`product_type`, которого нет в OLAP). По дню,
    чтобы отдавать произвольные периоды суммированием.
    """

    __tablename__ = "dish_detail"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, index=True)
    dish_id = Column(String)
    dish_name = Column(String)
    category = Column(String)
    product_type = Column(String)
    quantity = Column(Float, default=0)
    revenue = Column(Float, default=0)
    cost_sum = Column(Float, default=0)


class Order(Base):
    """Чек (заказ) как сущность — для будущей аналитики по чекам. Одна строка =
    один заказ; денормализованный срез из `order_items` (канал из «Статуса»,
    число гостей, сумма, число позиций). Текущие эндпоинты её не читают —
    источник истины остаётся `order_items`; заполняется тем же синком.
    """

    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, index=True)
    order_num = Column(String)  # номер чека (id заказа в iiko)
    hour = Column(Integer)  # час открытия (минимальный по позициям)
    weekday = Column(Integer)  # день недели 0=Пн..6=Вс (для группировок)
    daypart = Column(String)  # дейпарт по часу (Завтрак/Ланч/…), services.daypart
    channel = Column(String)  # канал из «Статуса»: в зале / с собой / доставка
    is_delivery = Column(Boolean, default=False)  # бизнес-правило доставки (категория/_д)
    guests = Column(Float, default=0)  # GuestNum
    total_sum = Column(Float, default=0)  # сумма позиций заказа
    cost_sum = Column(Float, default=0)  # с/с iiko по позициям заказа
    item_count = Column(Float, default=0)  # число позиций (сумма qty, без «Статуса»)
    dish_count = Column(Integer, default=0)  # число РАЗНЫХ позиций (без «Статуса»)
    # заказ-уровневые атрибуты из OLAP (отдельный запрос)
    pay_type = Column(String)  # способ оплаты (нал/карта/агрегатор; сплит — через «, »)
    table_num = Column(String)  # номер стола
    section = Column(String)  # зал/секция
    cashier = Column(String)  # кассир
    session_num = Column(String)  # номер кассовой смены
    open_time = Column(String)  # ISO-таймстамп открытия
    close_time = Column(String)  # ISO-таймстамп закрытия
    duration_min = Column(Float)  # длительность обслуживания, мин (close - open)


class OrderPayment(Base):
    """Оплата заказа по способу (нормализация `orders.pay_type`): один заказ — одна
    или несколько строк (сплит-оплата). `amount` — сумма по этому способу (OLAP
    делит корректно). Для аналитики структуры выручки нал/карта/агрегатор.
    """

    __tablename__ = "order_payments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, index=True)
    order_num = Column(String)
    pay_type = Column(String)
    amount = Column(Float, default=0)


class SyncLog(Base):
    __tablename__ = "sync_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sync_type = Column(String)
    status = Column(String)
    message = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


# ---------- Поставщики, номенклатура, ТТК (Фазы 1–3) ----------


class Supplier(Base):
    __tablename__ = "suppliers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, unique=True, index=True)
    address = Column(String, default="")
    min_delivery = Column(String, default="")  # мин. поставка (текстом: сумма/условия)
    comment = Column(String, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    files = relationship("SupplierFile", back_populates="supplier", cascade="all, delete-orphan")
    prices = relationship("SupplierPrice", back_populates="supplier", cascade="all, delete-orphan")
    contacts = relationship(
        "SupplierContact", back_populates="supplier", cascade="all, delete-orphan"
    )


class SupplierContact(Base):
    """Контакт поставщика: телефон + контактное лицо (много на одного поставщика)."""

    __tablename__ = "supplier_contacts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"))
    contact_person = Column(String, default="")  # чьё это лицо/роль
    phone = Column(String, default="")  # нормализованный «+7XXXXXXXXXX»
    whatsapp = Column(String, default="")  # номер WhatsApp (нормализованный)
    telegram = Column(String, default="")  # @username или ссылка
    email = Column(String, default="")
    comment = Column(String, default="")  # напр. «склад», «бухгалтерия»
    created_at = Column(DateTime, default=datetime.utcnow)

    supplier = relationship("Supplier", back_populates="contacts")


class SupplierFile(Base):
    __tablename__ = "supplier_files"

    id = Column(Integer, primary_key=True, autoincrement=True)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"))
    filename = Column(String)  # оригинальное имя
    path = Column(String)  # путь в /data/files
    file_type = Column(String, default="other")  # invoice | price | other
    uploaded_at = Column(DateTime, default=datetime.utcnow)

    supplier = relationship("Supplier", back_populates="files")


class Ingredient(Base):
    """Каталог-номенклатура: ингредиенты/продукты из ТТК и матриц."""

    __tablename__ = "ingredients"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String)
    name_norm = Column(String, unique=True, index=True)  # lower/trim — ключ связывания
    unit = Column(String, default="")  # г / мл / шт
    iiko_product_id = Column(String, nullable=True)  # связь с iiko (Фаза 6)
    created_at = Column(DateTime, default=datetime.utcnow)

    prices = relationship(
        "SupplierPrice", back_populates="ingredient", cascade="all, delete-orphan"
    )


class SupplierPrice(Base):
    __tablename__ = "supplier_prices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"))
    ingredient_id = Column(Integer, ForeignKey("ingredients.id"))
    brand = Column(String, default="")  # торговая марка товара у этого поставщика
    pack_size = Column(Float, nullable=True)  # вес/объём упаковки в ед.изм ингредиента
    pack_unit = Column(String, default="")
    pack_price = Column(Float, nullable=True)  # стоимость упаковки
    unit_price = Column(Float, nullable=True)  # цена за 1 ед.изм.
    price_date = Column(Date, nullable=True)  # дата проценки
    source = Column(String, default="import")  # import | invoice
    created_at = Column(DateTime, default=datetime.utcnow)

    supplier = relationship("Supplier", back_populates="prices")
    ingredient = relationship("Ingredient", back_populates="prices")


class Ttk(Base):
    """Тех-тех карта (блюдо или полуфабрикат)."""

    __tablename__ = "ttk"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String)
    name_norm = Column(String, index=True)
    category = Column(String, default="")
    is_semi = Column(Boolean, default=False)  # п/ф
    yield_qty = Column(Float, nullable=True)  # выход
    yield_unit = Column(String, default="")
    cost_total = Column(Float, default=0)  # с/с по рецепту (за выход карты), из листа ТТК
    sale_price = Column(Float, nullable=True)  # цена продажи (из листа «Сводная»)
    cost_full = Column(
        Float, nullable=True
    )  # с/с ПОРЦИИ «общая» (продукты+списания+упаковка), «Сводная»
    dish_iiko_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    lines = relationship(
        "TtkIngredient",
        back_populates="ttk",
        foreign_keys="TtkIngredient.ttk_id",
        cascade="all, delete-orphan",
    )


class TtkIngredient(Base):
    """Строка состава ТТК: либо сырьё (ingredient_id), либо п/ф (child_ttk_id)."""

    __tablename__ = "ttk_ingredients"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ttk_id = Column(Integer, ForeignKey("ttk.id"))
    raw_name = Column(String, default="")  # исходный текст строки (для нематчащихся п/ф)
    ingredient_id = Column(Integer, ForeignKey("ingredients.id"), nullable=True)
    child_ttk_id = Column(Integer, ForeignKey("ttk.id"), nullable=True)
    gross = Column(Float, nullable=True)
    net = Column(Float, nullable=True)
    unit = Column(String, default="")
    waste_pct = Column(Float, nullable=True)
    cost_rub = Column(Float, nullable=True)

    ttk = relationship("Ttk", back_populates="lines", foreign_keys=[ttk_id])
    ingredient = relationship("Ingredient")
    child_ttk = relationship("Ttk", foreign_keys=[child_ttk_id])


class DishMapping(Base):
    """Привязка проданного блюда (название в продажах iiko) к ТТК.

    Нужна, т.к. POS-названия продаж не совпадают с названиями ТТК/«Сводной»
    (продаётся «Зурна», в ТТК — «Искандер дюрюм Zurna»). По этой привязке берётся
    себестоимость порции для расчёта с/с % в «Продажах блюд».
    """

    __tablename__ = "dish_mappings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sale_name = Column(String)  # как называется в продажах
    sale_name_norm = Column(String, unique=True, index=True)  # ключ сопоставления
    ttk_id = Column(Integer, ForeignKey("ttk.id"))
    created_at = Column(DateTime, default=datetime.utcnow)

    ttk = relationship("Ttk")


class DaypartPlan(Base):
    """План (цель) по дейпарту × группе дня недели — дневная норма на сегмент.

    Гранулярность: ОДИН день каждого сегмента (дейпарт × группа дня недели:
    Пн / Вт-Ср / Чт / выходные Пт-Вс). План на период считается умножением нормы
    на число подходящих дней в периоде — так `% к плану` честен для день/неделя/MTD/
    диапазона (месячный план в Excel врал на неполном месяце). Заполняется автосидом
    из истории (`POST /api/plan/seed-from-history`) и правится вручную.
    """

    __tablename__ = "daypart_plan"

    id = Column(Integer, primary_key=True, autoincrement=True)
    daypart_key = Column(String, index=True)  # ключ дейпарта (DAYPARTS)
    weekday_group = Column(String, index=True)  # ключ группы дня недели (WEEKDAY_GROUPS)
    revenue = Column(Float, default=0.0)  # дневная норма выручки
    avg_check = Column(Float, default=0.0)  # целевой средний чек
    guests = Column(Float, default=0.0)  # дневная норма гостей
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (UniqueConstraint("daypart_key", "weekday_group", name="uq_daypart_group"),)


def init_db():
    # До-миграция ПРОИЗВОДНЫХ таблиц (order_items/dish_detail/orders): create_all не
    # добавляет колонки в существующую таблицу. Эти таблицы — снимок из iiko
    # (пересобираются бэкафиллом), поэтому при дрейфе схемы безопасно пересоздать —
    # данные не теряются (косты/ТТК/поставщики в других таблицах не трогаются).
    # Сентинел-колонка на таблицу: её отсутствие = старая схема → DROP.
    derived_sentinels = {
        "order_items": "dish_type",
        "orders": "pay_type",
    }
    insp = inspect(engine)
    existing = set(insp.get_table_names())
    with engine.begin() as conn:
        for table, sentinel in derived_sentinels.items():
            if table in existing:
                cols = {c["name"] for c in insp.get_columns(table)}
                if sentinel not in cols:
                    conn.execute(text(f"DROP TABLE {table}"))
    Base.metadata.create_all(bind=engine)
