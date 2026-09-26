"""Справочные выборки по номенклатуре: с/с позиции от кассы и фильтр модификаторов.

**Фильтр модификаторов.** Разрез по заказам не знает тип позиции (в строках его нет),
поэтому имена и категории модификаторов берутся из `dish_detail` (`productType=MODIFIER`)
и отсеиваются в разрезах: «Разрезать 1/2» — не блюдо. ⚠️ Категория отсекается ТОЛЬКО если
она целиком модификаторная: «Напитки» и «Доставка» содержат и блюда, и платные добавки, и
однажды отсев по категории убирал из всех разрезов «Напитки» — третью по выручке категорию.

**С/с позиции от кассы** нужна там, где нет привязки к нашей ТТК: считается как
себестоимость ÷ количество по данным кассы за период.

Вынесено из `routers/dishes.py` (этап 7а аудита).
"""

from constants import (
    OLAP_FIELD_COST,
    OLAP_FIELD_DISH_NAME,
    OLAP_FIELD_QTY,
    PRODUCT_TYPE_MODIFIER,
)
from services.order_store import dish_detail_rows, order_rows
from utils import normalize_name


async def iiko_unit_cost_by_name(date_from: str, date_to: str) -> dict[str, float]:
    """С/с ОДНОЙ порции по нормализованному имени = iiko-с/с позиций (`ProductCostBase`)
    ÷ проданное количество за период.

    Единый источник food cost для всех экранов — позиции заказов (`order_items.cost`),
    как их отдаёт iiko. Легаси-костинг по ТТК-файлу (`cost_full`/`DishMapping`) больше
    не используется. Возвращаем УДЕЛЬНУЮ с/с (а не суммарную): одному нормализованному
    имени в списке блюд может соответствовать несколько позиций номенклатуры (dish_id) —
    суммарная с/с задвоилась бы на каждой из них, а удельная × qty блюда корректна.
    """
    rows = await order_rows(
        group_fields=[OLAP_FIELD_DISH_NAME],
        data_fields=[OLAP_FIELD_COST, OLAP_FIELD_QTY],
        date_from=date_from,
        date_to=date_to,
    )
    agg: dict[str, list[float]] = {}
    for r in rows:
        name = r.get("field0", {}).get("value", "")
        if not name:
            continue
        cost = float(r.get("field1", {}).get("value", 0) or 0)
        qty = float(r.get("field2", {}).get("value", 0) or 0)
        a = agg.setdefault(normalize_name(name), [0.0, 0.0])
        a[0] += cost
        a[1] += qty
    # только реально прокостованные имена: у части позиций (доставочные дубли
    # «…доставка»/«_д») iiko не проставляет ProductCostBase → с/с 0. Такие блюда должны
    # показывать «—» (has_cost=False), а не мнимые 0% food cost / 100% маржу.
    return {k: c / q for k, (c, q) in agg.items() if c > 0 and q > 0}


async def modifier_filters(date_from_iso: str, date_to_iso: str) -> tuple[set[str], set[str]]:
    """(норм. имена, категории) платных модификаторов за период.

    OLAP SALES не отдаёт productType, поэтому набор модификаторов («Разрезать 1/2» и пр.)
    берём из `dishes_detail` (get-data, там есть productType) и исключаем их из
    OLAP-разрезов продаж: модификаторы — не блюда и в продажи попадать не должны.
    Категория и имена «Статуса» (Доставка/В зале/С собой) тоже сюда попадают — в разрезах
    они либо уже отсекаются по категории, либо предварительно дают канал заказа.
    """
    rows = await dish_detail_rows(date_from_iso, date_to_iso)
    names: set[str] = set()
    cat_has_mod: set[str] = set()
    cat_has_dish: set[str] = set()
    for r in rows:
        cat = r.get("category")
        if r.get("product_type") == PRODUCT_TYPE_MODIFIER:
            names.add(normalize_name(r["dish_name"]))
            if cat:
                cat_has_mod.add(cat)
        elif cat:
            cat_has_dish.add(cat)
    # Категорию целиком отсекаем, ТОЛЬКО если в ней нет ни одного блюда (чистая
    # модификаторная категория — «модификаторы»/«Статус»). СМЕШАННЫЕ категории
    # (Напитки/Доставка: блюда + модификаторы-добавки вроде бесплатного «Айран_»)
    # не трогаем — иначе из OLAP-разрезов пропадала вся категория (напр. «Напитки»
    # исчезала из состава чека). Отдельные модификаторы-строки внутри смешанной
    # категории по имени не вычистить: платные «Кола»/«Айран» в OLAP слиты с
    # одноимёнными блюдами, отсев по имени убил бы реальные продажи.
    cats = cat_has_mod - cat_has_dish
    return names, cats
