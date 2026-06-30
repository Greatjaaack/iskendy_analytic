"""
Погода по Москве на дату — из Open-Meteo (бесплатно, без API-ключа).

Используется для отображения погоды рядом с выручкой по дням (чтобы видеть связь
выручки с погодой). Данные кэшируются по дате в памяти процесса.

Замечание: архивный API Open-Meteo отстаёт на ~5 дней (свежие даты он отдаёт с 400),
поэтому для свежих дат (последняя неделя и сегодня) берём forecast-API, а для более
старых — archive-API. Для дальнего будущего (или если API недоступен) возвращаются
пустые значения — фронт показывает «—».
"""

import logging
from datetime import date, timedelta

import httpx

from utils import today

logger = logging.getLogger(__name__)

# Координаты Москвы (центр)
MOSCOW_LAT = 55.7558
MOSCOW_LON = 37.6173
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
# Архив отстаёт на ~5 дней; с запасом считаем «свежими» последние 7 дней и берём их
# из forecast-API (он отдаёт прошлые дни через past_days и ближайший прогноз).
RECENT_DAYS = 7

# Кэш: ISO-дата → {"temp_max", "weather_code"}.
# Храним только дневную температуру (temp_max) — ночная (temp_min) не нужна.
_cache: dict[str, dict] = {}


async def get_weather(date_from: str, date_to: str) -> dict[str, dict]:
    """Погода по дням за диапазон. Возвращает {ISO-дата: {temp_max, weather_code}}.

    Уже закэшированные даты не запрашиваются повторно. При ошибке сети возвращает
    то, что есть в кэше (пустой dict в худшем случае) — вызов не падает.
    """
    # какие даты ещё не в кэше — только их и запрашиваем
    missing = _missing_dates(date_from, date_to)
    if missing:
        # граница «свежих» дат: их отдаёт forecast-API, старее — archive-API
        cutoff = (today() - timedelta(days=RECENT_DAYS)).isoformat()
        old = [d for d in missing if d < cutoff]
        recent = [d for d in missing if d >= cutoff]
        for url, dates in ((ARCHIVE_URL, old), (FORECAST_URL, recent)):
            if not dates:
                continue
            try:
                await _fetch_range(url, min(dates), max(dates))
            except Exception as error:  # погода не критична — не роняем дашборд, но логируем трейс
                logger.warning("weather: запрос не удался (%s)", url, exc_info=error)

    return {d: _cache[d] for d in _date_range(date_from, date_to) if d in _cache}


def _date_range(date_from: str, date_to: str) -> list[str]:
    d0, d1 = date.fromisoformat(date_from), date.fromisoformat(date_to)
    out, d = [], d0
    while d <= d1:
        out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _missing_dates(date_from: str, date_to: str) -> list[str]:
    return [d for d in _date_range(date_from, date_to) if d not in _cache]


async def _fetch_range(url: str, date_from: str, date_to: str) -> None:
    params = {
        "latitude": MOSCOW_LAT,
        "longitude": MOSCOW_LON,
        "start_date": date_from,
        "end_date": date_to,
        "daily": "temperature_2m_max,weather_code",
        "timezone": "Europe/Moscow",
    }
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(url, params=params)
        r.raise_for_status()
        daily = r.json().get("daily", {})

    times = daily.get("time", [])
    tmax = daily.get("temperature_2m_max", [])
    codes = daily.get("weather_code", [])
    for i, day in enumerate(times):
        _cache[day] = {
            "temp_max": tmax[i] if i < len(tmax) else None,
            "weather_code": codes[i] if i < len(codes) else None,
        }
