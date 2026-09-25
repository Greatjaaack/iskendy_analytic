"""Защита ручек: перебор пароля, сверка токенов, загрузка файлов, валидация тел.

Что проверяем и почему именно это:

- **Перебор пароля.** Дашборд открыт в интернет, пароль один общий, и до 25.09.2026
  попытки входа ничем не ограничивались.
- **Логин с кириллицей.** `hmac.compare_digest` на строках требует ASCII и бросал
  `TypeError` — вход отвечал 500 вместо 401, подсказывая перебирающему, что ввод необычный.
- **Internal-токен.** Сравнивался обычным `!=`, то есть по времени ответа подбирался
  посимвольно.
- **Загрузка файлов.** Файл читался целиком в память при лимите контейнера 512 МБ:
  один запрос мог увести бэкенд в OOM вместе с ручкой табло.
- **Тела write-ручек.** Шесть ручек принимали `payload: dict`, и запрос без обязательного
  поля падал 500 в глубине кода вместо 422 на границе.

Тела запросов в тестах — ровно те, что отправляет фронт (`frontend/src/api.ts`).
"""

import sys
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main  # noqa: E402
import models  # noqa: E402
import ratelimit  # noqa: E402
import storage  # noqa: E402
from config import settings  # noqa: E402
from routers import plan as plan_router  # noqa: E402
from routers import pnl as pnl_router  # noqa: E402
from routers import schedule as sched_router  # noqa: E402
from routers import suppliers as sup_router  # noqa: E402

