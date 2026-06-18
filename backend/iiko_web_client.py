"""
Клиент внутреннего API iikoweb.

Авторизация: headless-браузер (Playwright) логинится логином/паролем как человек,
забирает cookie-сессию, далее быстрые JSON-запросы идут через httpx с этими куками.
Сессия живёт ~20 мин — при истечении (HTTP 401 / authorized=false) перелогиниваемся.

Документация эндпоинтов и кодов метрик: см. IIKO_WEB_API.md
"""

import asyncio
import logging
from datetime import date, timedelta

import httpx

from config import settings
from constants import (
    DATA_DETAILS,
    DATA_SUMMARY_BY_DATE,
    DATA_SUMMARY_BY_HOURS,
    DATA_TOTAL,
    METRICS_DISHES,
    METRICS_HOURLY,
    METRICS_REVENUE_DAILY,
    METRICS_TOTALS,
    OLAP_FILTER_DATE,
    OLAP_STATUS_ERROR,
    OLAP_STATUS_SUCCESS,
    OLAP_TYPE_SALES,
    OLAP_VIEW_SIMPLE,
)

logger = logging.getLogger(__name__)

LOGIN_URL = f"{settings.iiko_web_url}/navigator/index.html#/auth/login"


class IikoWebClient:
    def __init__(self):
        self.base_url = settings.iiko_web_url
        self.store_id = settings.iiko_store_id
        self._cookies: dict[str, str] = {}
        self._lock = asyncio.Lock()

    # ---------- Авторизация ----------

    async def _login(self) -> None:
        """Логин через headless Chromium, извлечение cookie-сессии."""
        from playwright.async_api import async_playwright

        if not settings.iiko_web_login or not settings.iiko_web_password:
            raise RuntimeError("IIKO_WEB_LOGIN / IIKO_WEB_PASSWORD не заданы в .env")

        logger.info("iikoweb: логин через headless-браузер...")
        async with async_playwright() as p:
            # --no-sandbox обязателен при запуске Chromium от root в контейнере;
            # --disable-dev-shm-usage спасает от падений из-за маленького /dev/shm в Docker.
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            page = await browser.new_page()
            # networkidle на этой странице не наступает (Яндекс-метрика висит в сети) — ждём DOM.
            await page.goto(LOGIN_URL, wait_until="domcontentloaded")

            # Форма Angular Material; интерфейс может быть на англ. (Username / Password / SIGN IN).
            # Адресуемся по стабильным name-атрибутам, а не по тексту.
            # ВАЖНО: type() с задержкой, а не fill() — иначе валидаторы Angular не срабатывают,
            # кнопка submit остаётся disabled и click() висит до таймаута.
            await page.locator('input[name="login"]').wait_for(state="visible", timeout=20000)
            await page.click('input[name="login"]')
            await page.type('input[name="login"]', settings.iiko_web_login, delay=20)
            await page.click('input[name="password"]')
            await page.type('input[name="password"]', settings.iiko_web_password, delay=20)

            # Сабмит по Enter надёжнее клика по кнопке в SPA.
            await page.press('input[name="password"]', "Enter")

            # Ждём ухода со страницы логина (успешный вход меняет hash-маршрут на #/main).
            try:
                await page.wait_for_function(
                    "!location.hash.includes('/auth/login')", timeout=20000
                )
            except Exception:
                await page.wait_for_timeout(3000)

            cookies = await browser.contexts[0].cookies()
            self._cookies = {c["name"]: c["value"] for c in cookies}
            await browser.close()

        if not self._cookies:
            raise RuntimeError("iikoweb: не удалось получить cookies после логина")
        logger.info("iikoweb: сессия получена (%d cookies)", len(self._cookies))

    async def _ensure_session(self) -> None:
        if self._cookies and await self._check_auth():
            return
        async with self._lock:
            if self._cookies and await self._check_auth():
                return
            await self._login()

    async def _check_auth(self) -> bool:
        try:
            async with httpx.AsyncClient(cookies=self._cookies, timeout=15) as c:
                r = await c.get(f"{self.base_url}/api/auth")
                return r.status_code == 200 and r.json().get("authorized") is True
        except Exception:
            return False

    # ---------- Базовый запрос ----------

    async def _post(self, path: str, payload: dict, _retry: bool = True) -> dict:
        await self._ensure_session()
        async with httpx.AsyncClient(cookies=self._cookies, timeout=60) as c:
            r = await c.post(f"{self.base_url}{path}", json=payload)
            if r.status_code in (401, 403) and _retry:
                self._cookies = {}
                return await self._post(path, payload, _retry=False)
            r.raise_for_status()
            return r.json()

    async def _get(self, path: str, _retry: bool = True) -> dict:
        await self._ensure_session()
        async with httpx.AsyncClient(cookies=self._cookies, timeout=60) as c:
            r = await c.get(f"{self.base_url}{path}")
            if r.status_code in (401, 403) and _retry:
                self._cookies = {}
                return await self._get(path, _retry=False)
            r.raise_for_status()
            return r.json()

    # ---------- Данные (KPI get-data) ----------

    async def get_metrics(
        self,
        metric_codes: list[str],
        date_from: str,
        date_to: str,
        data_type: str = DATA_TOTAL,
        with_decoration: bool = False,
    ) -> dict:
        """Универсальный запрос метрик к `POST /api/kpi/dashboard/get-data`.

        Args:
            metric_codes: коды метрик (см. `constants.METRIC_*`).
            date_from, date_to: даты в формате ISO `YYYY-MM-DD` (включительно).
            data_type: разрез ответа (`constants.DATA_*`) — итог/по дням/по блюдам/по часам.
            with_decoration: вернуть ли блок decoration (справочник блюд).

        Returns:
            Без decoration — dict `{"<METRIC>": {"<ключ>": число}}` (ключ зависит от data_type).
            С decoration — кортеж `(data, decoration)`, где
            `decoration["product"][uuid] = {name, productCategory, productType, ...}`.

        Raises:
            RuntimeError: если iiko вернул `error` в теле ответа.
        """
        resp = await self._post(
            "/api/kpi/dashboard/get-data",
            {
                "dateFrom": date_from,
                "dateTo": date_to,
                "metricCodes": metric_codes,
                "storeIds": [self.store_id],
                "dataType": data_type,
            },
        )
        if resp.get("error"):
            raise RuntimeError(f"iikoweb get-data error: {resp.get('errorMessage')}")
        if with_decoration:
            return resp.get("data", {}), resp.get("decoration", {})
        return resp.get("data", {})

    async def revenue_by_day(self, date_from: str, date_to: str) -> dict:
        """Выручка/чеки/средний чек/скидки/возвраты/себестоимость по дням."""
        return await self.get_metrics(
            METRICS_REVENUE_DAILY,
            date_from,
            date_to,
            data_type=DATA_SUMMARY_BY_DATE,
        )

    async def revenue_by_hour(self, date_from: str, date_to: str) -> dict:
        """Выручка/чеки по часам (матрица часы×даты, см. `_parse_hour_matrix` в роутере)."""
        return await self.get_metrics(
            METRICS_HOURLY,
            date_from,
            date_to,
            data_type=DATA_SUMMARY_BY_HOURS,
        )

    async def dishes_detail(self, date_from: str, date_to: str) -> list[dict]:
        """Продажи по позициям номенклатуры с названиями/категориями/типом.

        Названия и категории берутся из `decoration.product` того же ответа.
        Возвращает список строк (отсортирован по выручке убыв.); поле `product_type`
        (`DISH`/`GOODS`/`MODIFIER`) нужно для фильтрации в «Продажах блюд».
        """
        data, decoration = await self.get_metrics(
            METRICS_DISHES,
            date_from,
            date_to,
            data_type=DATA_DETAILS,
            with_decoration=True,
        )
        qty = data.get(METRICS_DISHES[0], {})
        amt = data.get(METRICS_DISHES[1], {})
        cost = data.get(METRICS_DISHES[2], {})
        products = decoration.get("product", {})

        rows = []
        for dish_id in set(qty) | set(amt):
            meta = products.get(dish_id, {})
            rows.append(
                {
                    "dish_id": dish_id,
                    "dish_name": meta.get("name", dish_id),
                    "category": meta.get("productCategory", ""),
                    "product_type": meta.get("productType", ""),
                    "quantity": float(qty.get(dish_id, 0) or 0),
                    "revenue": float(amt.get(dish_id, 0) or 0),
                    "cost_sum": float(cost.get(dish_id, 0) or 0),
                }
            )
        rows.sort(key=lambda r: r["revenue"], reverse=True)
        return rows

    async def totals(self, date_from: str, date_to: str) -> dict:
        """Итоги за период — одно число на метрику."""
        return await self.get_metrics(
            METRICS_TOTALS,
            date_from,
            date_to,
            data_type=DATA_TOTAL,
        )

    # ---------- OLAP (асинхронные отчёты SALES) ----------

    async def olap_sales(
        self,
        group_fields: list[str],
        data_fields: list[str],
        date_from: str,
        date_to: str,
        poll_attempts: int = 30,
    ) -> list[dict]:
        """OLAP-отчёт SALES: init → поллинг статуса → выгрузка результата.

        Нужен для разрезов, которые `get-data` не умеет (напр. «час × блюдо»).
        Возвращает `result.rows` — список строк вида
        `{"field0": {"value": "<группа>"}, "field1": {"value": <число>}, ...}`,
        где field0 — склейка group_fields через ", ", далее идут data_fields по порядку.
        """
        # dateTo делаем эксклюзивным концом следующего дня, чтобы включить весь date_to
        date_to_excl = (date.fromisoformat(date_to) + timedelta(days=1)).isoformat()
        req = {
            "storeIds": [self.store_id],
            "olapType": OLAP_TYPE_SALES,
            "groupFields": group_fields,
            "dataFields": data_fields,
            "filters": [
                {
                    "filterType": "date_range",
                    "field": OLAP_FILTER_DATE,
                    "dateFrom": date_from,
                    "dateTo": date_to_excl,
                    "includeLeft": True,
                    "includeRight": False,
                }
            ],
            "includeVoidTransactions": False,
        }
        init = await self._post("/api/olap/init", req)
        h = init.get("data")
        if not h:
            raise RuntimeError("iikoweb olap: init не вернул hash")

        status = None
        for _ in range(poll_attempts):
            status = (await self._get(f"/api/olap/fetch-status/{h}")).get("data")
            if status in (OLAP_STATUS_SUCCESS, OLAP_STATUS_ERROR):
                break
            await asyncio.sleep(1)
        if status != OLAP_STATUS_SUCCESS:
            raise RuntimeError(f"iikoweb olap: статус {status}")

        resp = await self._post(f"/api/olap/fetch/{h}/{OLAP_VIEW_SIMPLE}", req)
        return resp.get("result", {}).get("rows", [])

    # Каталог всех метрик (408 шт) — справочник кодов/названий
    async def metrics_catalog(self) -> list[dict]:
        resp = await self._post("/api/kpi/directory/bystores", {"storeIds": [self.store_id]})
        return resp if isinstance(resp, list) else list(resp.values())


iiko_web = IikoWebClient()
