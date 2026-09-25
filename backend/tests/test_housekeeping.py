"""Уборка: кэш не растёт вечно, журнал синков не переживает месяцы.

Обе утечки медленные и потому незаметные:

- **Кэш живых чтений.** Ключ содержит даты периода, то есть каждый новый период создаёт
  новый ключ. `cache_get` удаляет протухшее только у того ключа, к которому обратились, —
  остальные оставались в словаре навсегда вместе со значениями (ответы OLAP за месяц).
- **Журнал синков.** Каждый синк пишет строку, а `sync_today` идёт раз в три минуты: к
  25.09.2026 в `sync_log` было 86 196 записей — больше, чем самих позиций заказов (39 045).
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cache  # noqa: E402
import models  # noqa: E402
import scheduler  # noqa: E402
from config import settings  # noqa: E402

# --- кэш --------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_cache(monkeypatch):
    cache.cache_clear()
    monkeypatch.setattr(settings, "cache_ttl_seconds", 60)
    yield
    cache.cache_clear()


def test_протухшие_ключи_выметаются_при_разрастании(monkeypatch):
    """Порог разрастания — `_SWEEP_AT`; до него не метём, чтобы не ходить по словарю зря."""
    monkeypatch.setattr(cache, "_SWEEP_AT", 5)
    monkeypatch.setattr(settings, "cache_ttl_seconds", -1)  # TTL<=0 — no-op, кэш пуст
    for i in range(10):
        cache.cache_set(f"k{i}", i)
    assert cache.cache_size() == 0

    monkeypatch.setattr(settings, "cache_ttl_seconds", 60)
    for i in range(4):
        cache.cache_set(f"живой{i}", i, ttl=60)
    # эти протухнут сразу: отрицательный TTL кладёт запись с истёкшим сроком
    for i in range(4):
        cache._store[f"мёртвый{i}"] = (0.0, i)
    assert cache.cache_size() == 8

    cache.cache_set("ещё", 1, ttl=60)  # порог превышен → sweep
    keys = set(cache._store)
    assert not any(k.startswith("мёртвый") for k in keys)
    assert all(f"живой{i}" in keys for i in range(4))


def test_живые_ключи_остаются_на_месте(monkeypatch):
    monkeypatch.setattr(cache, "_SWEEP_AT", 2)
    cache.cache_set("a", 1, ttl=60)
    cache.cache_set("b", 2, ttl=60)
    cache.cache_set("c", 3, ttl=60)
    assert cache.cache_get("a") == 1
    assert cache.cache_get("c") == 3


def test_ttl_ноль_ничего_не_кладёт(monkeypatch):
    monkeypatch.setattr(settings, "cache_ttl_seconds", 0)
    cache.cache_set("x", 1)
    assert cache.cache_get("x") is None


# --- журнал синков ----------------------------------------------------------


@pytest.fixture
def db(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'log.db'}", connect_args={"check_same_thread": False}
    )
    event.listen(engine, "connect", models._sqlite_pragmas)
    models.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with Session() as session:
        for days_ago in (0, 1, 29, 31, 90):
            session.add(
                models.SyncLog(
                    sync_type="orders",
                    status="ok",
                    created_at=now - timedelta(days=days_ago),
                )
            )
        session.commit()
    monkeypatch.setattr(scheduler, "SessionLocal", Session)
    return Session


def _count(Session) -> int:
    with Session() as session:
        return session.execute(select(func.count()).select_from(models.SyncLog)).scalar()


def test_старые_записи_журнала_удаляются(db, monkeypatch):
    monkeypatch.setattr(settings, "sync_log_keep_days", 30)
    assert _count(db) == 5
    assert scheduler.prune_sync_log() == 2  # записи 31 и 90 дней
    assert _count(db) == 3


def test_свежие_записи_остаются(db, monkeypatch):
    monkeypatch.setattr(settings, "sync_log_keep_days", 30)
    scheduler.prune_sync_log()
    with db() as session:
        ages = [
            (datetime.now(timezone.utc).replace(tzinfo=None) - r.created_at).days
            for r in session.execute(select(models.SyncLog)).scalars()
        ]
    assert sorted(ages) == [0, 1, 29]


def test_ноль_дней_выключает_чистку(db, monkeypatch):
    """Настройка 0 — журнал не трогаем вовсе (нужно, если понадобится долгий разбор)."""
    monkeypatch.setattr(settings, "sync_log_keep_days", 0)
    assert scheduler.prune_sync_log() == 0
    assert _count(db) == 5
