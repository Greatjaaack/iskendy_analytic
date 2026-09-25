"""Выбор кассы по настройке `POS_PROVIDER` — единственное место, где это решается.

`get_pos()` отдаёт адаптер, реализующий `pos.base.PosClient`. Всё остальное
приложение (планировщик, роутеры, ручка табло) знает только этот контракт, поэтому
переезд с iiko на Saby Presto — это правка одной переменной окружения, а не кода.
"""

import logging

from config import settings
from pos.base import (
    ItemRow,
    PosClient,
    PosDay,
    PosHour,
    PosItem,
    PosOpenOrder,
    PosOrder,
    PosPayment,
    PosProduct,
    to_item_rows,
    to_order_rows,
    to_payment_rows,
)

logger = logging.getLogger(__name__)

PROVIDER_IIKO = "iiko"
PROVIDER_SABY = "saby"

_client: PosClient | None = None


def get_pos() -> PosClient:
    """Адаптер текущей кассы (создаётся один раз: у него кэш сессии/токена и каталога)."""
    global _client
    if _client is None:
        provider = (settings.pos_provider or PROVIDER_IIKO).strip().lower()
        if provider == PROVIDER_SABY:
            from pos.saby import SabyPos

            _client = SabyPos()
        elif provider == PROVIDER_IIKO:
            from pos.iiko import IikoPos

            _client = IikoPos()
        else:
            raise RuntimeError(
                f"POS_PROVIDER={provider!r} неизвестен (ожидается {PROVIDER_IIKO} или "
                f"{PROVIDER_SABY})"
            )
        logger.info("Касса: %s", _client.name)
    return _client


def reset_pos() -> None:
    """Сбросить кэшированный адаптер (нужно тестам и смене настроек на ходу)."""
    global _client
    _client = None


__all__ = [
    "ItemRow",
    "PROVIDER_IIKO",
    "PROVIDER_SABY",
    "PosClient",
    "PosDay",
    "PosHour",
    "PosItem",
    "PosOpenOrder",
    "PosOrder",
    "PosPayment",
    "PosProduct",
    "get_pos",
    "reset_pos",
    "to_item_rows",
    "to_order_rows",
    "to_payment_rows",
]
