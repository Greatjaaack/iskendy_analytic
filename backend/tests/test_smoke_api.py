"""Смоук по всем ручкам: каждая отвечает, числа между ручками сходятся, в кассу не ходим.

Зачем именно так, а не «просто 200». Ошибку этапа 1 (заказы склеивались по номеру, и
дашборд показывал 237 чеков вместо 3 310) не поймал бы тест на код ответа: ручки отвечали
200 и выглядели правдоподобно. Ловит её сверка — число чеков в разрезе против числа чеков
в выручке. Поэтому здесь два слоя:

1. **Каждая ручка отвечает** — и список ручек сверяется с OpenAPI, так что новая ручка без
   теста валит `test_все_ручки_покрыты`.
2. **Инварианты** — суммы и счётчики, которые ОБЯЗАНЫ совпадать между разными ручками.

Касса подменена заглушкой, падающей при обращении (`conftest.КассаНедоступна`): любой
запрос в кассу за период внутри истории — регрессия этапа 3.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main  # noqa: E402
from tests.conftest import (  # noqa: E402
    INTERNAL_TOKEN,
    ВЫРУЧКА_ВСЕГО,
    ВЫРУЧКА_ЗА_ДЕНЬ,
    ПЕРИОД,
    ПЕРИОД_ДНИ,
    ЧЕКОВ_ВСЕГО,
    ЧЕКОВ_ЗА_ДЕНЬ,
)

# GET-ручки дашборда: путь → чем проверяем, что ответ осмысленный
ЧИТАЮЩИЕ = {
    "/api/health": lambda b: b["status"] == "ok",
    "/api/auth/me": lambda b: b["username"] == "admin",
    "/api/sync/last": lambda b: "last_sync" in b,
    f"/api/revenue?{ПЕРИОД}": lambda b: len(b["data"]) == len(ПЕРИОД_ДНИ),
    f"/api/revenue/hourly?{ПЕРИОД}": lambda b: len(b["data"]) >= 2,
    f"/api/revenue/by-weekday?{ПЕРИОД}": lambda b: len(b["data"]) == len(ПЕРИОД_ДНИ),
    f"/api/revenue/by-daypart?{ПЕРИОД}": lambda b: any(d["revenue"] for d in b["data"]),
    f"/api/revenue/by-payment?{ПЕРИОД}": lambda b: len(b["totals"]) >= 1,
    f"/api/revenue/by-channel?{ПЕРИОД}": lambda b: len(b["data"]) == len(ПЕРИОД_ДНИ),
    f"/api/revenue/hourly-by-channel?{ПЕРИОД}": lambda b: len(b["data"]) >= 2,
    f"/api/revenue/kpi-by-channel?{ПЕРИОД}": lambda b: b["other"]["checks"] == ЧЕКОВ_ВСЕГО,
    f"/api/revenue/ops-report?{ПЕРИОД}": lambda b: len(b["days"]) == len(ПЕРИОД_ДНИ),
    f"/api/dishes?{ПЕРИОД}": lambda b: any(d["name"] == "Балык" for d in b["data"]),
    f"/api/dishes?{ПЕРИОД}&group_by=category": lambda b: any(
        d["name"] == "Дюрюмы" for d in b["data"]
    ),
    f"/api/dishes/check-distribution?{ПЕРИОД}": lambda b: b["total"] == ЧЕКОВ_ВСЕГО,
    f"/api/dishes/check-composition?{ПЕРИОД}": lambda b: b["total"]["checks"] == ЧЕКОВ_ВСЕГО,
    f"/api/dishes/check-fullness?{ПЕРИОД}": lambda b: sum(b["total"].values()) == ЧЕКОВ_ВСЕГО,
    f"/api/dishes/hourly-breakdown?{ПЕРИОД}": lambda b: len(b["data"]) >= 2,
    f"/api/dishes/hourly-breakdown?{ПЕРИОД}&group=dish": lambda b: len(b["data"]) >= 2,
    f"/api/dishes/basket?{ПЕРИОД}&group=dish": lambda b: b["orders"] == ЧЕКОВ_ВСЕГО,
    f"/api/dishes/service-breakdown?{ПЕРИОД}": lambda b: len(b["data"]) >= 2,
    f"/api/pnl?{ПЕРИОД}": lambda b: b["revenue"] > 0 and b["sections"],
    "/api/pnl/costs?year=2026&month=3": lambda b: b["values"]["rent"] == 90000,
    f"/api/pnl/day-costs?{ПЕРИОД}": lambda b: "days" in b or "rows" in b,
    "/api/plan": lambda b: "cells" in b,
    "/api/schedule/employees": lambda b: b[0]["name"] == "Тестовый повар",
    # смены заведены на все дни фикстуры, март — часть из них
    "/api/schedule/shifts?year=2026&month=3": lambda b: len(b) == 8,
    "/api/schedule/labor?year=2026&month=3": lambda b: b["operational"] > 0,
    "/api/suppliers": lambda b: b[0]["name"] == "Тестовый поставщик",
    "/api/suppliers/1": lambda b: b["name"] == "Тестовый поставщик",
    "/api/ingredients": lambda b: any(i["name"] == "Лаваш" for i in b),
    "/api/ingredients/1": lambda b: b["name"] == "Лаваш",
    "/api/ttk": lambda b: any(t["name"] == "Балык" for t in b),
    "/api/ttk/1": lambda b: b["name"] == "Балык",
    "/api/dish-mappings": lambda b: any(m["sale_name"] == "Балык" for m in b),
}

# Ручки, намеренно не входящие в смоук, и причина — иначе список «покрыто» сгниёт молча.
ВНЕ_СМОУКА = {
    # живой путь к кассе, у него свои тесты (test_orders_today.py)
    "GET /api/orders/today",
    # диагностика сырого поля кассы (живой OLAP)
    "GET /api/dishes/order-types",
    # внутренняя ручка под сервисным токеном — проверяется отдельным тестом ниже
    "GET /api/summary",
    # вход и лимит попыток — test_security.py
    "POST /api/auth/login",
    # операции записи и внешние импорты: проверяются точечно, а не смоуком
    "POST /api/sync",
    "POST /api/import/ttk-matrix",
    "POST /api/pnl/import-sheet",
    "POST /api/plan/seed-from-history",
    "PUT /api/plan",
    "PUT /api/pnl/costs",
    "PUT /api/pnl/day-costs",
    "POST /api/schedule/employees",
    "PUT /api/schedule/employees/{emp_id}",
    "DELETE /api/schedule/employees/{emp_id}",
    "POST /api/schedule/shifts/toggle",
    "POST /api/suppliers",
    "PUT /api/suppliers/{supplier_id}",
    "DELETE /api/suppliers/{supplier_id}",
    "POST /api/suppliers/{supplier_id}/contacts",
    "PUT /api/suppliers/{supplier_id}/contacts/{contact_id}",
    "DELETE /api/suppliers/{supplier_id}/contacts/{contact_id}",
    "POST /api/suppliers/{supplier_id}/files",
    "GET /api/suppliers/{supplier_id}/files/{file_id}",
    "PUT /api/suppliers/{supplier_id}/products/{price_id}",
    "GET /api/suppliers/export",
    "PUT /api/ingredients/{ingredient_id}",
    "POST /api/dish-mappings",
    "DELETE /api/dish-mappings/{mapping_id}",
}


def _шаблон(url: str) -> str:
    """URL смоука → путь как он выглядит в OpenAPI (без query, с {параметрами})."""
    path = url.split("?")[0]
    for конкретный, шаблон in (
        ("/api/suppliers/1", "/api/suppliers/{supplier_id}"),
        ("/api/ingredients/1", "/api/ingredients/{ingredient_id}"),
        ("/api/ttk/1", "/api/ttk/{ttk_id}"),
    ):
        if path == конкретный:
            return шаблон
    return path


def test_все_ручки_покрыты():
    """Новая ручка обязана попасть либо в смоук, либо в список исключений с причиной."""
    spec = main.app.openapi()
    все = {
        f"{метод.upper()} {путь}"
        for путь, операции in spec["paths"].items()
        for метод in операции
        if метод.lower() in ("get", "post", "put", "delete")
    }
    покрыто = {f"GET {_шаблон(u)}" for u in ЧИТАЮЩИЕ}
    непокрытые = все - покрыто - ВНЕ_СМОУКА
    assert not непокрытые, (
        "эти ручки никем не проверяются — добавьте в ЧИТАЮЩИЕ или в ВНЕ_СМОУКА с причиной: "
        + ", ".join(sorted(непокрытые))
    )
    # и наоборот: исключение, которого больше нет в API, только мешает читать список
    assert not (ВНЕ_СМОУКА - все), f"исчезли из API: {sorted(ВНЕ_СМОУКА - все)}"


@pytest.mark.parametrize("url", sorted(ЧИТАЮЩИЕ))
def test_ручка_отвечает_осмысленно(клиент, url):
    r = клиент.get(url)
    assert r.status_code == 200, f"{url} → {r.status_code}: {r.text[:200]}"
    проверка = ЧИТАЮЩИЕ[url]
    assert проверка(r.json()), f"{url}: ответ 200, но содержимое не то: {r.text[:300]}"


def test_внутренняя_сводка_для_табло(клиент):
    r = клиент.get(
        f"/api/summary?date={ПЕРИОД_ДНИ[0].isoformat()}",
        headers={"X-Internal-Token": INTERNAL_TOKEN},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["has_data"] is True
    assert body["revenue"] == ВЫРУЧКА_ЗА_ДЕНЬ
    assert body["checks"] == ЧЕКОВ_ЗА_ДЕНЬ


# --- инварианты: числа обязаны сходиться между ручками -----------------------


def test_выручка_сходится_по_дням_и_итогом(клиент):
    body = клиент.get(f"/api/revenue?{ПЕРИОД}").json()
    assert sum(d["total_sum"] for d in body["data"]) == ВЫРУЧКА_ВСЕГО
    assert body["summary"]["gross_revenue"] == ВЫРУЧКА_ВСЕГО
    assert body["summary"]["total_checks"] == ЧЕКОВ_ВСЕГО


def test_часы_и_дейпарты_дают_ту_же_выручку(клиент):
    часы = клиент.get(f"/api/revenue/hourly?{ПЕРИОД}").json()["data"]
    дейпарты = клиент.get(f"/api/revenue/by-daypart?{ПЕРИОД}").json()["data"]
    assert sum(h["revenue"] for h in часы) == ВЫРУЧКА_ВСЕГО
    assert sum(d["revenue"] for d in дейпарты) == ВЫРУЧКА_ВСЕГО
    assert sum(h["checks"] for h in часы) == ЧЕКОВ_ВСЕГО


def test_каналы_дают_ту_же_выручку(клиент):
    по_дням = клиент.get(f"/api/revenue/by-channel?{ПЕРИОД}").json()["data"]
    по_часам = клиент.get(f"/api/revenue/hourly-by-channel?{ПЕРИОД}").json()["data"]
    assert sum(r["total"] for r in по_дням) == ВЫРУЧКА_ВСЕГО
    assert sum(r["total"] for r in по_часам) == ВЫРУЧКА_ВСЕГО
    kpi = клиент.get(f"/api/revenue/kpi-by-channel?{ПЕРИОД}").json()
    assert kpi["other"]["revenue"] + kpi["delivery"]["revenue"] == ВЫРУЧКА_ВСЕГО


def test_оплаты_сходятся_с_выручкой(клиент):
    """Сплит-оплата разложена по способам, и сумма частей равна выручке."""
    body = клиент.get(f"/api/revenue/by-payment?{ПЕРИОД}").json()
    assert sum(t["amount"] for t in body["totals"]) == ВЫРУЧКА_ВСЕГО


def test_чеки_сходятся_во_всех_разрезах(клиент):
    """Главный инвариант: заказ — это (дата, номер), поэтому чеки считаются одинаково."""
    ожидается = ЧЕКОВ_ВСЕГО
    assert клиент.get(f"/api/dishes/check-distribution?{ПЕРИОД}").json()["total"] == ожидается
    assert (
        клиент.get(f"/api/dishes/check-composition?{ПЕРИОД}").json()["total"]["checks"] == ожидается
    )
    fullness = клиент.get(f"/api/dishes/check-fullness?{ПЕРИОД}").json()["total"]
    assert sum(fullness.values()) == ожидается
    assert клиент.get(f"/api/dishes/basket?{ПЕРИОД}&group=dish").json()["orders"] == ожидается
    assert (
        клиент.get(f"/api/revenue/kpi-by-channel?{ПЕРИОД}").json()["other"]["checks"] == ожидается
    )


def test_блюда_дают_ту_же_выручку_без_служебных_строк(клиент):
    """Сумма по блюдам = выручка: «Статус» и модификаторы в неё не попадают."""
    data = клиент.get(f"/api/dishes?{ПЕРИОД}").json()["data"]
    assert sum(d["revenue"] for d in data) == ВЫРУЧКА_ВСЕГО
    assert not any(d["name"] in ("С собой", "В зале", "Разрезать 1/2") for d in data)


def test_pnl_берёт_ту_же_выручку(клиент):
    """P&L строится на той же выручке, что и дашборд, иначе отчёты разойдутся."""
    pnl = клиент.get(f"/api/pnl?{ПЕРИОД}").json()
    assert pnl["revenue"] == ВЫРУЧКА_ВСЕГО
    assert pnl["active_days"] == len(ПЕРИОД_ДНИ)


def test_ops_report_сходится_с_выручкой(клиент):
    body = клиент.get(f"/api/revenue/ops-report?{ПЕРИОД}").json()
    assert body["totals"]["total"]["revenue"] == ВЫРУЧКА_ВСЕГО
    assert body["totals"]["total"]["checks"] == ЧЕКОВ_ВСЕГО


def test_галка_без_доставки_ничего_не_меняет_когда_доставки_нет(клиент):
    """У точки доставки нет, поэтому обе версии обязаны совпасть до рубля."""
    с_доставкой = клиент.get(f"/api/revenue?{ПЕРИОД}").json()["summary"]["gross_revenue"]
    без = клиент.get(f"/api/revenue?{ПЕРИОД}&include_delivery=false").json()["summary"][
        "gross_revenue"
    ]
    assert с_доставкой == без == ВЫРУЧКА_ВСЕГО


def test_себестоимость_приходит_из_ттк(клиент):
    """У «Балыка» есть привязка к ТТК, значит есть и с/с с процентом, а не «—»."""
    балык = next(
        d for d in клиент.get(f"/api/dishes?{ПЕРИОД}").json()["data"] if d["name"] == "Балык"
    )
    assert балык["has_cost"] is True
    assert балык["cost_sum"] > 0
    assert балык["cost_pct"] is not None
