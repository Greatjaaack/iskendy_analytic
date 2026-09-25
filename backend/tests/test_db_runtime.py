"""Режим SQLite: WAL и ожидание блокировки вместо ошибки.

Настройки применяются обработчиком `connect` в `models.py`, то есть на каждое новое
соединение. Тест держит их зафиксированными: `journal_mode` живёт в самом файле БД, и
если обработчик однажды уберут, режим у новой базы тихо вернётся к `delete` — а это уже
заметно только под нагрузкой, когда синк пишет, а дашборд читает.

Проверено на проде: «database is locked» там не встречалось ни разу (0 записей в
`sync_log` и 0 в логах контейнера), так что WAL здесь профилактика, а не лечение.
"""

import sys
from pathlib import Path

from sqlalchemy import create_engine, event, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import models  # noqa: E402
from config import settings  # noqa: E402


def _fresh_engine(tmp_path: Path):
    """Отдельная база и отдельный engine с тем же обработчиком pragma, что у приложения."""
    engine = create_engine(
        f"sqlite:///{tmp_path / 'pragma.db'}", connect_args={"check_same_thread": False}
    )
    event.listen(engine, "connect", models._sqlite_pragmas)
    return engine


def test_база_работает_в_режиме_wal(tmp_path):
    engine = _fresh_engine(tmp_path)
    with engine.connect() as conn:
        assert conn.execute(text("PRAGMA journal_mode")).scalar() == "wal"


def test_ожидание_блокировки_из_настройки(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "sqlite_busy_timeout_ms", 7000)
    engine = _fresh_engine(tmp_path)
    with engine.connect() as conn:
        assert conn.execute(text("PRAGMA busy_timeout")).scalar() == 7000


def test_synchronous_normal(tmp_path):
    """NORMAL (1) — штатная пара к WAL: fsync на чекпоинте, а не на каждой транзакции."""
    engine = _fresh_engine(tmp_path)
    with engine.connect() as conn:
        assert conn.execute(text("PRAGMA synchronous")).scalar() == 1


def test_на_другой_субд_pragma_не_применяются(monkeypatch):
    """Обработчик молча выходит, если БД не SQLite: этих pragma там нет."""
    monkeypatch.setattr(settings, "database_url", "postgresql://user@host/db")

    class Boom:
        def cursor(self):  # pragma: no cover — вызов означал бы, что проверка сломалась
            raise AssertionError("на не-SQLite pragma выполняться не должны")

    models._sqlite_pragmas(Boom(), None)
