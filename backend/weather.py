"""
Погода по Москве на дату — из Open-Meteo (бесплатно, без API-ключа).

Используется для отображения погоды рядом с выручкой по дням (чтобы видеть связь
выручки с погодой). Данные кэшируются по дате в памяти процесса.

Замечание: исторический архив Open-Meteo покрывает прошлые даты; для будущих дат
(или если API недоступен) возвращаются пустые значения — фронт показывает «—».
"""

import logging

import httpx

logger = logging.getLogger(__name__)

# Координаты Москвы (центр)
MOSCOW_LAT = 55.7558
MOSCOW_LON = 37.6173
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

# Кэш: ISO-дата → {"temp_max", "temp_min", "weather_code"}
_cache: dict[str, dict] = {}


async def get_weather(date_from: str, date_to: str) -> dict[str, dict]:
    """Погода по дням за диапазон. Возвращает {ISO-дата: {temp_max, temp_min, weather_code}}.

    Уже закэшированные даты не запрашиваются повторно. При ошибке сети возвращает
    то, что есть в кэше (пустой dict в худшем случае) — вызов не падает.
    """
    # какие даты ещё не в кэше — только их и запрашиваем
    missing = _missing_dates(date_from, date_to)
    if missing:
        try:
            await _fetch_range(min(missing), max(missing))
        except Exception as error:  # погода не критична — не роняем дашборд, но логируем трейс
            logger.warning("weather: запрос не удался", exc_info=error)

    return {d: _cache[d] for d in _date_range(date_from, date_to) if d in _cache}


def _date_range(date_from: str, date_to: str) -> list[str]:
    from datetime import date, timedelta

    d0, d1 = date.fromisoformat(date_from), date.fromisoformat(date_to)
    out, d = [], d0
    while d <= d1:
        out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _missing_dates(date_from: str, date_to: str) -> list[str]:
    return [d for d in _date_range(date_from, date_to) if d not in _cache]


async def _fetch_range(date_from: str, date_to: str) -> None:
    params = {
        "latitude": MOSCOW_LAT,
        "longitude": MOSCOW_LON,
        "start_date": date_from,
        "end_date": date_to,
        "daily": "temperature_2m_max,temperature_2m_min,weather_code",
        "timezone": "Europe/Moscow",
    }
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(ARCHIVE_URL, params=params)
        r.raise_for_status()
        daily = r.json().get("daily", {})

    times = daily.get("time", [])
    tmax = daily.get("temperature_2m_max", [])
    tmin = daily.get("temperature_2m_min", [])
    codes = daily.get("weather_code", [])
    for i, day in enumerate(times):
        _cache[day] = {
            "temp_max": tmax[i] if i < len(tmax) else None,
            "temp_min": tmin[i] if i < len(tmin) else None,
            "weather_code": codes[i] if i < len(codes) else None,
        }
