"""Разрезы по чекам: сочетаемость, состав чека, наполненность, каналы.

Все они отвечают на вопросы «что лежит в одном чеке» и потому держатся одного правила:
**заказ опознаётся парой (дата, номер)**. Номер уникален только внутри дня, и по одному
номеру за 01–20.09.2026 из 3 310 чеков получалось 237 «чеков» по 39,7 позиции вместо 2,5 —
сочетаемость показывала пары, которых в одном чеке не было, а наполненность загоняла 79 %
чеков в корзину «4+». Ключ собирают хелперы `services/olap_parse.py`.

Служебные строки («Статус») и модификаторы в состав чека не входят: «Разрезать 1/2» — не
блюдо. Категория отсекается только если она целиком модификаторная (см. `dish_catalog`).

Вынесено из `routers/dishes.py` (этап 7а аудита).
"""

from collections import Counter, defaultdict
from itertools import combinations

from constants import (
    CHANNEL_DELIVERY,
    CHANNEL_DINEIN,
    CHANNEL_TAKEAWAY,
    NON_PRODUCT_CATEGORIES,
    OLAP_FIELD_HOUR,
    ORDER_STATUS_CATEGORY,
)
from services.channels import status_channel
from services.olap_parse import split_order_row
from utils import display_category, is_delivery


def build_check_fullness(rows: list[dict], mod_cats: set[str], include_delivery: bool) -> dict:
    """Распределение чеков по числу позиций (1 / 2 / 3 / 4+), по часам.

    «Позиция» — проданная единица товара (сумма `qty` по товарным строкам заказа), а не
    число разных блюд: заказ из двух одинаковых айранов — это чек на 2 позиции, иначе
    занижался бы сигнал апсейла. Дробный вес округляется, минимум 1.
    """
    # ключ — (час, заказ), где заказ = (дата, номер): по одному номеру заказы разных
    # дней склеивались в один «чек» на 40 позиций, и почти всё падало в корзину «4+».
    positions: dict[tuple[str, str], float] = defaultdict(float)
    for r in rows:
        ordernum, hour, category, name = split_order_row(
            r.get("field0", {}).get("value", ""), OLAP_FIELD_HOUR
        )
        # галка «без доставки»: доставка = категория «Доставка» ИЛИ имя с маркером `_д`
        if not include_delivery and is_delivery(category, name):
            continue
        if not name or category in NON_PRODUCT_CATEGORIES or category in mod_cats:
            continue
        positions[(hour, ordernum)] += float(r.get("field1", {}).get("value", 0) or 0)

    buckets = ["1", "2", "3", "4+"]

    def bucket(n: int) -> str:
        return "4+" if n >= 4 else str(n)

    per_hour: dict[str, dict] = defaultdict(lambda: {b: 0 for b in buckets})
    total = {b: 0 for b in buckets}
    for (hour, _ordernum), qty_sum in positions.items():
        if qty_sum <= 0:
            continue
        b = bucket(max(1, round(qty_sum)))
        per_hour[hour][b] += 1
        total[b] += 1

    data = []
    for hk in sorted((h for h in per_hour if h.isdigit()), key=int):
        h = int(hk)
        row = {"hour": h, "label": f"{h:02d}-{h + 1:02d}", **per_hour[hk]}
        row["total"] = sum(per_hour[hk].values())
        data.append(row)
    return {"buckets": buckets, "total": total, "data": data}


def build_check_distribution(rows: list[dict], include_delivery: bool) -> dict:
    """Чеки по типу обслуживания: доставка / в зале / с собой (уникальные заказы)."""

    order_channel: dict[str, str] = {}  # канал из «Статус»-строки заказа
    order_has_delivery: set[str] = set()  # в заказе есть позиция меню-категории «Доставка»
    orders: set[str] = set()  # все товарные заказы (по которым считаем чеки)
    for r in rows:
        order_num, _day, category, name = split_order_row(r.get("field0", {}).get("value", ""))
        if not order_num:
            continue
        if category == ORDER_STATUS_CATEGORY:
            # у заказа может быть несколько «Статусов» — берём сильнейший, а не последний
            ch = status_channel(order_channel.get(order_num), name, include_delivery)
            if ch:
                order_channel[order_num] = ch
            continue
        if not name:
            continue
        orders.add(order_num)
        if is_delivery(category, name):
            order_has_delivery.add(order_num)

    counts = {CHANNEL_DINEIN: 0, CHANNEL_TAKEAWAY: 0, CHANNEL_DELIVERY: 0}
    for o in orders:
        if not include_delivery and o in order_has_delivery:
            continue  # галка «без доставки»: заказ с доставочной позицией — как в KPI
        ch = order_channel.get(o) or (
            CHANNEL_DELIVERY if o in order_has_delivery else CHANNEL_DINEIN
        )
        counts[ch] += 1

    total = sum(counts.values())
    labels = {
        CHANNEL_DINEIN: "В зале",
        CHANNEL_TAKEAWAY: "С собой",
        CHANNEL_DELIVERY: "Доставка",
    }
    data = sorted(
        (
            {
                "type": labels[ch],
                "count": cnt,
                "share": round(cnt / total * 100, 1) if total else 0,
            }
            for ch, cnt in counts.items()
        ),
        key=lambda x: x["count"],
        reverse=True,
    )
    return {
        "total": int(total),
        "data": data,
    }


