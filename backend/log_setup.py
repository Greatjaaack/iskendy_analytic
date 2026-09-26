"""Настройка журнала приложения: что пишем, а что — шум.

Замер на проде 26.09.2026: **2 196 строк в час, из них ~90 % шум** — 717 строк `httpx`
про проверку сессии iiko, 345 строк access-лога опроса табло `/api/orders/today`
(раз в ~10 с), по две строки APScheduler на каждый запуск `sync_today` (раз в 3 минуты).
Docker хранит 3 × 10 МБ лога, так что шум вытеснял предупреждения и трейсы через
несколько дней — ровно тогда, когда их приходят искать.

Что убираем:
- `httpx`/`httpcore` — только WARNING и выше (ошибки запросов всё равно всплывают
  исключениями и логируются там, где их ловят);
- `apscheduler.executors` — только WARNING: «Running job» / «executed successfully»
  без пользы, а упавший job APScheduler пишет ERROR'ом и мы его увидим;
- access-лог uvicorn — без УСПЕШНЫХ запросов к путям из `QUIET_PATHS` (опрос табло,
  healthcheck). Ответ 4xx/5xx на них по-прежнему пишется.
"""

import logging

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

# Пути, успешные запросы к которым не пишутся в access-лог: их дёргают автоматы.
QUIET_PATHS = ("/api/orders/today", "/api/health")

_QUIET_LOGGERS = ("httpx", "httpcore", "apscheduler.executors")


class QuietPathsFilter(logging.Filter):
    """Отсев успешных запросов к `QUIET_PATHS` из access-лога uvicorn.

    Запись uvicorn.access несёт `args = (клиент, метод, путь, http-версия, статус)`.
    Запись другого вида пропускаем как есть — фильтр не должен терять чужие строки.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if not isinstance(args, tuple) or len(args) < 5:
            return True
        path, status = str(args[2]), args[4]
        quiet = path.split("?", 1)[0] in QUIET_PATHS
        try:
            ok = int(status) < 400
        except (TypeError, ValueError):
            return True
        return not (quiet and ok)


def setup_logging() -> None:
    """Формат с именем логгера (видно, кто пишет: `pos.saby`, `scheduler`…) и отсев шума.

    Uvicorn настраивает свои логгеры до импорта приложения, поэтому фильтр на
    `uvicorn.access`, повешенный здесь, переживает его настройку.
    """
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
    for name in _QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
    access = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, QuietPathsFilter) for f in access.filters):
        access.addFilter(QuietPathsFilter())
