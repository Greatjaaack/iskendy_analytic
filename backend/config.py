"""Конфигурация приложения — один типизированный класс на pydantic BaseSettings.

Значения берутся из переменных окружения (в Docker — из env_file `.env`), имена полей
соответствуют именам переменных без учёта регистра: `iiko_web_url` ← `IIKO_WEB_URL`.
Так все параметры окружения собраны в одном месте, валидируются и имеют дефолты.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # iikoweb (внутренний API через cookie-сессию)
    iiko_web_url: str = "https://iskendi.iikoweb.ru"
    iiko_web_login: str = ""
    iiko_web_password: str = ""
    iiko_store_id: int = 161059

    # хранилище
    database_url: str = "sqlite:///./iskendi.db"
    files_dir: str = "/data/files"

    # часовой пояс ресторана: определяет границы «сегодня/неделя/месяц» и расписание
    # синков. Не зависит от TZ контейнера (там обычно UTC). Точка московская (см. погоду).
    timezone: str = "Europe/Moscow"

    # TTL in-memory кэша живых чтений из iikoweb (get-data/OLAP), сек. 0 — кэш выключен.
    # Короткий TTL схлопывает повторные одинаковые запросы дашборда, не задерживая
    # обновление дольше этого окна. Сбрасывается при ручном синке.
    cache_ttl_seconds: int = 60


settings = Settings()