def build_check_composition(rows: list[dict], mod_cats: set[str], include_delivery: bool) -> dict:
    """Состав чека: средняя доля категорий в чеке по количеству и выручке, всего и по часам."""
    # заказ → {категория: [qty, sum]}, заказ → час. Ключ заказа — (дата, номер):
    # по одному номеру заказы разных дней склеились бы в один чек на 40 позиций.
    orders: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))
    order_hour: dict[str, str] = {}
    for r in rows:
        ordernum, hour, category, name = split_order_row(
            r.get("field0", {}).get("value", ""), OLAP_FIELD_HOUR
        )
        # галка «без доставки»: доставка = категория «Доставка» ИЛИ имя с маркером `_д`
        if not include_delivery and is_delivery(category, name):
            continue
        # Позиции без категории НЕ отбрасываем: это напитки комбо (Айран_, Кола_…) —
        # до 26.09.2026 они выпадали, и доля напитков в чеке была занижена в разы, а
        # чеки из одного такого напитка пропадали (3 524 товарных чека против 3 727).
        if not ordernum or not name or category in NON_PRODUCT_CATEGORIES or category in mod_cats:
            continue
        category = display_category(category)  # отображаемое имя категории для вывода
        orders[ordernum][category][0] += float(r.get("field1", {}).get("value", 0) or 0)
        orders[ordernum][category][1] += float(r.get("field2", {}).get("value", 0) or 0)
        order_hour[ordernum] = hour

    def new_acc():
        return {"checks": 0, "cats": defaultdict(lambda: [0.0, 0.0])}

    total = new_acc()
    hourly: dict[str, dict] = defaultdict(new_acc)
    for ordernum, cats in orders.items():
        tq = sum(c[0] for c in cats.values())
        ts = sum(c[1] for c in cats.values())
        if tq <= 0:
            continue
        for bk in (total, hourly[order_hour.get(ordernum, "")]):
            bk["checks"] += 1
            for cat, (q, s) in cats.items():
                bk["cats"][cat][0] += q / tq
                bk["cats"][cat][1] += (s / ts) if ts else 0

    def fin(bk) -> dict:
        n = bk["checks"] or 1
        return {
            cat: {"qty": round(v[0] / n * 100, 1), "rev": round(v[1] / n * 100, 1)}
            for cat, v in bk["cats"].items()
        }

    cats_sorted = sorted(total["cats"], key=lambda c: total["cats"][c][0], reverse=True)
    hourly_out = []
    for hk in sorted((h for h in hourly if h.isdigit()), key=int):
        h = int(hk)
        hourly_out.append(
            {
                "hour": h,
                "label": f"{h:02d}-{h + 1:02d}",
                "checks": hourly[hk]["checks"],
                "by": fin(hourly[hk]),
            }
        )
    return {
        "categories": cats_sorted,
        "total": {"checks": total["checks"], "by": fin(total)},
        "hourly": hourly_out,
    }


