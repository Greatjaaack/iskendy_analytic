# iikoweb внутренний API — справочник (reverse-engineered)

Базовый URL: `https://iskendi.iikoweb.ru`
Авторизация: **cookie-сессия** (логин в веб-интерфейсе). TTL сессии — 1200 сек (20 мин).
Точка (store): **Искенди, storeId = 161059**, domain = `iskendi`.

## Авторизация / сессия

| Эндпоинт | Метод | Назначение |
|---|---|---|
| `/api/auth` | GET | Проверка сессии. Возвращает user, storeId, storeIds, sessionTtl, licences |
| `/api/stores/list` | GET | Список точек |

Страница входа: `/navigator/index.html#/auth/login` — поля «Логин» и «Пароль», кнопка «Войти».

### Авторизация на сервере: headless-браузер (Playwright)
Внутренний API защищён cookie-сессией (TTL 20 мин). Точный login-endpoint не реверсили
намеренно (фильтр безопасности не отдаёт пароль/куки в контекст — и не нужно).
Подход: на сервере Playwright (headless Chromium) вводит логин/пароль как человек →
забирает cookies → передаёт их в httpx для быстрых JSON-запросов. Re-login при 401/истечении.
Пароль — только в `.env`/секретах сервера.

## Главный эндпоинт данных (KPI)

`POST /api/kpi/dashboard/get-data`

```json
{
  "dateFrom": "2026-06-10",
  "dateTo": "2026-06-17",
  "metricCodes": ["REV_GROSS", "TRN_ALL"],
  "storeIds": [161059],
  "dataType": "DATA_SUMMARY_BY_DATE"
}
```

Ответ: `{ "data": { "<METRIC_CODE>": { "<ключ>": число } } }`
Ключ зависит от `dataType` (дата, UUID блюда, store, час...).

### dataType (валидные значения)
- `DATA_TOTAL` — одно число (итог за период)
- `DATA_TOTAL_AVERAGE` — среднее
- `DATA_SUMMARY_BY_DATE` — разбивка по дням ← **выручка по дням**
- `DATA_DETAILS` — разбивка по блюдам (ключ = UUID блюда) + блок `decoration.product` ← **блюда** (значение в коде — `constants.DATA_DETAILS`)
- `DATA_TOTAL_BY_HOURS` / `DATA_SUMMARY_BY_HOURS` — по часам
- `DATA_SUMMARY_BY_PERIODS`, `DATA_SUMMARY_BY_STORE`, `DATA_DETAILS_BY_DATE` и др.

### Проверенные коды метрик (на данных за 2026-06-17)
| Код | Название | Значение 06-17 |
|---|---|---|
| `REV_GROSS` | Выручка | 11780 |
| `REV_NET` | Выручка чистая | 11780 |
| `TRN_ALL` | Чеки / Заказы | 13 |
| `AVERAGE_SPEND_GROSS` | Средний чек | 906.15 (= 11780/13 ✓) |
| `REFUND_TRN` | Кол-во возвратов | 0 |
| `ACC_CAT_DISCOUNT_AMT` | Скидки | 0 |
| `PRODUCTS_USAGE_THEO_AMT` | Себестоимость блюд (с/с) | 350.96 |
| `PRODUCTS_COS_THEO_GROSS` | Себестоимость к выручке (food cost %) | — |
| `ITEM_SOLD_QTY` | Продажи блюд, по кол-ву | 40 |
| `ITEM_SOLD_AMT` | Продажи блюд, по выручке | 11780 |
| `SALES_GROSS_BY_PRODUCT_CAT` | Выручка по категориям | 11780 |
| `REV_GROSS_BYPAYMENT` | Выручка по типам оплаты | 11780 |

> ⚠️ Бухгалтерские метрики `ACC_CAT_SALES_NET/GROSS_AMT`, НДС возвращают 0 — учётные категории/НДС в этой точке не ведутся. Использовать `REV_GROSS`.

