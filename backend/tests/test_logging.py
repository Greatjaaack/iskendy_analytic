"""Журнал: шум не пишется, а то, что нужно для разбора, доживает до разбора.

Замер на проде 26.09.2026 — 2 196 строк в час, ~90 % шум (см. `log_setup.py`). Здесь
зафиксировано, что отсев шума не глотает ошибки, а синк не пишет «ok», когда данные
не обновились.
"""

import asyncio
import logging
import sys
from datetime import date
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import iiko_web_client  # noqa: E402
import scheduler  # noqa: E402
import weather  # noqa: E402
from config import settings  # noqa: E402
from log_setup import QuietPathsFilter, setup_logging  # noqa: E402
from tests.test_sync_guards import DAY, FakePos, _order, fake_session  # noqa: E402


def run(coro):
    return asyncio.run(coro)


def access_record(path: str, status: int) -> logging.LogRecord:
    """Запись в том виде, в каком её пишет uvicorn.access."""
    return logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        0,
        '%s - "%s %s HTTP/%s" %d',
        ("10.0.0.1:5000", "GET", path, "1.1", status),
        None,
    )


# ─── Access-лог ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize("path", ["/api/orders/today", "/api/health", "/api/health?x=1"])
def test_успешный_опрос_автоматами_не_пишется(path):
    assert QuietPathsFilter().filter(access_record(path, 200)) is False


@pytest.mark.parametrize("status", [401, 500, 503])
def test_ошибка_на_тихом_пути_пишется(status):
    """Табло получило 500 — это надо видеть, даже если 200 мы не пишем."""
    assert QuietPathsFilter().filter(access_record("/api/orders/today", status)) is True


def test_прочие_пути_пишутся():
    assert QuietPathsFilter().filter(access_record("/api/revenue", 200)) is True
    assert QuietPathsFilter().filter(access_record("/api/orders/today2", 200)) is True


def test_чужая_запись_проходит_без_изменений():
    rec = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 0, "просто текст", (), None)
    assert QuietPathsFilter().filter(rec) is True


def test_настройка_глушит_болтливые_логгеры_и_не_дублирует_фильтр():
    setup_logging()
    setup_logging()
    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("apscheduler.executors").level == logging.WARNING
    access = logging.getLogger("uvicorn.access")
    assert sum(isinstance(f, QuietPathsFilter) for f in access.filters) == 1


# ─── Журнал синков ────────────────────────────────────────────────────────────


def _statuses(journal: dict) -> list[tuple[str, str]]:
    return [(r.sync_type, r.status) for r in journal.get("added", [])]


def test_синк_при_сработавшем_предохранителе_не_пишет_ok(monkeypatch):
    """Касса отдала пусто поверх непустых дней — данные не обновлены, значит не «ok».

    Иначе `/api/sync/last` показывал бы «синхронизировано только что» над старыми цифрами.
    """
    journal: dict = {}
    monkeypatch.setattr(settings, "pos_switch_date", None)
    monkeypatch.setattr(scheduler, "get_pos", lambda: FakePos(journal=journal))
    monkeypatch.setattr(scheduler, "SessionLocal", fake_session(journal, have=120))
    run(scheduler.sync_orders_recent(days_back=2))
    assert _statuses(journal) == [("orders", "skipped")]
    assert "не тронуты" in journal["added"][0].message


def test_удачный_синк_пишет_ok(monkeypatch):
    journal: dict = {}
    monkeypatch.setattr(settings, "pos_switch_date", None)
    monkeypatch.setattr(scheduler, "get_pos", lambda: FakePos([_order()], journal))
    monkeypatch.setattr(scheduler, "SessionLocal", fake_session(journal, have=0))
    run(scheduler.sync_orders_recent(days_back=1))
    assert _statuses(journal) == [("orders", "ok")]


def test_синк_заказов_возвращает_число_заказов(monkeypatch):
    journal: dict = {}
    monkeypatch.setattr(settings, "pos_switch_date", None)
    monkeypatch.setattr(scheduler, "get_pos", lambda: FakePos([_order()], journal))
    monkeypatch.setattr(scheduler, "SessionLocal", fake_session(journal, have=0))
    assert run(scheduler.sync_orders_range(DAY, DAY)) == 1


def test_падение_бэкафилла_остаётся_в_журнале_синков(monkeypatch):
    """Бэкафилл идёт ночью; docker-лог ротируется за дни, журнал синков — нет."""
    journal: dict = {}
    base = fake_session(journal, have=0)

    class Session(base):  # type: ignore[misc, valid-type]
        def execute(self, *a, **kw):
            class Empty:
                def scalar(self):
                    return None

                def all(self):
                    return []

            return Empty()

    async def start():
        return DAY

    async def boom(date_from, date_to):
        raise RuntimeError("касса легла")

    monkeypatch.setattr(scheduler, "SessionLocal", Session)
    monkeypatch.setattr(scheduler, "_history_start", start)
    monkeypatch.setattr(scheduler, "sync_orders_range", boom)
    run(scheduler.backfill())
    assert _statuses(journal) == [("backfill", "error")]
    assert "касса легла" in journal["added"][0].message


# ─── Сессия iiko: проверка не перед каждым запросом ──────────────────────────


def test_сессия_iiko_проверяется_не_чаще_раза_в_минуту(monkeypatch):
    client = iiko_web_client.IikoWebClient()
    client._cookies = {"sid": "x"}
    checks = []

    async def check():
        checks.append(1)
        return True

    monkeypatch.setattr(client, "_check_auth", check)
    run(client._ensure_session())
    run(client._ensure_session())
    run(client._ensure_session())
    assert len(checks) == 1

    client._checked_at -= iiko_web_client._SESSION_TRUST_SECONDS + 1  # минута прошла
    run(client._ensure_session())
    assert len(checks) == 2


def test_после_отказа_401_сессия_проверяется_заново(monkeypatch):
    """Протухшая сессия: 401 сбрасывает доверие, и следующий вызов перелогинивается."""
    client = iiko_web_client.IikoWebClient()
    client._cookies = {"sid": "x"}
    client._checked_at = 10**9  # «только что проверена»
    logins = []

    async def login():
        logins.append(1)
        client._cookies = {"sid": "new"}

    responses = iter([401, 200])

    class FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json):
            return httpx.Response(next(responses), json={}, request=httpx.Request("POST", url))

    async def auth_fails():
        return False

    monkeypatch.setattr(client, "_login", login)
    monkeypatch.setattr(client, "_check_auth", auth_fails)
    monkeypatch.setattr(iiko_web_client.httpx, "AsyncClient", FakeClient)
    assert run(client._post("/api/x", {})) == {}
    assert logins == [1]


# ─── Погода: ожидаемый сетевой сбой — одна строка, без трейса ───────────────


def test_таймаут_погоды_пишется_одной_строкой(monkeypatch, caplog):
    async def timeout(url, date_from, date_to):
        raise httpx.ConnectTimeout("нет сети")

    monkeypatch.setattr(weather, "_fetch_range", timeout)
    monkeypatch.setattr(weather, "_cache", {})
    monkeypatch.setattr(weather, "_attempted", {})
    day = date.today().isoformat()
    with caplog.at_level("WARNING", logger="weather"):
        assert run(weather.get_weather(day, day)) == {}
    (rec,) = [r for r in caplog.records if r.name == "weather"]
    assert "ConnectTimeout" in rec.getMessage()
    assert rec.exc_info is None
