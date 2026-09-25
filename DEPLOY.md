# Деплой Iskendy Analytics на сервер

Запуск на VPS в Docker с автоматическим HTTPS. Локальная разработка — в `CLAUDE.md`
(`docker compose up -d --build`, без TLS, порты 5173/8000 наружу).

## Что нужно на сервере

- Docker + docker compose (плагин v2).
- **Открытые порты 80 и 443** (для Let's Encrypt и доступа к дашборду).
- **Домен** с A-записью DNS на IP сервера (для авто-HTTPS). Без домена можно
  по IP с self-signed (см. `caddy/Caddyfile`), но браузер будет ругаться на сертификат.
- Память: ~1–2 ГБ достаточно (Playwright поднимает Chromium на перелогин раз в ~20 мин).
  3 ГБ — с запасом, ни о чём беспокоиться не нужно.

## Чек-лист первого запуска

1. **Склонировать репозиторий:**
   ```bash
   git clone git@github.com:Greatjaaack/iskendy_analytic.git
   cd iskendy_analytic
   ```

2. **Создать `.env`** (его нет в git — заполнить вручную):
   ```bash
   cp .env.example .env
   ```
   Обязательно проставить реальные значения:
   - `IIKO_WEB_PASSWORD` — пароль от iikoweb (иначе логина в iiko нет → данные не выкачаются);
   - `AUTH_PASSWORD` — **свой** пароль входа в дашборд (не `change_me`!);
   - `JWT_SECRET` — задать свой случайный секрет (`openssl rand -hex 32`);
   - `DOMAIN` — ваш домен (например `analytics.iskendi.ru`).

3. **Поднять прод-конфигурацию:**
   ```bash
   docker compose -f docker-compose.prod.yml up -d --build
   ```
   Caddy сам получит TLS-сертификат для `DOMAIN` (нужны открытые 80/443 и DNS).

4. **Проверить логи** — первый запуск логинится в iiko и запускает бэкафилл всей истории:
   ```bash
   docker compose -f docker-compose.prod.yml logs -f backend
   ```
   Ищите успешный логин («iikoweb: логин через headless-браузер...» → без ошибок) и
   старт синков. Бэкафилл идёт **в фоне** (десятки минут на первый прогон) — дашборд
   при этом уже работает на выручке за 31 день.

5. Открыть `https://<DOMAIN>` → войти логином/паролем из `.env`.

## Как это работает

```
Интернет → Caddy (443, авто-TLS) → frontend:80 (nginx, SPA)
                                         └─ /api/* → backend:8000 (FastAPI)
```

- **Caddy** терминирует HTTPS и продлевает сертификат сам.
- **backend** и **frontend** наружу НЕ опубликованы (`expose`, не `ports`) — снаружи
  доступны только через Caddy. Пароль дашборда не летит по сети открытым текстом.
- БД (`/data/iskendi.db`) и файлы (`/data/files`) — в volume `backend-data`,
  переживают пересборку и перезапуск.

## Данные из iiko (что качается и когда)

- **При старте:** синхронно выручка за 31 день (готова сразу), затем в фоне —
  свежие заказы + `backfill` всей истории заказов (разово, долго).
- **По расписанию** (APScheduler, `Europe/Moscow`): каждый час — выручка и свежие
  заказы за 7 дней; ночью 00:05 — полный синк + бэкафилл.
- Живые запросы к iiko делает только планировщик; дашборд читает из SQLite.

## Эксплуатация

```bash
# Обновить до свежего кода:
git pull
docker compose -f docker-compose.prod.yml up -d --build

# Логи / статус:
docker compose -f docker-compose.prod.yml logs -f backend
docker compose -f docker-compose.prod.yml ps

# Остановить (данные в volume сохраняются):
docker compose -f docker-compose.prod.yml down

# Ручной синк (без UI): нужен токен авторизации — проще нажать «Синхронизировать»
# в дашборде. Health-check публичен:
curl https://<DOMAIN>/api/health
```

> ⚠️ `docker compose ... down -v` удалит volume вместе с БД и файлами. Без `-v` данные
> остаются. При смене СУЩЕСТВУЮЩЕЙ схемы БД (миграций нет) пересоздание делается
> именно через `down -v` — это сотрёт накопленную историю. Заказы и выручка
> перельются бэкафиллом из iiko, **а поставщики, цены, ТТК и себестоимость — нет:
> они вбиты руками и в iiko их не существует**. Перед `down -v` — снять копию
> (см. ниже) и убедиться, что она открывается.

## Бэкапы БД

Суточная копия базы с ротацией на 30 штук и выгрузкой на Google Диск владельца.

| | |
|---|---|
| Скрипт | `/root/dashboards-backup.sh` на сервере, эталон в репозитории — `ops/backup.sh` |
| Крон | `15 4 * * *` (сайт-табло выгружается в 03:30 — время разведено, чтобы не толкаться) |
| Копии на сервере | `/root/backups/analytics/iskendi-<YYYYmmdd-HHMMSS>.db.gz`, последние 30 |
| Копии снаружи | `yadisk:Искенди/бэкапы-аналитика` (rclone, конфиг `/root/.config/rclone/rclone.conf`) |
| Лог | `/var/log/iskendy-analytics-backup.log` |
| Тревоги | через `/root/iskendy/guard.sh --raise/--resolve` в тему 858 рабочего чата |

Как снимается: **не** копированием файла — приложение пишет в базу постоянно, и
копия живого файла выйдет рваной. Внутри контейнера python делает
`sqlite3.Connection.backup()` — согласованный снимок под блокировкой самой SQLite,
без остановки сервиса, — и тут же проверяет его `PRAGMA integrity_check`.

С 25.09.2026 база работает в режиме **WAL**, поэтому рядом с `iskendi.db` в томе
появляются `iskendi.db-wal` и `iskendi.db-shm`. Для бэкапа это ничего не меняет:
`.backup()` учитывает журнал и отдаёт согласованный снимок одним файлом. А вот копировать
базу «руками» (`cp`/`docker cp` одного `.db`) при WAL тем более нельзя — без `-wal` часть
последних транзакций потеряется. Нужна копия на ходу — снимать тем же способом, что и
крон (см. скрипт), либо остановив контейнер.

Наружу — `rclone copy`, **не** `sync`: локально держим 30 копий, sync удалял бы на
Диске всё, что старше, то есть ровно тот архив, ради которого всё затевалось.
Выгрузка идёт тремя попытками с паузой 5 минут, тревога поднимается только если не
прошла ни одна: сетевой промах ночью — не повод будить людей, каждый промах и так
остаётся в логе. Скрипт задаёт
`PATH` и `--config` явно: крон запускает его почти с пустым окружением, `$HOME` там
нет и конфиг rclone не находится. Проверять правки запуском `env -i /root/dashboards-backup.sh`.

Снять копию вручную (перед любой рискованной операцией):

```bash
/root/dashboards-backup.sh          # снимет, положит локально и выгрузит на Диск
```

**Восстановление** — единственная проверка, которая что-то значит. Бэкап, который не
разворачивали, бэкапом не является:

```bash
# 1. забрать копию с Диска (а не локальную — проверяем весь путь)
rclone --config /root/.config/rclone/rclone.conf \
  copy "yadisk:Искенди/бэкапы-аналитика/iskendi-<стамп>.db.gz" /tmp/restore
gunzip /tmp/restore/iskendi-<стамп>.db.gz

# 2. открыть и посчитать строки, не трогая боевую базу
docker cp /tmp/restore/iskendi-<стамп>.db dashboards-backend-1:/tmp/restored.db
docker exec dashboards-backend-1 python3 -c "import sqlite3;\
c=sqlite3.connect('file:/tmp/restored.db?mode=ro',uri=True);\
print(c.execute('PRAGMA integrity_check').fetchone());\
print([(n[0], c.execute('SELECT count(*) FROM \"%s\"' % n[0]).fetchone()[0]) \
       for n in c.execute('SELECT name FROM sqlite_master WHERE type=\"table\"')])"

# 3. вернуть в бой (только при остановленном backend — иначе снимок разъедется)
docker compose -f docker-compose.prod.yml stop backend
docker cp /tmp/restore/iskendi-<стамп>.db dashboards-backend-1:/data/iskendi.db
docker compose -f docker-compose.prod.yml start backend
```

**Почему Яндекс, а не Google.** Сначала копии уезжали на Google Диск, но `rclone`
ходит туда под встроенным client_id, общим для всех его пользователей в мире, и
упирается в поминутную квоту `rateLimitExceeded`. 24.08 и 25.08 ночная выгрузка не
прошла ни с первой попытки, ни со второй, а ручной запуск через полчаса проходил
сразу. Свой client_id завести не вышло: Google требует политику конфиденциальности
и подтверждённый домен. У Яндекса квоты нет — 35 файлов залились с первого раза.
Токен в `rclone.conf` выдан до 25.08.2027, **продлевать за месяц**.

Проверено 24.08.2026 (Google) и 25.08.2026 (Яндекс): копия скачана с Диска,
развёрнута, `integrity_check=ok`, число строк во всех 20 таблицах совпало с
боевой базой.

## Общий Caddy — как правится

Конфиг лежит в `caddy/Caddyfile` и монтируется в контейнер **каталогом**
(`./caddy:/etc/caddy:ro`), а не файлом. Это не косметика: bind-mount одиночного
файла держится за его inode, а `git pull` пишет новый файл и переименовывает —
inode меняется, и контейнер продолжает читать СТАРУЮ версию. 24.08.2026 на этом
обожглись: `caddy reload` отработал «успешно» на устаревшем конфиге, md5 файла на
хосте и в контейнере разошлись, а поняли это только по прямой сверке. С каталогом
`reload` честный.

Caddy общий для трёх продуктов (analytics.iskendy.ru, iskendy.ru, чужой
bot.iskendy.ru), поэтому после правки проверять **все три**, а не свой:

```bash
docker exec dashboards-caddy-1 caddy validate --config /etc/caddy/Caddyfile
docker exec dashboards-caddy-1 caddy reload --config /etc/caddy/Caddyfile
curl -s -o /dev/null -w "%{http_code}\n" https://analytics.iskendy.ru/api/health
curl -s -o /dev/null -w "%{http_code}\n" https://iskendy.ru/api/health
curl -s -o /dev/null -w "%{http_code}\n" https://bot.iskendy.ru
```

Если конфиг меняли не через git, а руками на сервере — валидировать НОВЫЙ файл
одноразовым контейнером, иначе `caddy validate` проверит тот, что уже внутри:

```bash
docker run --rm -e DOMAIN=analytics.iskendy.ru \
  -v /root/dashboards/caddy/Caddyfile:/etc/caddy/Caddyfile:ro \
  caddy:2-alpine caddy validate --config /etc/caddy/Caddyfile
```

## Запуск без домена (по IP, для теста)

В `caddy/Caddyfile` закомментировать блок `{$DOMAIN}` и раскомментировать блок `:443`
с `tls internal`. Caddy отдаст self-signed сертификат — браузер предупредит, но
соединение будет зашифровано. Для постоянной работы лучше завести домен.