### Словарь блюд — в том же ответе! (`decoration`)
При `dataType: "DATA_DETAILS"` ответ содержит блок `decoration.product`:
```json
"decoration": { "product": {
  "<uuid>": { "id","num","name":"Комбо лайт (Мини + суп 200гр)",
              "productType":"DISH","productCategory":"Комбо",
              "mainUnit":"шт","cookingPlaceType":"Кухня","deleted":false }
}}
```
→ отдельный эндпоинт справочника блюд НЕ нужен. Берём `name` + `productCategory` отсюда.
Себестоимость блюда `PRODUCTS_USAGE_THEO_AMT` приходит по расходу продуктов
(ключи — продукты-ингредиенты, не всегда совпадают с UUID проданного блюда).

### Справочник метрик
`POST /api/kpi/directory/bystores` body `{"storeIds":[161059]}`
→ массив из **408 метрик**, поля: `kpiCode`, `kpiName`, `kpiDescription`, `categoryType`, `valueType`.

### Конфиг дашборда (готовые наборы метрик)
`GET /api/kpi/dashboard/config/get/{id}` — напр. 532 = «Основные показатели», 411 = «Отчёт о продажах».

## OLAP-движок (гибкие отчёты, асинхронный)

1. `POST /api/olap/init` — запуск, возвращает `{"data": "<hash>"}`
2. `GET /api/olap/fetch-status/<hash>` — поллинг (`IN_PROGRESS` → `READY`/`ERROR`)
3. результат по готовности

Тело init (пример «Доходы и расходы», olapType `TRANSACTIONS`):
```json
{
  "storeIds":[161059], "olapType":"TRANSACTIONS",
  "groupFields":["Account.Type","Account.AccountHierarchyTop","Account.AccountHierarchySecond"],
  "dataFields":["sum_signed"],
  "calculatedFields":[{"name":"sum_signed","title":"Сумма","formula":"[Sum.Outgoing]-[Sum.Incoming]","type":"MONEY","canSum":true}],
  "filters":[
    {"filterType":"date_range","dateFrom":"2026-06-17","dateTo":"2026-06-17","field":"DateTime.OperDayFilter","includeLeft":true,"includeRight":true},
    {"field":"Account.Group","filterType":"value_list","valueList":["INCOME_EXPENSES"],"inclusiveList":true}
  ],
  "includeVoidTransactions":false
}
```
olapType: `TRANSACTIONS` (проводки/доходы-расходы), `SALES` (продажи). Точные имена полей SALES — добрать из готового пресета (валидные ловятся из ошибки fetch-status).

### Проверенные поля OLAP SALES (Искенди, июнь 2026)
Группировки: `OrderNum` (номер заказа), `DishName`, `DishCategory`, `HourOpen`,
`OpenTime`/`CloseTime` (ISO-таймстамп), `SessionNum`, `Cashier`, `Department`.
Данные: `DishAmountInt` (кол-во), `DishSumInt` (сумма без скидки).
Невалидные (OLAP → ERROR): `UniqOrderId`, `OrderId`, `Order.Num`, `Modifier`,
`ServiceType`, `OrderType.Name`, `Waiter`.
⚠️ **Тип обслуживания НЕ в `OrderType`/`OrderServiceType`** — они почти всегда пусты
(только редкие «Обычный заказ»/`COMMON`). Канал (Доставка/В зале/С собой) задаётся
**модификатором категории «Статус» на уровне заказа** — в OLAP это отдельная строка
блюда (`DishCategory="Статус"`, `DishName`∈{Доставка,В зале,С собой}). Разрез блюдо×канал:
группировка `[OrderNum, DishCategory, DishName]`, у каждого заказа берём «Статус» и
относим к нему все его блюда (см. `/api/dishes/service-breakdown`). field0 склеивает
группы через «, ».

## Готовые OLAP-шаблоны (presets)
Доходы и расходы, Отчёт по официантам, по скидкам, по типам оплаты, почасовой, по ингредиентам.
`GET /api/analytics/olap/presets/get/<presetId>`

## Прочие эндпоинты загрузки
`/api/config/get`, `/api/permissions/my`, `/api/kpi-metric/stores`, `/api/app/menu`,
`/api/kpi-dashboard/system-strings`.

## ВАЖНО про технику
- Приложение на **Angular → использует XMLHttpRequest**, не fetch. Для перехвата патчить `XMLHttpRequest.prototype.open/send`.
- Микрофронтенды отчётов перезагружают window-контекст при SPA-переходе (интерсептор слетает) — переставлять после каждого перехода.