def build_service_breakdown(rows: list[dict], group: str, mod_cats: set[str], limit: int) -> dict:
    """Блюдо/категория × канал обслуживания.

    У каждого заказа берём его «Статус» и относим к этому каналу все блюда заказа;
    позиция из меню-категории «Доставка» или с маркером `_д` форсит доставку.
    """

    # 1-й проход: канал каждого заказа из его строки категории «Статус»
    order_channel: dict[str, str] = {}
    for r in rows:
        order_num, _day, category, name = split_order_row(r.get("field0", {}).get("value", ""))
        if category == ORDER_STATUS_CATEGORY:
            ch = status_channel(order_channel.get(order_num), name, include_delivery=True)
            if ch:
                order_channel[order_num] = ch

    # 2-й проход: канал блюда — по категории «Доставка»/маркеру `_д` (бизнес-правило),
    # иначе «Статус» заказа (по умолчанию зал).
    channels = (CHANNEL_DINEIN, CHANNEL_TAKEAWAY, CHANNEL_DELIVERY)
    agg: dict[str, dict] = {}
    for r in rows:
        order_num, _day, category, name = split_order_row(r.get("field0", {}).get("value", ""))
        # пропускаем «Статус» (он дал канал в 1-м проходе) и платные модификаторы — не блюда
        if not name or category == ORDER_STATUS_CATEGORY or category in mod_cats:
            continue
        qty = float(r.get("field1", {}).get("value", 0) or 0)
        rev = float(r.get("field2", {}).get("value", 0) or 0)
        if is_delivery(category, name):
            channel = CHANNEL_DELIVERY
        else:
            channel = order_channel.get(order_num, CHANNEL_DINEIN)
        key = display_category(category) if group == "category" else name
        a = agg.setdefault(
            key,
            {"name": key, "total": 0.0, "revenue": 0.0, **{c: 0.0 for c in channels}},
        )
        a["total"] += qty
        a["revenue"] += rev
        a[channel] += qty

    result = sorted(agg.values(), key=lambda x: x["total"], reverse=True)
    for a in result:
        a["total"] = round(a["total"], 1)
        a["revenue"] = round(a["revenue"], 2)
        for c in channels:
            a[c] = round(a[c], 1)
    return {
        "group_by": group,
        "channels": list(channels),
        "data": result[:limit],
    }


def build_basket(
    rows: list[dict], group: str, top: int, mod_cats: set[str], include_delivery: bool
) -> dict:
    """Матрица сочетаемости: что чаще берут вместе в одном чеке.

    Возвращает `labels`/`freq` (топ позиций по числу чеков), `matrix` (со-встречаемость
    пар; диагональ = число чеков с позицией), `pairs` (топ-пары с `support`/`confidence`)
    и `orders` — сколько чеков легло в основу.
    """
    # Заказ — пара (дата, номер). По одному номеру в «чек» попадали позиции из всех
    # дней периода, и матрица показывала пары, которых в одном чеке никогда не было.
    order_labels: dict[str, set[str]] = defaultdict(set)
    for r in rows:
        ordernum, _day, category, name = split_order_row(r.get("field0", {}).get("value", ""))
        if not ordernum:
            continue
        if not include_delivery and is_delivery(category, name):
            continue
        if not name or category in NON_PRODUCT_CATEGORIES or category in mod_cats:
            continue
        order_labels[ordernum].add(display_category(category) if group == "category" else name)

    total_orders = len(order_labels)
    freq: Counter[str] = Counter()
    pair_counts: Counter[tuple[str, str]] = Counter()
    for labels in order_labels.values():
        for lbl in labels:
            freq[lbl] += 1
        for a, b in combinations(sorted(labels), 2):
            pair_counts[(a, b)] += 1

    top_labels = [lbl for lbl, _ in freq.most_common(max(1, top))]
    idx = {lbl: i for i, lbl in enumerate(top_labels)}
    n = len(top_labels)
    matrix = [[0] * n for _ in range(n)]
    for i, lbl in enumerate(top_labels):
        matrix[i][i] = freq[lbl]
    for (a, b), c in pair_counts.items():
        if a in idx and b in idx:
            matrix[idx[a]][idx[b]] = c
            matrix[idx[b]][idx[a]] = c

    pairs = []
    for (a, b), c in pair_counts.most_common(15):
        strong, weak = (a, b) if freq[a] >= freq[b] else (b, a)
        pairs.append(
            {
                "a": strong,
                "b": weak,
                "count": c,
                "support": round(c / total_orders * 100, 1) if total_orders else 0,
                "confidence": round(c / freq[strong] * 100, 1) if freq[strong] else 0,
            }
        )

    return {
        "group_by": group,
        "orders": total_orders,
        "labels": top_labels,
        "freq": [freq[lbl] for lbl in top_labels],
        "matrix": matrix,
        "pairs": pairs,
    }