PASSWORD = "secret-pass"
INTERNAL = "internal-token"


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Временная БД с одним поставщиком; файлы — в tmp."""
    engine = create_engine(
        f"sqlite:///{tmp_path / 'sec.db'}", connect_args={"check_same_thread": False}
    )
    event.listen(engine, "connect", models._sqlite_pragmas)
    models.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as session:
        session.add(models.Supplier(name="Тестовый поставщик"))
        session.commit()
    for module in (main, sup_router, pnl_router, plan_router, sched_router):
        monkeypatch.setattr(module, "SessionLocal", Session, raising=False)
    files = tmp_path / "files"
    files.mkdir()
    monkeypatch.setattr(storage, "FILES_DIR", str(files))
    return Session


@pytest.fixture
def client(monkeypatch, db):
    monkeypatch.setattr(settings, "auth_password", PASSWORD)
    monkeypatch.setattr(settings, "auth_username", "admin")
    monkeypatch.setattr(settings, "internal_token", INTERNAL)
    ratelimit.reset()
    c = TestClient(main.app)
    token = c.post("/api/auth/login", json={"username": "admin", "password": PASSWORD}).json()[
        "token"
    ]
    c.headers.update({"Authorization": f"Bearer {token}"})
    return c


# --- перебор пароля ----------------------------------------------------------


def test_перебор_пароля_упирается_в_лимит(client):
    """После `LOGIN_LIMIT` попыток с адреса вход отвечает 429, а не продолжает сверять."""
    ratelimit.reset()
    codes = [
        client.post("/api/auth/login", json={"username": "admin", "password": "нет"}).status_code
        for _ in range(ratelimit.LOGIN_LIMIT + 3)
    ]
    assert codes[0] == 401  # первые попытки просто неверные
    assert codes[-1] == 429  # дальше лимит
    assert codes.count(429) == 3


def test_после_остывания_лимита_вход_снова_возможен(client):
    ratelimit.reset()
    for _ in range(ratelimit.LOGIN_LIMIT):
        client.post("/api/auth/login", json={"username": "admin", "password": "нет"})
    assert (
        client.post("/api/auth/login", json={"username": "admin", "password": PASSWORD}).status_code
        == 429
    )
    ratelimit.reset()  # имитация остывшего окна
    assert (
        client.post("/api/auth/login", json={"username": "admin", "password": PASSWORD}).status_code
        == 200
    )


def test_логин_с_кириллицей_это_401_а_не_500(client):
    ratelimit.reset()
    r = client.post("/api/auth/login", json={"username": "админ", "password": "пароль"})
    assert r.status_code == 401


def test_слишком_длинный_логин_отсекается_на_границе(client):
    ratelimit.reset()
    r = client.post("/api/auth/login", json={"username": "a" * 500, "password": "b"})
    assert r.status_code == 422


# --- internal-токен ----------------------------------------------------------


def test_внутренняя_ручка_проверяет_токен(client):
    assert client.get("/api/summary", headers={"X-Internal-Token": "wrong"}).status_code == 401
    assert client.get("/api/summary", headers={"X-Internal-Token": INTERNAL}).status_code == 200


def test_почти_верный_токен_не_проходит(client):
    """Отличие в последнем символе — отказ.

    Константность времени сверки этот тест НЕ проверяет (замеры времени в тестах
    ненадёжны): он ловит только корректность. Сама константность обеспечивается
    `hmac.compare_digest` в `main._require_internal`.
    """
    r = client.get("/api/summary", headers={"X-Internal-Token": INTERNAL[:-1] + "x"})
    assert r.status_code == 401


# --- загрузка файлов ---------------------------------------------------------


def test_большой_файл_не_принимаем(client, monkeypatch):
    monkeypatch.setattr(settings, "max_upload_mb", 1)
    big = b"x" * (2 * 1024 * 1024)
    r = client.post(
        "/api/suppliers/1/files",
        files={"file": ("накладная.pdf", big, "application/pdf")},
    )
    assert r.status_code == 413
    assert list(Path(storage.FILES_DIR).iterdir()) == []  # недописанный файл убран


def test_чужое_расширение_не_принимаем(client):
    r = client.post(
        "/api/suppliers/1/files",
        files={"file": ("скрипт.sh", b"#!/bin/sh\necho", "text/x-sh")},
    )
    assert r.status_code == 415
    assert list(Path(storage.FILES_DIR).iterdir()) == []


def test_нормальный_файл_принимаем(client):
    r = client.post(
        "/api/suppliers/1/files",
        files={"file": ("прайс.xlsx", b"PK\x03\x04payload", "application/vnd.ms-excel")},
    )
    assert r.status_code == 200
    assert r.json()["filename"] == "прайс.xlsx"
    assert len(list(Path(storage.FILES_DIR).iterdir())) == 1


# --- тела write-ручек: то, что шлёт фронт, и то, что шлёт кривой клиент ------


def test_план_сохраняется_телом_фронта(client):
    body = {"cells": {"lunch|weekend": {"revenue": 120000, "avg_check": 600, "guests": 200}}}
    assert client.put("/api/plan", json=body).status_code == 200
    saved = client.get("/api/plan").json()
    assert saved["cells"]["lunch|weekend"]["revenue"] == 120000


def test_план_с_отрицательной_выручкой_отклоняется(client):
    body = {"cells": {"lunch|weekend": {"revenue": -5, "avg_check": 0, "guests": 0}}}
    assert client.put("/api/plan", json=body).status_code == 422


def test_затраты_месяца_сохраняются_плоским_телом(client):
    """Фронт шлёт `Record<string, number>`: год, месяц и ₽-поля вперемешку."""
    body = {"year": 2026, "month": 9, "rent": 250000, "utilities": 40000, "tax_pct": 6}
    assert client.put("/api/pnl/costs", json=body).status_code == 200
    saved = client.get("/api/pnl/costs?year=2026&month=9").json()
    assert saved["values"]["rent"] == 250000
    assert saved["values"]["tax_pct"] == 6


def test_затраты_без_года_это_422_а_не_500(client):
    assert client.put("/api/pnl/costs", json={"month": 9, "rent": 1}).status_code == 422


def test_месяц_вне_диапазона_отклоняется(client):
    assert client.put("/api/pnl/costs", json={"year": 2026, "month": 13}).status_code == 422


def test_дневные_затраты_сохраняются_телом_фронта(client):
    body = {"days": [{"date": "2026-09-10", "writeoffs": 500, "packaging": 300}]}
    assert client.put("/api/pnl/day-costs", json=body).status_code == 200


def test_дневные_затраты_с_битой_датой_это_422(client):
    body = {"days": [{"date": "вчера", "writeoffs": 500}]}
    assert client.put("/api/pnl/day-costs", json=body).status_code == 422


def test_сотрудник_создаётся_и_правится(client):
    created = client.post(
        "/api/schedule/employees",
        json={
            "name": "Иван",
            "role": "повар",
            "labor_group": "operational",
            "pay_type": "shift",
            "rate": 3000,
            "active": True,
        },
    )
    assert created.status_code == 200
    emp_id = created.json()["id"]
    # фронт шлёт Partial<Employee> — вместе с id, лишнее поле не должно ломать запрос
    patched = client.put(f"/api/schedule/employees/{emp_id}", json={"id": emp_id, "rate": 3500})
    assert patched.status_code == 200
    assert patched.json()["rate"] == 3500
    assert patched.json()["name"] == "Иван"  # неприсланное не затёрлось


def test_неизвестный_тип_оплаты_отклоняется(client):
    r = client.post("/api/schedule/employees", json={"name": "Пётр", "pay_type": "почасовая"})
    assert r.status_code == 422


def test_смена_переключается_телом_фронта(client):
    created = client.post("/api/schedule/employees", json={"name": "Анна"})
    emp_id = created.json()["id"]
    body = {"employee_id": emp_id, "date": date(2026, 9, 10).isoformat()}
    assert client.post("/api/schedule/shifts/toggle", json=body).json() == {"on": True}
    assert client.post("/api/schedule/shifts/toggle", json=body).json() == {"on": False}


def test_смена_без_сотрудника_это_422_а_не_500(client):
    assert (
        client.post("/api/schedule/shifts/toggle", json={"date": "2026-09-10"}).status_code == 422
    )


def test_схемы_совпадают_со_справочниками(client):
    """Literal в схеме и константы роутера — один источник правды, иначе тихо разъедутся."""
    import typing

    assert set(typing.get_args(sched_router.EmployeeIn.model_fields["pay_type"].annotation)) == set(
        sched_router.PAY_TYPES
    )
    assert set(
        typing.get_args(sched_router.EmployeeIn.model_fields["labor_group"].annotation)
    ) == set(sched_router.LABOR_GROUPS)


# --- CORS -------------------------------------------------------------------


def test_cors_только_для_своих_origin(client):
    """Раньше стоял `allow_origins=["*"]` — ручки были открыты любому сайту в браузере."""
    свой = client.options(
        "/api/health",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
    )
    assert свой.headers.get("access-control-allow-origin") == "http://localhost:5173"

    чужой = client.options(
        "/api/health",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert "access-control-allow-origin" not in чужой.headers
