"""Лимит обращений по IP — защита входа от перебора пароля.

Дашборд открыт в интернет (`analytics.iskendy.ru`), пароль один общий на весь
инструмент, и до 25.09.2026 попытки входа ничем не ограничивались: пароль можно было
перебирать со скоростью сети. Здесь — тот же приём, что давно работает в табло
(`iskendy_site`): скользящее окно на минуту, отдельная корзина на каждый вид обращения.

Состояние в памяти процесса: бэкенд запущен одним воркером (планировщик живёт в нём же),
поэтому общего хранилища не нужно. Перезапуск сбрасывает счётчики — для защиты от
перебора это приемлемо, а лишней зависимости (Redis) в проекте нет.
"""

import logging
import time

from fastapi import HTTPException, Request, status

logger = logging.getLogger(__name__)

WINDOW_SEC = 60
# Сколько попыток входа с одного адреса в минуту. Человек с забытым паролем укладывается,
# перебор — нет.
LOGIN_LIMIT = 10

# ключ корзины → времена обращений (monotonic)
_hits: dict[str, list[float]] = {}
# выше этого числа корзин подчищаем остывшие, чтобы словарь не рос вечно
_SWEEP_AT = 512


def client_ip(request: Request) -> str:
    """Адрес клиента с учётом прокси.

    Наружу стоит Caddy, за ним nginx фронта — оба добавляют себя в `X-Forwarded-For`.
    Доверяем заголовку только если запрос пришёл из приватной сети (то есть от нашего
    же прокси), иначе любой клиент мог бы подделать адрес и обойти лимит. Берём
    **последний** элемент цепочки: его подставил ближайший прокси, а первые могли
    прийти от самого клиента.
    """
    peer = request.client.host if request.client else ""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded and _is_private(peer):
        chain = [part.strip() for part in forwarded.split(",") if part.strip()]
        if chain:
            return chain[-1]
    return peer or "unknown"


def _is_private(ip: str) -> bool:
    """Приватный/локальный адрес — значит это наш прокси, а не клиент из интернета."""
    if not ip:
        return False
    if ip in ("127.0.0.1", "::1", "testclient"):
        return True
    return ip.startswith(("10.", "192.168.", "172.16.", "172.17.", "172.18.", "172.19."))


def rate_ok(key: str, limit: int) -> bool:
    """Не больше `limit` обращений по этому ключу за минуту."""
    now = time.monotonic()
    hits = [t for t in _hits.get(key, []) if now - t < WINDOW_SEC]
    if len(hits) >= limit:
        _hits[key] = hits
        return False
    hits.append(now)
    _hits[key] = hits
    if len(_hits) > _SWEEP_AT:
        for stale in [k for k, v in _hits.items() if not v or now - v[-1] > WINDOW_SEC]:
            _hits.pop(stale, None)
    return True


def guard(request: Request, limit: int, bucket: str) -> None:
    """Проверить лимит и ответить 429, если он выбран.

    `bucket` задаётся явно: два разных лимита легко оказываются равны по числу, и тогда
    они молча делят один счётчик.
    """
    ip = client_ip(request)
    if rate_ok(f"{bucket}:{ip}", limit):
        return
    logger.warning("лимит обращений: %s с адреса %s (%s)", bucket, ip, request.url.path)
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Слишком много попыток, попробуйте через минуту",
    )


def reset() -> None:
    """Сбросить счётчики (нужно тестам)."""
    _hits.clear()
